"""文本分块工具。

基于 LangChain RecursiveCharacterTextSplitter，按段落边界优先切分，
对学术论文正文比纯字符切割更友好。

v2: 增加代码块 / LaTeX 公式检测，保护特殊内容不被切断。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

# 学术论文友好的分隔符优先级：段落 > 换行 > 句号空格 > 空格 > 硬切
_ACADEMIC_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

# 代码块和 LaTeX 公式的保护模式
_CODE_BLOCK_RE = re.compile(r'```[^`]*```', re.DOTALL)
_INLINE_CODE_RE = re.compile(r'`[^`]+`')
_LATEX_BLOCK_RE = re.compile(r'\$\$[^$]*\$\$', re.DOTALL)
_LATEX_INLINE_RE = re.compile(r'\$[^$]+\$')


def _protect_special_blocks(text: str) -> tuple:
    """将代码块和 LaTeX 公式替换为占位符，避免被切断。

    Returns:
        (protected_text, placeholder_map) — placeholder_map 是 {placeholder: original} 字典
    """
    placeholders: Dict[str, str] = {}
    counter = [0]

    def _replace(match, prefix):
        counter[0] += 1
        ph = f"__{prefix}_{counter[0]}__"
        placeholders[ph] = match.group(0)
        return ph

    # 按长度优先级：先保护长块（多行代码/公式），再保护短块
    text = _CODE_BLOCK_RE.sub(lambda m: _replace(m, 'CB'), text)
    text = _LATEX_BLOCK_RE.sub(lambda m: _replace(m, 'LB'), text)
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
        keep_separator=True,
        strip_whitespace=True,
    )


def split_text(
    text: str,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> List[str]:
    """对纯文本分块，自动保护代码块和公式不被切断。"""
    if not text or not text.strip():
        return []
    splitter = _get_splitter(chunk_size, chunk_overlap)
    protected, ph_map = _protect_special_blocks(text.strip())
    raw_chunks = splitter.split_text(protected)
    return _restore_special_blocks(raw_chunks, ph_map)


def split_doc(doc: Dict, chunk_size: Optional[int] = None, chunk_overlap: Optional[int] = None) -> List[Dict]:
    """对 `parse/pdf.py` 输出的结构化 doc 分块，保护代码块和公式。

    期望 doc 结构：{"metadata": {...}, "sections": [{"title", "page", "content", "subsections"?}]}
    返回的每个 chunk dict: {"text", "title", "page", "section_title", "source"}
    """
    if not doc:
        return []
    splitter = _get_splitter(chunk_size, chunk_overlap)
    chunks: List[Dict] = []

    meta = doc.get("metadata") or {}

    def _emit(text: str, title: str, page, section_title: str) -> None:
        protected, ph_map = _protect_special_blocks(text.strip())
        for piece in splitter.split_text(protected):
            restored = piece
            for ph, original in ph_map.items():
                restored = restored.replace(ph, original)
            chunks.append(
                {
                    "text": restored,
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
