"""Embedding 子包：文本分块 + 向量化 + BM25 稀疏检索 + RRF 重排 + Cross-Encoder 精排。

v3 增强：
- BM25 稀疏检索（关键词精确匹配）
- Cross-Encoder 重排序（交互式语义精排）
- 混合检索 pipeline：稠密+稀疏 → RRF融合 → Cross-Encoder精排 → Top-K
"""

from .chunk import split_text, split_doc
from .embedding import Embedder, get_embedder, rrf_rerank, hybrid_retrieve
from .bm25 import BM25Index, build_bm25_from_store
from .reranker import Reranker, get_reranker

__all__ = [
    "split_text",
    "split_doc",
    "Embedder",
    "get_embedder",
    "rrf_rerank",
    "hybrid_retrieve",
    "BM25Index",
    "build_bm25_from_store",
    "Reranker",
    "get_reranker",
]
