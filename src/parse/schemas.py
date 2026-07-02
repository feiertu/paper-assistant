"""统一的解析输出结构。

grobid.py / pdf.py 都输出 ParsedPaper，下游 chunk/embed 只依赖这一个结构。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Section:
    """章节/子章节（递归结构）。"""
    title: str
    page: int
    content: str = ""
    subsections: List[Section] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "title": self.title,
            "page": self.page,
            "content": self.content,
        }
        if self.subsections:
            result["subsections"] = [s.to_dict() for s in self.subsections]
        return result


@dataclass
class Table:
    """表格。GROBID 可提取表格并转为 Markdown。"""
    caption: str = ""
    page: int = 0
    markdown: str = ""  # Markdown 表格
    section_title: str = ""  # 所属章节

    def to_dict(self) -> Dict[str, Any]:
        return {
            "caption": self.caption,
            "page": self.page,
            "markdown": self.markdown,
            "section_title": self.section_title,
        }


@dataclass
class Figure:
    """图片。GROBID 提取 caption；图片内容本身暂不处理（v2 可加多模态描述）。"""
    caption: str = ""
    page: int = 0
    section_title: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "caption": self.caption,
            "page": self.page,
            "section_title": self.section_title,
        }


@dataclass
class PaperMetadata:
    """论文元数据。"""
    title: str = ""
    authors: List[str] = field(default_factory=list)
    abstract: str = ""
    source: str = ""  # "arxiv" / "grobid" / "pymupdf"
    arxiv_id: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)  # 扩展字段

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "source": self.source,
            "arxiv_id": self.arxiv_id,
            **{k: v for k, v in self.extra.items() if v},
        }


@dataclass
class ParsedPaper:
    """论文解析统一输出。"""
    metadata: PaperMetadata = field(default_factory=PaperMetadata)
    sections: List[Section] = field(default_factory=list)
    tables: List[Table] = field(default_factory=list)
    figures: List[Figure] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """兼容旧格式的输出：metadata + sections，tables/figures 塞到顶层。"""
        result: Dict[str, Any] = {
            "metadata": self.metadata.to_dict(),
            "sections": [s.to_dict() for s in self.sections],
        }
        if self.tables:
            result["tables"] = [t.to_dict() for t in self.tables]
        if self.figures:
            result["figures"] = [f.to_dict() for f in self.figures]
        return result

    def to_legacy(self) -> Dict[str, Any]:
        """兼容 pdf.py 旧格式（仅 metadata + sections，content 为纯文本）。"""
        return self.to_dict()

    @classmethod
    def from_legacy(cls, legacy: Dict[str, Any]) -> "ParsedPaper":
        """从 pdf.py 旧格式字典转换。"""
        meta_raw = legacy.get("metadata") or {}
        metadata = PaperMetadata(
            title=meta_raw.get("title") or "",
            authors=(
                [a.strip() for a in meta_raw.get("author", "").split(",") if a.strip()]
                if meta_raw.get("author")
                else []
            ),
            abstract="",
            source="pymupdf",
        )

        def _build_sections(raw_sections) -> List[Section]:
            result = []
            for s in raw_sections or []:
                sec = Section(
                    title=s.get("title") or "",
                    page=s.get("page") or 1,
                    content=s.get("content") or "",
                )
                if s.get("subsections"):
                    sec.subsections = _build_sections(s["subsections"])
                result.append(sec)
            return result

        return cls(
            metadata=metadata,
            sections=_build_sections(legacy.get("sections", [])),
        )
