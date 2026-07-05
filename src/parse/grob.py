"""GROBID PDF 解析器。

通过 REST API 调用 GROBID Docker 服务，利用 ML 模型精确提取：
- 标题、作者、摘要
- 章节标题和正文（不再依赖字体大小启发式）
- 表格 → Markdown 格式
- 图片 caption

GROBID 启动：
    docker run -d -p 8070:8070 lfoppiano/grobid:0.8.1

API 文档：https://grobid.readthedocs.io/en/latest/Grobid-service/
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from lxml import etree

from .schemas import Figure, PaperMetadata, ParsedPaper, Section, Table
from src.logging_config import get_logger
import config

logger = get_logger(__name__)

# GROBID 地址（通过环境变量 PAPER_ASSISTANT_GROBID_URL 覆盖，由 config 模块统一管理）
GROBID_BASE_URL = config._env("PAPER_ASSISTANT_GROBID_URL", "http://localhost:8070") or "http://localhost:8070"
FULLTEXT_ENDPOINT = f"{GROBID_BASE_URL}/api/processFulltextDocument"

# TEI 命名空间
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

_NS = {"tei": TEI_NS, "xml": XML_NS}

# 非正文章节名（跳过不打 chunk）
_SKIP_SECTIONS = {
    "references", "bibliography", "acknowledgements", "acknowledgments",
    "appendix", "appendices", "supplementary material",
}


def _xpath(el, expr: str, many: bool = False):
    """在 TEI 命名空间下执行 xpath。"""
    result = el.xpath(expr, namespaces=_NS)
    if many:
        return result
    return result[0] if result else None


def _text(el, expr: str, join: str = " ") -> str:
    """提取 xpath 匹配元素的文本内容。"""
    hits = el.xpath(expr, namespaces=_NS)
    texts = []
    for h in hits:
        t = "".join(h.itertext()).strip()
        if t:
            texts.append(t)
    return join.join(texts) if texts else ""


def _clean(text: str) -> str:
    """清理多余空白。"""
    return re.sub(r"\s+", " ", text).strip()


# ---------- GROBID API 调用 ----------


def parse_with_grobid(
    pdf_path: str,
    base_url: Optional[str] = None,
    timeout: int = 120,
    retries: int = 3,
) -> Optional[ParsedPaper]:
    """调用 GROBID 解析 PDF，返回 ParsedPaper。

    Args:
        pdf_path: PDF 文件路径
        base_url: GROBID 服务地址，默认 http://localhost:8070
        timeout: 请求超时（秒）
        retries: 失败重试次数

    Returns:
        ParsedPaper，失败返回 None
    """
    endpoint = f"{base_url or GROBID_BASE_URL}/api/processFulltextDocument"
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        logger.warning("文件不存在: %s", pdf_path)
        return None

    for attempt in range(1, retries + 1):
        try:
            with open(pdf_path, "rb") as f:
                resp = requests.post(
                    endpoint,
                    files={"input": (pdf_file.name, f, "application/pdf")},
                    data={
                        "consolidateHeader": "1",
                        "consolidateCitations": "0",
                        "includeRawCitations": "0",
                        "segmentSentences": "0",
                    },
                    timeout=timeout,
                )
            resp.raise_for_status()
            return _parse_tei(resp.content)
        except Exception as e:
            if attempt < retries:
                wait = 2 ** attempt
                logger.warning("第 %d/%d 次请求失败，%ds 后重试: %s", attempt, retries, wait, e)
                time.sleep(wait)
            else:
                logger.error("解析失败 (%d 次重试): %s", retries, e)
                return None

    return None


# ---------- TEI XML 解析 ----------


def _parse_tei(xml_bytes: bytes) -> ParsedPaper:
    """将 GROBID TEI XML 解析为 ParsedPaper。"""
    root = etree.fromstring(xml_bytes)
    header = _xpath(root, "//tei:teiHeader")

    # 元数据
    metadata = PaperMetadata(
        title=_clean(_text(root, "//tei:titleStmt/tei:title")),
        authors=_extract_authors(root),
        abstract=_clean(_text(root, "//tei:profileDesc/tei:abstract")),
        source="grobid",
    )

    # 正文
    body = _xpath(root, "//tei:text/tei:body")
    sections, tables, figures = [], [], []
    if body is not None:
        sections, tables, figures = _parse_body(body)

    return ParsedPaper(
        metadata=metadata,
        sections=sections,
        tables=tables,
        figures=figures,
    )


def _extract_authors(root) -> List[str]:
    """提取作者列表。"""
    authors = []
    for author_el in root.xpath("//tei:sourceDesc//tei:author", namespaces=_NS):
        pers = _xpath(author_el, "tei:persName")
        if pers is None:
            continue
        forename = _text(pers, "tei:forename", join=" ")
        surname = _text(pers, "tei:surname")
        name = f"{forename} {surname}".strip()
        if name:
            authors.append(name)
    return authors


def _parse_body(body) -> Tuple[List[Section], List[Table], List[Figure]]:
    """解析 <body>：遍历顶层 <div>，递归构建 Section / Table / Figure。"""
    sections, tables, figures = [], [], []

    for div in body.xpath("tei:div", namespaces=_NS):
        # 判断是否顶层 div（没有再嵌套 div 的 div）
        child_divs = div.xpath("tei:div", namespaces=_NS)

        if child_divs:
            # 有子 div：当前 div 是容器，递归子 div
            for child in child_divs:
                sec = _parse_section(child)
                if sec is not None:
                    sections.append(sec)
            # 同时提取当前层级的表格/图片
            tables.extend(_parse_tables(div))
            figures.extend(_parse_figures(div))
        else:
            # 叶子 div：直接解析为 section
            sec = _parse_section(div)
            if sec is not None:
                sections.append(sec)

    # 顶层表格/图片（不在任何 div 内的）
    tables.extend(_parse_tables(body))
    figures.extend(_parse_figures(body))

    return sections, tables, figures


def _parse_section(div) -> Optional[Section]:
    """解析单个 <div> 为 Section。"""
    head = _xpath(div, "tei:head")
    title = _clean("".join(head.itertext())) if head is not None else ""

    # 跳过非正文章节
    if title.strip().lower() in _SKIP_SECTIONS:
        return None

    # 正文段落
    paragraphs = []
    for p in div.xpath("tei:p", namespaces=_NS):
        text = _clean("".join(p.itertext()))
        if text:
            paragraphs.append(text)
    content = " ".join(paragraphs)

    # 页号（GROBID 在 pb 元素中标注）
    page = _extract_page(div)

    sec = Section(title=title, page=page, content=content)

    # 嵌套子章节
    child_divs = div.xpath("tei:div", namespaces=_NS)
    for child in child_divs:
        sub = _parse_section(child)
        if sub is not None:
            sec.subsections.append(sub)

    return sec


def _parse_tables(parent) -> List[Table]:
    """从父元素中提取 <figure type="table">。"""
    tables = []
    for fig in parent.xpath('tei:figure[@type="table"]', namespaces=_NS):
        caption = _clean(_text(fig, "tei:figDesc"))
        page = _extract_page(fig)
        markdown = _table_to_markdown(fig)
        tables.append(Table(caption=caption, page=page, markdown=markdown))
    return tables


def _parse_figures(parent) -> List[Figure]:
    """从父元素中提取图片 <figure>（不含 table 类型）。"""
    figures = []
    for fig in parent.xpath(
        'tei:figure[not(@type) or @type!="table"]', namespaces=_NS
    ):
        caption = _clean(_text(fig, "tei:figDesc"))
        page = _extract_page(fig)
        sect_title = _parent_section_title(fig)
        figures.append(
            Figure(caption=caption, page=page, section_title=sect_title)
        )
    return figures


def _table_to_markdown(figure_el) -> str:
    """尝试将 GROBID <table> 转为 Markdown 表格。"""
    table_el = _xpath(figure_el, "tei:table")
    if table_el is None:
        return ""

    rows = table_el.xpath("tei:row", namespaces=_NS)
    if not rows:
        return ""

    md_rows = []
    for i, row in enumerate(rows):
        cells = []
        for cell in row.xpath("tei:cell", namespaces=_NS):
            cells.append(_clean("".join(cell.itertext())))
        md_rows.append("| " + " | ".join(cells) + " |")
        if i == 0:
            # 表头分隔线
            md_rows.append("| " + " | ".join(["---"] * len(cells)) + " |")

    return "\n".join(md_rows)


def _extract_page(el) -> int:
    """从元素中提取页码（GROBID 用 <pb> 标注）。"""
    # 在当前元素及其之前的同级中找最近的 <pb>
    pb = _xpath(el, "preceding::tei:pb[1]")
    if pb is None:
        pb = _xpath(el, "ancestor-or-self::*//tei:pb[1]")
    if pb is not None:
        n = pb.get("n") or pb.get("{http://www.w3.org/XML/1998/namespace}id")
        try:
            return int(n) if n else 1
        except (ValueError, TypeError):
            return 1
    return 1


def _parent_section_title(el) -> str:
    """获取元素所属最近章节标题。"""
    parent_div = _xpath(el, "ancestor::tei:div[tei:head][1]")
    if parent_div is not None:
        head = _xpath(parent_div, "tei:head")
        if head is not None:
            return _clean("".join(head.itertext()))
    return ""


# ---------- 批量处理 ----------


def batch_grobid(
    input_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    base_url: Optional[str] = None,
) -> dict:
    """批量用 GROBID 处理 PDF 并保存为 JSON。

    Args:
        input_dir: PDF 目录，默认 config.RAW_PDF_DIR
        output_dir: JSON 输出目录，默认 config.PARSED_DIR
        base_url: GROBID 地址

    Returns:
        {"success": [...], "failed": [...]}
    """
    import json

    import config

    in_dir = Path(input_dir) if input_dir else config.RAW_PDF_DIR
    out_dir = Path(output_dir) if output_dir else config.PARSED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = list(in_dir.rglob("*.pdf"))
    if not pdf_files:
        print(f"[GROBID] 未找到 PDF 文件: {in_dir}")
        return {"success": [], "failed": []}

    success, failed = [], []
    for pdf_file in pdf_files:
        print(f"[GROBID] 处理中: {pdf_file.name}")
        parsed = parse_with_grobid(str(pdf_file), base_url=base_url)
        if parsed is None:
            failed.append(str(pdf_file))
            continue

        out_path = out_dir / f"{pdf_file.stem}.json"
        out_path.write_text(
            json.dumps(parsed.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"   → {out_path.name}  ({len(parsed.sections)} 章节, "
              f"{len(parsed.tables)} 表格, {len(parsed.figures)} 图片)")
        success.append(str(pdf_file))

    print(f"\n[GROBID] 完成: {len(success)} 成功, {len(failed)} 失败")
    return {"success": success, "failed": failed}


if __name__ == "__main__":
    batch_grobid()
