"""Embedding 子包：文本分块 + 向量化 + RRF 重排序。"""

from .chunk import split_text, split_doc
from .embedding import Embedder, get_embedder, rrf_rerank

__all__ = ["split_text", "split_doc", "Embedder", "get_embedder", "rrf_rerank"]