"""BM25 稀疏检索模块。

实现 Okapi BM25 算法，用于关键词级别的精确匹配检索。
与稠密向量检索互补：稠密捕获语义相似，BM25 捕获关键词精确命中。

使用示例：
    bm25 = BM25Index()
    bm25.index(documents, ids)
    results = bm25.search("transformer attention mechanism", top_k=10)
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple


class BM25Index:
    """Okapi BM25 全文检索索引。

    特点：
    - 零外部依赖，纯 Python 实现
    - 支持动态增删文档
    - 分词：英文按空白+标点，中文按字符 bigram
    - 标准 BM25 参数 k1=1.5, b=0.75
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25,
    ):
        """
        Args:
            k1: 词频饱和度参数（默认 1.5）
            b:  文档长度归一化参数（默认 0.75）
            epsilon: 负值惩罚（默认 0.25，防止 IDF 为负）
        """
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon

        # 语料统计
        self._corpus: List[str] = []          # 原始文档文本
        self._ids: List[str] = []             # 文档 ID
        self._doc_tokens: List[List[str]] = []  # 分词后的文档
        self._doc_len: List[int] = []         # 每篇文档长度
        self._avgdl: float = 0.0              # 平均文档长度

        # IDF 缓存
        self._df: Dict[str, int] = defaultdict(int)  # 词 → 包含该词的文档数
        self._idf: Dict[str, float] = {}             # 词 → IDF 值
        self._N: int = 0                              # 文档总数

        # 分词器：英文单词或中文连续字符
        self._tokenize_re = re.compile(
            r'[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*|[一-鿿]+|[^\s]',
        )

    # ── 索引构建 ──

    def index(
        self,
        documents: List[str],
        ids: Optional[List[str]] = None,
        reset: bool = False,
    ) -> None:
        """构建 BM25 索引。

        Args:
            documents: 文档文本列表
            ids: 文档 ID 列表（可选，默认 "doc_0", "doc_1" ...）
            reset: 是否清空旧索引
        """
        if reset:
            self.reset()

        if ids is None:
            ids = [f"bm25_{len(self._corpus) + i}" for i in range(len(documents))]

        for doc, doc_id in zip(documents, ids):
            tokens = self._tokenize(doc)
            self._corpus.append(doc)
            self._ids.append(doc_id)
            self._doc_tokens.append(tokens)
            self._doc_len.append(len(tokens))
            self._N += 1

            # 更新文档频率（去重）
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self._df[token] += 1

        # 更新平均文档长度
        self._avgdl = sum(self._doc_len) / max(self._N, 1)
        # 预计算所有词的 IDF
        self._precompute_idf()

    def add_document(self, text: str, doc_id: Optional[str] = None) -> str:
        """动态添加单篇文档。"""
        if doc_id is None:
            doc_id = f"bm25_{len(self._corpus)}"
        tokens = self._tokenize(text)
        self._corpus.append(text)
        self._ids.append(doc_id)
        self._doc_tokens.append(tokens)
        self._doc_len.append(len(tokens))
        self._N += 1
        self._avgdl = sum(self._doc_len) / self._N

        for token in set(tokens):
            self._df[token] += 1
            # 增量更新该词的 IDF
            self._idf[token] = self._calc_idf(self._df[token])

        return doc_id

    # ── 检索 ──

    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """BM25 检索。

        Args:
            query: 查询文本
            top_k: 返回文档数
            min_score: 最低分数过滤

        Returns:
            [{"id", "document", "score", "metadata": {}}, ...]
        """
        if self._N == 0:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores: List[Tuple[int, float]] = []
        for idx in range(self._N):
            score = self._score_doc(query_tokens, idx)
            if score > min_score:
                scores.append((idx, score))

        # 按分数降序排序
        scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in scores[:top_k]:
            results.append({
                "id": self._ids[idx],
                "document": self._corpus[idx],
                "score": round(score, 6),
                "metadata": {
                    "bm25_score": round(score, 6),
                    "doc_len": self._doc_len[idx],
                },
            })
        return results

    def get_scores(self, query: str) -> List[float]:
        """获取所有文档的 BM25 分数（用于 RRF 融合）。"""
        if self._N == 0:
            return []
        query_tokens = self._tokenize(query)
        return [self._score_doc(query_tokens, i) for i in range(self._N)]

    # ── 内部方法 ──

    def _tokenize(self, text: str) -> List[str]:
        """分词：英文按单词边界 + 标点，中文按单字。"""
        tokens = self._tokenize_re.findall(text.lower())
        # 过滤纯标点和过短的 token
        return [t for t in tokens if len(t) > 1 or t.isalnum()]

    def _calc_idf(self, df: int) -> float:
        """计算 IDF 值。

        IDF = log((N - df + 0.5) / (df + 0.5) + 1)
        加 1 确保非负，epsilon 进一步防止精确负值。
        """
        idf = math.log((self._N - df + 0.5) / (df + 0.5) + 1.0)
        return max(idf, self.epsilon)

    def _precompute_idf(self) -> None:
        """预计算所有词的 IDF。"""
        self._idf.clear()
        for token, df in self._df.items():
            self._idf[token] = self._calc_idf(df)

    def _score_doc(self, query_tokens: List[str], doc_idx: int) -> float:
        """计算单个文档对查询的 BM25 分数。"""
        doc_tokens = self._doc_tokens[doc_idx]
        doc_len = self._doc_len[doc_idx]
        if doc_len == 0:
            return 0.0

        # 词频统计（预计算）
        tf_map: Dict[str, int] = {}
        for t in doc_tokens:
            tf_map[t] = tf_map.get(t, 0) + 1

        score = 0.0
        for token in query_tokens:
            idf = self._idf.get(token, 0.0)
            if idf == 0.0:
                continue
            tf = tf_map.get(token, 0)
            if tf == 0:
                continue
            # BM25 公式
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self._avgdl)
            score += idf * numerator / denominator

        return score

    # ── 管理 ──

    def reset(self) -> None:
        """清空索引。"""
        self._corpus.clear()
        self._ids.clear()
        self._doc_tokens.clear()
        self._doc_len.clear()
        self._df.clear()
        self._idf.clear()
        self._N = 0
        self._avgdl = 0.0

    def __len__(self) -> int:
        return self._N

    def stats(self) -> Dict[str, Any]:
        """返回索引统计信息。"""
        return {
            "doc_count": self._N,
            "avg_doc_len": round(self._avgdl, 1),
            "vocab_size": len(self._df),
            "total_tokens": sum(self._doc_len),
        }


# ── 简易工厂：从 VectorStore 的 chunks 构建 BM25 索引 ──


def build_bm25_from_store(store_peek_result: List[Dict]) -> BM25Index:
    """从 VectorStore.peek() 的结果构建 BM25 索引。

    用于在启动时或定时构建稀疏检索索引。
    """
    bm25 = BM25Index()
    docs = []
    ids = []
    for item in store_peek_result:
        doc_id = item.get("id", "")
        doc_text = item.get("document", "")
        if doc_text.strip():
            docs.append(doc_text)
            ids.append(doc_id)

    if docs:
        bm25.index(docs, ids)
    return bm25


__all__ = ["BM25Index", "build_bm25_from_store"]
