"""Cross-Encoder 重排序模块。

在混合检索（稠密向量 + BM25 稀疏）的初排结果之上，使用 Cross-Encoder
做精细化语义重排序。Cross-Encoder 同时编码 query 和 document，捕捉交互特征，
排序精度远超双塔模型。

默认模型：BAAI/bge-reranker-v2-m3（多语言，中英均支持）。
可用环境变量 RERANKER_MODEL 覆盖。

架构：
    粗排（Top-20 via RRF）→ Cross-Encoder 精排 → Top-K
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.logging_config import get_logger

logger = get_logger(__name__)

# 默认重排模型
_DEFAULT_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

# 标记是否可用
_HAS_SENTENCE_TRANSFORMERS = False

try:
    from sentence_transformers import CrossEncoder
    _HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    pass


class Reranker:
    """Cross-Encoder 重排序器。

    用法：
        reranker = Reranker()
        scores = reranker.score(query, documents)
        ranked = reranker.rerank(query, hits, top_k=5)

    特性：
    - 懒加载模型（首次使用时才加载）
    - 支持批量评分
    - 与 retrieve() 的 hits 格式兼容
    """

    def __init__(self, model_name: Optional[str] = None):
        if not _HAS_SENTENCE_TRANSFORMERS:
            raise ImportError(
                "sentence-transformers 未安装。请运行: pip install sentence-transformers"
            )
        self._model_name = model_name or _DEFAULT_MODEL
        self._model: Optional[CrossEncoder] = None

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            logger.info("加载 Cross-Encoder 重排模型: %s ...", self._model_name)
            self._model = CrossEncoder(
                self._model_name,
                max_length=512,
                device="cpu",  # 默认 CPU；可设 CUDA
            )
            logger.info("重排模型加载完成: %s", self._model_name)
        return self._model

    # ── 评分 ──

    def score(self, query: str, documents: List[str]) -> List[float]:
        """对 (query, document) 对计算相关性分数。

        Args:
            query: 查询文本
            documents: 文档文本列表

        Returns:
            分数列表（越高越相关），与 documents 同序
        """
        if not documents:
            return []
        pairs = [(query, doc) for doc in documents]
        scores = self.model.predict(pairs)
        if isinstance(scores, np.ndarray):
            scores = scores.tolist()
        # 确保是 list[float]
        return [float(s) for s in scores]

    def score_pairs(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """对自定义 (query, document) 对评分。"""
        if not pairs:
            return []
        scores = self.model.predict(pairs)
        if isinstance(scores, np.ndarray):
            scores = scores.tolist()
        return [float(s) for s in scores]

    # ── 重排 ──

    def rerank(
        self,
        query: str,
        hits: List[Dict[str, Any]],
        top_k: int = 5,
        score_field: str = "rerank_score",
    ) -> List[Dict[str, Any]]:
        """对检索命中结果做 Cross-Encoder 重排。

        Args:
            query: 查询文本
            hits: 检索命中结果，每项需含 "document" 字段
            top_k: 返回 top-K
            score_field: 新增的分数字段名（默认 "rerank_score"）

        Returns:
            重排后的 hits（按 rerank_score 降序）
        """
        if not hits:
            return []

        docs = [h.get("document", "") for h in hits]
        scores = self.score(query, docs)

        # 附加分数并排序
        for h, s in zip(hits, scores):
            h[score_field] = round(s, 6)
            # 保留原始分数
            if "original_score" not in h:
                h["original_score"] = h.get("score") or h.get("distance")

        # 按重排分数降序
        ranked = sorted(hits, key=lambda x: x.get(score_field, -999), reverse=True)
        return ranked[:top_k]


# ── 模块级单例 ──

_reranker: Optional[Reranker] = None


def get_reranker(model_name: Optional[str] = None) -> Optional[Reranker]:
    """获取重排序器单例。如果 sentence-transformers 未安装，返回 None。"""
    global _reranker
    if not _HAS_SENTENCE_TRANSFORMERS:
        logger.warning("sentence-transformers 未安装，禁用 Cross-Encoder 重排")
        return None
    if _reranker is None:
        _reranker = Reranker(model_name=model_name)
    return _reranker


__all__ = ["Reranker", "get_reranker"]
