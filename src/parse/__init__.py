"""论文解析子包：PDF → 结构化 JSON。

两个后端：
- pdf.py   : pymupdf 快速解析（预览/元数据）
- grob.py  : GROBID ML 解析（RAG 入库，精确结构化）
- schemas.py: 统一的数据结构 ParsedPaper
"""

from .schemas import ParsedPaper, PaperMetadata, Section, Table, Figure

__all__ = ["ParsedPaper", "PaperMetadata", "Section", "Table", "Figure"]
