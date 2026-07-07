"""论文解析子包：PDF → 结构化 JSON。

三个后端：
- pdf.py          : pymupdf 快速解析（默认，字号启发式）
- docling_parser.py: IBM Docling 解析（推荐，Markdown + 表格 + 公式 + 阅读顺序）
- grob.py         : GROBID ML 解析（需 Docker，精确结构化）
- schemas.py      : 统一的数据结构 ParsedPaper

通过 config.PDF_PARSER 或环境变量 PDF_PARSER 选择后端。
"""

from .schemas import ParsedPaper, PaperMetadata, Section, Table, Figure

__all__ = ["ParsedPaper", "PaperMetadata", "Section", "Table", "Figure"]
