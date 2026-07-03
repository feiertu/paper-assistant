"""文本分块工具。

基于 LangChain RecursiveCharacterTextSplitter，按段落边界优先切分，
对学术论文正文比纯字符切割更友好。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

# 学术论文友好的分隔符优先级：段落 > 换行 > 句号空格 > 空格 > 硬切
_ACADEMIC_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def _get_splitter(
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> RecursiveCharacterTextSplitter:
    cs = chunk_size or config.CHUNK_SIZE
    co = chunk_overlap if chunk_overlap is not None else config.CHUNK_OVERLAP
    return RecursiveCharacterTextSplitter(
        chunk_size=cs,
        chunk_overlap=co,
        separators=_ACADEMIC_SEPARATORS,
        keep_separator=True,  # 保留分隔符，不丢段落信息
        strip_whitespace=True,
    )


def split_text(
    text: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> List[str]:
    """对纯文本分块。

    空字符串返回 []；自动用 config 中的默认值。
    """
    if not text or not text.strip():
        return []
    splitter = _get_splitter(chunk_size, chunk_overlap)
    return splitter.split_text(text.strip())


def split_doc(doc: Dict, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None) -> List[Dict]:
    """对 `parse/pdf.py` 输出的结构化 doc 分块。

    期望 doc 结构：{"metadata": {...}, "sections": [{"title", "page", "content", "subsections"?}]}
    返回的每个 chunk dict: {"text", "title", "page", "section_title", "source"}
    """
    if not doc:
        return []
    splitter = _get_splitter(chunk_size, chunk_overlap)
    chunks: List[Dict] = []

    meta = doc.get("metadata") or {}

    def _emit(text: str, title: str, page, section_title: str) -> None:
        for piece in splitter.split_text(text.strip()):
            chunks.append(
                {
                    "text": piece,
                    "title": title,
                    "page": page,
                    "section_title": section_title,
                    "source": meta.get("title") or meta.get("source"),
                }
            )

    for section in doc.get("sections", []) or []:
        stitle = section.get("title") or ""
        spage = section.get("page")
        scontent = section.get("content") or ""
        if scontent.strip():
            _emit(scontent, stitle, spage, stitle)

        for sub in section.get("subsections", []) or []:
            sstitle = sub.get("title") or ""
            sspage = sub.get("page") or spage
            sscontent = sub.get("content") or ""
            if sscontent.strip():
                _emit(sscontent, sstitle, sspage, sstitle)

    return chunks


def iter_doc_files(input_dir) -> Iterable[Dict]:
    """遍历 parsed JSON 文件并 yield (path, doc)。容错：坏 JSON 直接跳过。"""
    import json
    from pathlib import Path

    p = Path(input_dir)
    if not p.exists():
        return
    for fp in p.rglob("*.json"):
        try:
            yield fp, json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue


def find_parsed_dir() -> Path:
    """自动定位 parsed JSON 所在目录。

    优先 config.PARSED_DIR；找不到再回落到 src/data/parsed（早期版本遗留）。
    """
    primary = Path(config.PARSED_DIR)
    if primary.exists() and any(primary.rglob("*.json")):
        return primary
    fallback = Path(__file__).resolve().parents[1] / "data" / "parsed"
    if fallback.exists() and any(fallback.rglob("*.json")):
        return fallback
    return primary  # 即便为空也返回主路径，便于上层报错
