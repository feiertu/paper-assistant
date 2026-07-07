"""文本分块工具（v3：结构感知 + 上下文注入）。

核心改进：
1. Markdown 标题层级感知切片 — 沿 h1→h2→h3 边界切分，保证语义完整性
2. 面包屑路径注入 — 每个 chunk 注入 "论文 > 第3章 > 3.2 方法" 上下文
3. 表格/代码块保护 — 表格和代码块作为整体，不从中切断
4. 兼容旧版 pymupdf JSON 格式

基于 LangChain RecursiveCharacterTextSplitter，按段落边界优先切分。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

# ── 学术论文友好的分隔符优先级 ──
# 段落 > 换行 > 句号空格 > 分号 > 空格 > 硬切
_ACADEMIC_SEPARATORS = ["\n\n", "\n", ". ", "; ", " ", ""]

# ── 保护模式（代码块 / LaTeX / Markdown 表格） ──
_CODE_BLOCK_RE = re.compile(r'```[^`]*```', re.DOTALL)
_INLINE_CODE_RE = re.compile(r'`[^`]+`')
_LATEX_BLOCK_RE = re.compile(r'\$\$[^$]*\$\$', re.DOTALL)
_LATEX_INLINE_RE = re.compile(r'\$[^$]+\$')
# Markdown 表格块（连续的 | 行）
_MD_TABLE_BLOCK_RE = re.compile(
    r'(?:^\|.+\|$\n?)+', re.MULTILINE,
)
# HTML 表格块
_HTML_TABLE_RE = re.compile(r'<table[^>]*>.*?</table>', re.DOTALL | re.IGNORECASE)


def _protect_special_blocks(text: str) -> Tuple[str, Dict[str, str]]:
    """将特殊块替换为占位符，避免被切断。

    保护顺序（长块优先）：
    1. 代码块 (``` ... ```)
    2. LaTeX 公式块 ($$ ... $$)
    3. HTML 表格 (<table> ... </table>)
    4. Markdown 表格 (连续的 | 行)
    5. 行内代码 (`...`)
    6. 行内公式 ($...$)

    Returns:
        (protected_text, placeholder_map)
    """
    placeholders: Dict[str, str] = {}
    counter = [0]

    def _replace(match, prefix: str) -> str:
        counter[0] += 1
        ph = f"__{prefix}_{counter[0]}__"
        placeholders[ph] = match.group(0)
        return ph

    # 优先级：长块 → 短块
    text = _CODE_BLOCK_RE.sub(lambda m: _replace(m, 'CB'), text)
    text = _LATEX_BLOCK_RE.sub(lambda m: _replace(m, 'LB'), text)
    text = _HTML_TABLE_RE.sub(lambda m: _replace(m, 'HT'), text)
    text = _MD_TABLE_BLOCK_RE.sub(lambda m: _replace(m, 'MT'), text)
    text = _INLINE_CODE_RE.sub(lambda m: _replace(m, 'IC'), text)
    text = _LATEX_INLINE_RE.sub(lambda m: _replace(m, 'LI'), text)

    return text, placeholders


def _restore_special_blocks(chunks: List[str], placeholder_map: Dict[str, str]) -> List[str]:
    """将分块后的占位符还原为原始内容。"""
    if not placeholder_map:
        return chunks
    result = []
    for chunk in chunks:
        for ph, original in placeholder_map.items():
            chunk = chunk.replace(ph, original)
        result.append(chunk)
    return result


# ── 面包屑上下文注入 ──


def _build_breadcrumb(
    paper_title: str,
    section_title: str = "",
    subsection_path: str = "",
    page: int = 0,
) -> str:
    """构建面包屑上下文路径。

    示例：
        "论文: Attention Is All You Need > 3. Method > 3.2 Encoder Architecture"
    """
    parts = []
    if paper_title:
        parts.append(f"论文: {paper_title}")
    if section_title:
        parts.append(section_title)
    if subsection_path:
        parts.append(subsection_path)

    breadcrumb = " > ".join(parts) if parts else ""
    if page > 0 and breadcrumb:
        breadcrumb += f" (第{page}页)"
    return breadcrumb


def _inject_breadcrumb(
    chunk_text: str,
    paper_title: str,
    section_title: str = "",
    page: int = 0,
    heading_path: str = "",
) -> str:
    """在 chunk 文本开头注入上下文面包屑。

    格式：
        [上下文: 论文X > 方法 > 实验设置]
        <原始 chunk 内容>
    """
    breadcrumb = _build_breadcrumb(paper_title, section_title, heading_path, page)
    if not breadcrumb:
        return chunk_text
    return f"[上下文: {breadcrumb}]\n\n{chunk_text}"


# ── 分块 ──


def _get_splitter(
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> RecursiveCharacterTextSplitter:
    cs = chunk_size or config.CHUNK_SIZE
    co = chunk_overlap or config.CHUNK_OVERLAP
    return RecursiveCharacterTextSplitter(
        chunk_size=cs,
        chunk_overlap=co,
        separators=_ACADEMIC_SEPARATORS,
        keep_separator=True,
        strip_whitespace=True,
    )


def split_text(
    text: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> List[str]:
    """对纯文本分块，保护特殊块不被切断。"""
    if not text or not text.strip():
        return []
    splitter = _get_splitter(chunk_size, chunk_overlap)
    protected, ph_map = _protect_special_blocks(text.strip())
    raw_chunks = splitter.split_text(protected)
    return _restore_special_blocks(raw_chunks, ph_map)


# ── 新版：结构感知分块（支持 Markdown 和旧 JSON 格式） ──


def split_doc(
    doc: Dict,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    inject_context: bool = True,
) -> List[Dict]:
    """对解析后的文档分块，支持 Markdown 和旧 JSON 两种格式。

    上下文注入策略：
    - 每个 chunk 开头注入 "[上下文: 论文标题 > 章节 > 子章节]"
    - 帮助 LLM 理解片段在论文中的位置，防止"张冠李戴"

    Args:
        doc: ParsedPaper.to_dict() 输出，或 pdf.py 旧格式。
        chunk_size: 分块大小，None 则用配置。
        chunk_overlap: 重叠大小，None 则用配置。
        inject_context: 是否注入面包屑上下文（默认 True）。

    Returns:
        [{"text", "title", "page", "section_title", "source", "heading_path"}, ...]
    """
    if not doc:
        return []

    splitter = _get_splitter(chunk_size, chunk_overlap)
    chunks: List[Dict] = []

    meta = doc.get("metadata") or {}
    paper_title = meta.get("title") or meta.get("source") or ""
    source = paper_title or (meta.get("arxiv_id") or "")

    def _emit_rich(
        text: str,
        title: str,
        page,
        section_title: str,
        heading_path: str = "",
    ) -> None:
        """分块 + 注入上下文。"""
        if not text or not text.strip():
            return
        protected, ph_map = _protect_special_blocks(text.strip())
        for piece in splitter.split_text(protected):
            restored = piece
            for ph, original in ph_map.items():
                restored = restored.replace(ph, original)

            # 注入面包屑上下文
            if inject_context:
                enriched = _inject_breadcrumb(
                    restored,
                    paper_title=paper_title,
                    section_title=section_title or title,
                    page=page,
                    heading_path=heading_path,
                )
            else:
                enriched = restored

            chunks.append({
                "text": enriched,
                "title": title,
                "page": page,
                "section_title": section_title or title,
                "source": source,
                "heading_path": heading_path,
            })

    # ── 处理 tables 顶层字段（grobid / docling 格式） ──
    doc_tables = doc.get("tables") or []
    for tbl in doc_tables:
        md_table = tbl.get("markdown") or ""
        if md_table.strip():
            caption = tbl.get("caption") or ""
            page = tbl.get("page") or 0
            sec_title = tbl.get("section_title") or ""
            # 表格作为独立 chunk，注入所属章节上下文
            heading = f"{sec_title} > 表格" if sec_title else "表格"
            tbl_text = f"{caption}\n{md_table}" if caption else md_table
            _emit_rich(tbl_text, "表格", page, sec_title, heading)

    # ── 处理 sections（兼容新旧格式） ──
    for section in doc.get("sections", []) or []:
        _process_section(section, paper_title, "", splitter, _emit_rich)

    return chunks


def _process_section(
    section: Dict,
    paper_title: str,
    parent_path: str,
    splitter: RecursiveCharacterTextSplitter,
    emit_fn,
) -> None:
    """递归处理章节，构建 heading_path 并触发分块。"""
    stitle = section.get("title") or ""
    spage = section.get("page") or 0
    scontent = section.get("content") or ""

    # 构建当前路径
    path = f"{parent_path} > {stitle}" if parent_path else stitle

    # 正文分块
    if scontent.strip():
        emit_fn(scontent, stitle, spage, stitle, path)

    # 递归处理子章节
    for sub in section.get("subsections", []) or []:
        _process_section(sub, paper_title, path, splitter, emit_fn)

    # 处理章节内嵌的 tables（部分格式）
    if section.get("tables"):
        for tbl in section["tables"]:
            md_table = tbl.get("markdown") or ""
            if md_table.strip():
                caption = tbl.get("caption") or ""
                page = tbl.get("page") or spage
                tbl_text = f"{caption}\n{md_table}" if caption else md_table
                emit_fn(tbl_text, f"{stitle} 表格", page, stitle, f"{path} > 表格")


# ── 文档遍历 ──


def iter_doc_files(input_dir) -> Iterable[Tuple[Path, Dict]]:
    """遍历 parsed JSON 文件并 yield (path, doc)。容错：坏 JSON 直接跳过。"""
    import json

    p = Path(input_dir)
    if not p.exists():
        return
    for fp in sorted(p.rglob("*.json")):
        try:
            yield fp, json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue


def find_parsed_dir() -> Path:
    """自动定位 parsed JSON 所在目录。"""
    primary = Path(config.PARSED_DIR)
    if primary.exists() and any(primary.rglob("*.json")):
        return primary
    fallback = Path(__file__).resolve().parents[1] / "data" / "parsed"
    if fallback.exists() and any(fallback.rglob("*.json")):
        return fallback
    return primary


__all__ = [
    "split_text",
    "split_doc",
    "iter_doc_files",
    "find_parsed_dir",
    "_inject_breadcrumb",
    "_build_breadcrumb",
]
