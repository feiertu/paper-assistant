"""Docling PDF 解析器（IBM 开源）。

核心理念：将 PDF 精准转换为 Markdown 格式，保留表格（HTML）、公式（LaTeX）、
阅读顺序（解决多栏问题）和文档层级结构。

Markdown 是 RAG 语料的黄金标准——大模型对标题层级、粗体/斜体、列表、
代码块、表格标签化的理解能力远超纯文本。

依赖：pip install docling（可选；未安装时回退到 pymupdf）
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config
from src.logging_config import get_logger

from .schemas import Figure, PaperMetadata, ParsedPaper, Section, Table

logger = get_logger(__name__)

# ── 尝试导入 docling ──
try:
    from docling.document_converter import DocumentConverter
    _HAS_DOCLING = True
except ImportError:
    _HAS_DOCLING = False
    DocumentConverter = None  # type: ignore


def _check_docling():
    """检查 docling 是否可用，不可用时给出友好提示。"""
    if not _HAS_DOCLING:
        raise ImportError(
            "docling 未安装。请运行: pip install docling\n"
            "或设置 PDF_PARSER=pymupdf 使用 PyMuPDF 解析。"
        )


# ── Markdown 解析为结构化 Section ──

# 匹配 Markdown 标题行（# 到 ######）
_MD_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)

# 匹配 Markdown 表格块
_MD_TABLE_RE = re.compile(r'^\|.+\|$', re.MULTILINE)

# HTML 表格（docling 可为表格输出 HTML）
_HTML_TABLE_RE = re.compile(r'<table[^>]*>.*?</table>', re.DOTALL | re.IGNORECASE)

# LaTeX 公式块
_LATEX_DISPLAY_RE = re.compile(r'\$\$[^$]+\$\$', re.DOTALL)
_LATEX_INLINE_RE = re.compile(r'\$[^$]+\$')


def _clean_markdown(text: str) -> str:
    """清理 Markdown 文本，去除多余空白但不破坏结构。"""
    # 压缩连续空行为双空行（保留段落分隔）
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _split_by_headings(markdown: str) -> List[Dict[str, Any]]:
    """按 Markdown 标题层级将文档拆分为层级结构。

    返回树形结构列表，每项为：
    {
        "title": str,
        "level": int,         # 1-6 对应 h1-h6
        "content": str,       # 该标题下的直接内容（不含子标题内容）
        "children": [...],    # 子节点
        "tables": [...],
    }
    """
    lines = markdown.split('\n')
    root_children: List[Dict] = []
    # 栈：当前各级活跃节点，stack[i] 对应 level=i+1 的节点
    stack: List[Dict] = []

    # 内容缓冲：收集当前节点下的纯文本行（不含表格和子标题）
    content_buf: List[str] = []
    table_buf: List[str] = []
    in_table = False

    def _flush_content():
        """将缓冲文本写入当前活跃节点。"""
        nonlocal content_buf, table_buf, in_table
        if in_table:
            if table_buf:
                # 找到当前最深的活跃节点附加表格
                for node in reversed(stack):
                    if "tables" not in node:
                        node["tables"] = []
                    node["tables"].append('\n'.join(table_buf))
                    break
            table_buf = []
            in_table = False
        if content_buf:
            text = _clean_markdown('\n'.join(content_buf))
            if text and stack:
                stack[-1]["content"] += ('\n\n' + text if stack[-1]["content"] else text)
            elif text and not stack:
                # 根级别内容（Abstract 等前置内容）
                pass
            content_buf = []

    for line in lines:
        # 检测标题行
        m = _MD_HEADING_RE.match(line)
        if m:
            _flush_content()
            level = len(m.group(1))
            title = m.group(2).strip()

            node = {
                "title": title,
                "level": level,
                "content": "",
                "children": [],
                "tables": [],
            }

            # 弹出所有同级或更深层的节点
            while stack and stack[-1]["level"] >= level:
                stack.pop()

            if stack:
                stack[-1]["children"].append(node)
            else:
                root_children.append(node)

            stack.append(node)
            continue

        # 检测表格行
        if _MD_TABLE_RE.match(line.strip()) or _HTML_TABLE_RE.match(line.strip()):
            if not in_table:
                _flush_content()
                in_table = True
            table_buf.append(line)
            continue
        elif in_table and line.strip() and not _MD_TABLE_RE.match(line.strip()):
            # 表格结束
            _flush_content()

        # 普通内容行
        if in_table:
            table_buf.append(line)
        else:
            content_buf.append(line)

    _flush_content()

    return root_children


def _build_sections(
    nodes: List[Dict], parent_path: str = "", page_offset: int = 1
) -> List[Section]:
    """将树形节点递归转换为 Section 列表。"""
    sections = []
    for i, node in enumerate(nodes):
        title = node["title"]
        path = f"{parent_path}/{title}" if parent_path else title

        # 从内容中尝试提取页码（docling 可在文本中嵌入页码标记）
        page = page_offset + i  # 粗略页码

        sec = Section(
            title=title,
            page=page,
            content=node.get("content", "").strip(),
        )

        # 递归处理子节点
        if node.get("children"):
            sec.subsections = _build_sections(
                node["children"], parent_path=path, page_offset=page
            )

        sections.append(sec)

    return sections


def _extract_tables(markdown: str) -> List[Table]:
    """从 Markdown 文本中提取所有表格。"""
    tables = []

    # 提取 Markdown 表格（连续的 | 行）
    lines = markdown.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('|') and line.endswith('|'):
            table_lines = [line]
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith('|'):
                table_lines.append(lines[j].strip())
                j += 1

            # 验证：至少要有表头行 + 分隔行
            if len(table_lines) >= 2 and re.match(r'^\|[\s\-:|]+\|$', table_lines[1]):
                tables.append(Table(
                    caption="",
                    page=0,
                    markdown='\n'.join(table_lines),
                ))
            i = j
        else:
            i += 1

    # 提取 HTML 表格
    for m in _HTML_TABLE_RE.finditer(markdown):
        html = m.group(0)
        # 尝试将 HTML 转为 Markdown 表格（简单实现）
        md_table = _html_table_to_md(html)
        if md_table:
            tables.append(Table(caption="", page=0, markdown=md_table))

    return tables


def _html_table_to_md(html: str) -> str:
    """将简单 HTML <table> 转为 Markdown 表格。"""
    try:
        # 提取所有行
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
        if not rows:
            return ""

        md_rows = []
        for ri, row_html in enumerate(rows):
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL | re.IGNORECASE)
            clean_cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if clean_cells:
                md_rows.append('| ' + ' | '.join(clean_cells) + ' |')
                if ri == 0:
                    md_rows.append('| ' + ' | '.join(['---'] * len(clean_cells)) + ' |')

        return '\n'.join(md_rows) if len(md_rows) >= 2 else ""
    except Exception:
        return ""


def _extract_metadata_from_md(markdown: str, source: str = "docling") -> PaperMetadata:
    """从 Markdown 内容中提取元数据（标题、摘要、作者）。"""
    title = ""
    abstract = ""

    # 第一个 h1 作为论文标题
    h1_match = re.search(r'^#\s+(.+)$', markdown, re.MULTILINE)
    if h1_match:
        title = h1_match.group(1).strip()

    # 尝试找 Abstract 章节
    abstract_match = re.search(
        r'(?:^#{1,3}\s+Abstract?\s*$)\n+(.+?)(?:^#{1,3}\s|\Z)',
        markdown, re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if abstract_match:
        abstract = abstract_match.group(1).strip()[:3000]
    elif not title:
        # 没有明显标题时，取第一段
        first_para = re.search(r'^#{1,6}\s+.+\n+(.+?)(?:\n\n|\Z)', markdown, re.DOTALL)
        if first_para:
            abstract = first_para.group(1).strip()[:500]

    return PaperMetadata(
        title=title,
        authors=[],
        abstract=abstract,
        source=source,
    )


# ── 主解析函数 ──


def parse_with_docling(
    pdf_path: str,
    export_markdown: bool = True,
    export_tables: bool = True,
) -> Optional[ParsedPaper]:
    """使用 Docling 解析 PDF 为结构化的 ParsedPaper。

    Docling 特点：
    - 精准的阅读顺序（解决双栏论文的文本乱序问题）
    - 表格 → HTML（保留行列语义，LLM 可理解标签结构）
    - 公式 → LaTeX（保留数学语义）
    - 列表、粗体、斜体 → Markdown 格式

    Args:
        pdf_path: PDF 文件路径
        export_markdown: 是否导出为 Markdown（默认 True）
        export_tables: 是否提取表格（默认 True）

    Returns:
        ParsedPaper，失败返回 None
    """
    _check_docling()

    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        logger.warning("文件不存在: %s", pdf_path)
        return None

    try:
        logger.info("Docling 解析中: %s", pdf_file.name)

        converter = DocumentConverter()
        result = converter.convert(str(pdf_file))

        if export_markdown:
            markdown = result.document.export_to_markdown()
        else:
            markdown = result.document.export_to_text()

        if not markdown or not markdown.strip():
            logger.warning("Docling 输出为空: %s", pdf_file.name)
            return None

        # 提取元数据
        metadata = _extract_metadata_from_md(markdown, source="docling")

        # 提取表格
        tables = _extract_tables(markdown) if export_tables else []

        # 构建节结构
        heading_tree = _split_by_headings(markdown)
        sections = _build_sections(heading_tree)

        logger.info(
            "Docling 解析完成: %s → %d 章节, %d 表格",
            pdf_file.name, len(sections), len(tables),
        )

        return ParsedPaper(
            metadata=metadata,
            sections=sections,
            tables=tables,
            figures=[],
        )

    except Exception as e:
        logger.error("Docling 解析失败 %s: %s", pdf_file.name, e, exc_info=True)
        return None


def parse_with_docling_raw(pdf_path: str) -> Optional[str]:
    """使用 Docling 解析 PDF 并返回原始 Markdown 文本。

    适合需要直接处理 Markdown 的下游任务（如直接喂给 LLM）。
    """
    _check_docling()

    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        return None

    try:
        converter = DocumentConverter()
        result = converter.convert(str(pdf_file))
        return result.document.export_to_markdown()
    except Exception as e:
        logger.error("Docling 原始解析失败 %s: %s", pdf_file.name, e)
        return None


# ── 批量处理 ──


def batch_docling(
    input_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> dict:
    """批量使用 Docling 处理 PDF 并保存为 JSON。

    Args:
        input_dir: PDF 目录，默认 config.RAW_PDF_DIR
        output_dir: JSON 输出目录，默认 config.PARSED_DIR

    Returns:
        {"success": [...], "failed": [...]}
    """
    in_dir = Path(input_dir) if input_dir else config.RAW_PDF_DIR
    out_dir = Path(output_dir) if output_dir else config.PARSED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = list(in_dir.rglob("*.pdf"))
    if not pdf_files:
        print(f"[Docling] 未找到 PDF 文件: {in_dir}")
        return {"success": [], "failed": []}

    success, failed = [], []
    for pdf_file in pdf_files:
        print(f"[Docling] 处理中: {pdf_file.name}")
        parsed = parse_with_docling(str(pdf_file))
        if parsed is None:
            failed.append(str(pdf_file))
            continue

        # 同时保存 JSON 和 Markdown
        json_path = out_dir / f"{pdf_file.stem}.json"
        md_path = out_dir / f"{pdf_file.stem}.md"

        json_path.write_text(
            json.dumps(parsed.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 保存原始 Markdown 供直接消费
        md_text = parse_with_docling_raw(str(pdf_file))
        if md_text:
            md_path.write_text(md_text, encoding="utf-8")

        print(f"   → {json_path.name} ({len(parsed.sections)} 章节, "
              f"{len(parsed.tables)} 表格)")
        success.append(str(pdf_file))

    print(f"\n[Docling] 完成: {len(success)} 成功, {len(failed)} 失败")
    return {"success": success, "failed": failed}


def parse_pdf_docling(pdf_path: str) -> Dict[str, Any]:
    """统一入口：兼容 parse_pdf_structure 的返回格式。

    供 orchestrator 等上游透明调用，无需关心底层是 pymupdf 还是 docling。
    """
    parsed = parse_with_docling(pdf_path)
    if parsed is None:
        return {"metadata": {}, "sections": [], "tables": []}
    return parsed.to_dict()


if __name__ == "__main__":
    batch_docling()
