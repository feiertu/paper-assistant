"""引用关系提取。

从解析后的论文 JSON 中提取参考文献，匹配 arXiv ID。
支持 GROBID 和 pymupdf 两种解析器的输出格式。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import config
from src.logging_config import get_logger

logger = get_logger(__name__)

# arXiv ID 正则：匹配 "arxiv:XXXX.XXXXX" 或 "arXiv:XXXX.XXXXXvN" 等模式
_ARXIV_ID_RE = re.compile(
    r'(?:arxiv\s*[:#]?\s*|arXiv\s*[:#]?\s*)?'
    r'(\d{4}\.\d{4,5}(?:v\d+)?)',
    re.IGNORECASE,
)

# arXiv URL 模式
_ARXIV_URL_RE = re.compile(
    r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)',
    re.IGNORECASE,
)


def extract_arxiv_ids(text: str) -> List[str]:
    """从文本中提取 arXiv ID 列表。

    支持格式：
    - arXiv:2301.12345
    - arxiv.org/abs/2301.12345
    - 2301.12345v1 (独立出现在文本中)
    - [2301.12345]
    """
    ids: Set[str] = set()

    # URL 模式
    for m in _ARXIV_URL_RE.finditer(text):
        ids.add(m.group(1))

    # arXiv: 前缀模式
    for m in re.finditer(r'arxiv\s*[:#]\s*(\d{4}\.\d{4,5}(?:v\d+)?)', text, re.IGNORECASE):
        ids.add(m.group(1))

    # 独立 ID 模式（需要上下文确认不是页码/年份）
    for m in _ARXIV_ID_RE.finditer(text):
        raw = m.group(1)
        # 过滤误匹配：太短或纯数字
        if len(raw) >= 9 and "." in raw:
            ids.add(raw)

    return sorted(ids)


def extract_references_from_parsed(arxiv_id: str) -> List[Tuple[str, str, str]]:
    """从 parsed JSON 提取引用关系。

    Args:
        arxiv_id: 当前论文的 arXiv ID

    Returns:
        [(cited_arxiv_id, cited_title, context), ...]
    """
    json_path = config.PARSED_DIR / f"{arxiv_id}.json"
    if not json_path.exists():
        logger.debug("parsed JSON 不存在: %s", arxiv_id)
        return []

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("无法读取 parsed JSON %s: %s", arxiv_id, e)
        return []

    # 收集所有引用文本
    ref_texts = _collect_reference_texts(data)
    if not ref_texts:
        return []

    # 合并所有引用段
    full_ref_text = "\n".join(ref_texts)

    # 按文献条目分割（常见的编号模式）
    entries = _split_reference_entries(full_ref_text)

    results: List[Tuple[str, str, str]] = []
    for entry in entries:
        ids = extract_arxiv_ids(entry)
        for cited_id in ids:
            # 排除自身引用
            cited_base = cited_id.split("v")[0]
            self_base = arxiv_id.split("v")[0]
            if cited_base == self_base:
                continue
            # 提取引用上下文中的标题（第一行或编号后的文本）
            title = _extract_title_from_entry(entry)
            results.append((cited_id, title, entry[:300]))

    logger.info("引用提取: %s → %d 条引用关系", arxiv_id, len(results))
    return results


def _collect_reference_texts(data: Dict) -> List[str]:
    """从 parsed JSON 收集 References 相关文本。"""
    texts = []

    # 方法 1: 找 References 章节
    for sec in data.get("sections", []) or []:
        title = (sec.get("title") or "").strip().lower()
        if title in ("references", "bibliography", "reference"):
            content = sec.get("content") or ""
            if content.strip():
                texts.append(content)
        # 也检查子章节
        for sub in sec.get("subsections", []) or []:
            stitle = (sub.get("title") or "").strip().lower()
            if stitle in ("references", "bibliography", "reference"):
                content = sub.get("content") or ""
                if content.strip():
                    texts.append(content)

    return texts


def _split_reference_entries(ref_text: str) -> List[str]:
    """按文献编号分割引用条目。

    支持类似 "[1] ...", "1. ...", "[1]" 开头的分段。
    """
    # 尝试按 [N] 或 N. 分割
    parts = re.split(r'\n(?=\s*\[\d+\]|\s*\d+\.\s)', ref_text)
    if len(parts) <= 1:
        # 如果没有编号，按双换行分割
        parts = ref_text.split("\n\n")
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 20]


def _extract_title_from_entry(entry: str) -> str:
    """从引用条目中提取论文标题（启发式）。"""
    # 去掉编号前缀
    cleaned = re.sub(r'^\[?\d+\]?\.?\s*', '', entry.strip())
    # 取第一个句子（通常是标题）
    sentences = re.split(r'[.。!！?？]\s+', cleaned)
    first = sentences[0].strip() if sentences else cleaned[:200]
    # 去掉作者和年份部分（通常是 "Author, A., ... (2023)." 格式）
    title_match = re.search(r'(?:\)\.|,?\s*\d{4}[a-z]?\.?)\s*(.+)', first)
    if title_match:
        return title_match.group(1).strip()[:200]
    return first[:200]


def batch_extract_citations(arxiv_ids: Optional[List[str]] = None) -> Dict:
    """批量提取所有已解析论文的引用关系。

    Args:
        arxiv_ids: 指定论文 ID 列表，None 则处理 parsed 目录下全部 JSON。

    Returns:
        {"processed": N, "citations": M}
    """
    from src.db.dao import CitationDAO, get_dao

    parsed_dir = config.PARSED_DIR
    if not parsed_dir.exists():
        return {"processed": 0, "citations": 0, "error": "parsed 目录不存在"}

    if arxiv_ids is None:
        arxiv_ids = [p.stem for p in parsed_dir.glob("*.json")]

    citation_dao: CitationDAO = get_dao("citation")
    total_citations = 0

    for aid in arxiv_ids:
        refs = extract_references_from_parsed(aid)
        if refs:
            inserted = citation_dao.batch_insert([
                (aid, cited_id, title, ctx) for cited_id, title, ctx in refs
            ])
            total_citations += inserted

    logger.info("批量引用提取完成: %d 篇论文, %d 条引用", len(arxiv_ids), total_citations)
    return {"processed": len(arxiv_ids), "citations": total_citations}
