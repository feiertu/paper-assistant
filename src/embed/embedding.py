"""Embedding 客户端封装。

支持两种后端，可单独使用或同时启用（RRF 双路检索）：
1. OpenAI — text-embedding-3-large（dim=1024）
2. Voyage AI — voyage-3（dim=1024）

通过 config.EMBEDDING_PROVIDER 用逗号分隔，例如 "openai,voyage"。
两路维度统一为 1024，均做 L2 归一化以支持 cosine 检索。

特性：
- Embedding 缓存：相同文本 + provider 组合 24h 内不重复调用 API
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

import config
from src.cache import get_embed_cache, make_embed_key
from src.logging_config import get_logger

logger = get_logger(__name__)


# ---------- 后端实现 ----------


class _OpenAIBackend:
    def __init__(self, model_name: str) -> None:
        from openai import OpenAI

        config.require_openai_key()
        # 优先使用 embedding 专用配置，否则回退到 LLM 配置
        api_key = config.EMBEDDING_API_KEY or config.OPENAI_API_KEY
        base_url = config.EMBEDDING_BASE_URL or config.OPENAI_BASE_URL
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self._model = model_name

        # 检测非标准 API：MiniMax 等使用 texts/vectors 而非 input/data 格式
        self._base_url = base_url
        self._is_minimax = "minimax" in (base_url or "").lower()

    @property
    def name(self) -> str:
        return "openai"

    def embed(self, texts: List[str]) -> np.ndarray:
        if self._is_minimax:
            return self._embed_minimax(texts)
        return self._embed_openai(texts)

    def _embed_openai(self, texts: List[str]) -> np.ndarray:
        resp = self._client.embeddings.create(
            model=self._model,
            input=texts,
            dimensions=config.EMBEDDING_DIM,
        )
        arr = np.asarray([d.embedding for d in resp.data], dtype=np.float32)
        return self._normalize(arr)

    def _embed_minimax(self, texts: List[str]) -> np.ndarray:
        """MiniMax API: 使用 texts 字段（非 input），返回 vectors（非 data[].embedding）。"""
        import requests

        key = config.EMBEDDING_API_KEY or config.OPENAI_API_KEY
        url = f"{self._base_url.rstrip('/')}/embeddings"
        resp = requests.post(
            url,
            json={"model": self._model, "texts": texts},
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"MiniMax embedding API 返回 {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        vectors = data.get("vectors")
        if not vectors:
            err = data.get("base_resp", {})
            raise RuntimeError(
                f"MiniMax embedding 返回空向量: code={err.get('status_code')} "
                f"msg={err.get('status_msg')}"
            )
        arr = np.asarray(vectors, dtype=np.float32)
        return self._normalize(arr)

    @staticmethod
    def _normalize(arr: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms


class _VoyageBackend:
    def __init__(self, model_name: str) -> None:
        import voyageai

        if not config.VOYAGE_API_KEY:
            raise RuntimeError(
                "未配置 VOYAGE_API_KEY。请在 .env 中设置，或导出环境变量。"
            )
        self._client = voyageai.Client(api_key=config.VOYAGE_API_KEY)
        self._model = model_name

    @property
    def name(self) -> str:
        return "voyage"

    def embed(self, texts: List[str]) -> np.ndarray:
        result = self._client.embed(
            texts=texts,
            model=self._model,
            input_type="document",
        )
        arr = np.asarray(result.embeddings, dtype=np.float32)
        return self._normalize(arr)

    @staticmethod
    def _normalize(arr: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms


class _LocalBackend:
    """本地 sentence-transformers embedding 后端。

    不依赖外部 API，适合离线环境或 API 不提供 embedding 的情况。
    默认模型：all-MiniLM-L6-v2（英文，384维，80MB）或 BAAI/bge-small-zh-v1.5（中英，512维，100MB）。
    """

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model_name = model_name
        logger.info("加载本地 embedding 模型: %s ...", model_name)
        self._model = SentenceTransformer(model_name)
        logger.info("本地 embedding 模型加载完成: %s dim=%d", model_name, self.dim)

    @property
    def name(self) -> str:
        return "local"

    @property
    def dim(self) -> int:
        return self._model.get_sentence_embedding_dimension()

    def embed(self, texts: List[str]) -> np.ndarray:
        arr = np.asarray(self._model.encode(texts, normalize_embeddings=True), dtype=np.float32)
        # ChromaDB 需要 float64 或普通 Python list，这里统一转 Python float
        return arr.astype(np.float64)


# ---------- 统一入口 ----------


class Embedder:
    """统一的 embed 接口。单后端或双后端（RRF）均可。

    用法：
        # 单后端
        emb = Embedder(provider="openai")
        vec = emb.embed_query("hello")

        # 双后端（RRF 重排序需要外部 store 配合）
        emb = Embedder(provider="openai,voyage")
        vecs = emb.embed_query_all("hello")  # {"openai": [...], "voyage": [...]}
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        raw = (provider or config.EMBEDDING_PROVIDER).lower()
        self._providers: List[str] = [p.strip() for p in raw.split(",") if p.strip()]
        self._model_name = model_name or config.EMBEDDING_MODEL
        self._backends: Dict[str, Any] = {}
        self._cache = get_embed_cache() if config.CACHE_ENABLED else None

        for p in self._providers:
            self._backends[p] = self._build_backend(p)

        logger.info("Embedder 初始化 providers=%s model=%s dim=%d cache=%s",
                     self._providers, self._model_name, self.dim,
                     "enabled" if self._cache else "disabled")

    def _build_backend(self, provider: str):
        if provider == "openai":
            return _OpenAIBackend(self._model_name)
        if provider == "voyage":
            return _VoyageBackend(self._model_name)
        if provider == "local":
            return _LocalBackend(self._model_name)
        raise ValueError(
            f"未知 EMBEDDING_PROVIDER={provider!r}，可选: openai / voyage / local"
        )

    # ---------- 单后端接口 ----------

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """用第一个 provider 做 embedding（带缓存）。

        对每个 text 先查缓存，只对未命中文本调用 API，然后合并结果。
        """
        if not texts:
            return np.zeros((0, config.EMBEDDING_DIM), dtype=np.float32)
        provider = self._providers[0]
        return self._embed_with_cache(list(texts), provider)

    def _embed_with_cache(self, texts: List[str], provider: str) -> np.ndarray:
        """带缓存的 embedding：查缓存 + 调 API + 写缓存。"""
        dim = config.EMBEDDING_DIM
        if not self._cache:
            return self._backends[provider].embed(texts)

        # 1) 查缓存
        cached_vecs: Dict[int, np.ndarray] = {}
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []
        for i, text in enumerate(texts):
            key = make_embed_key(text, provider)
            val = self._cache.get(key)
            if val is not None:
                cached_vecs[i] = np.asarray(val, dtype=np.float32)
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # 2) 全部命中
        if not uncached_texts:
            logger.debug("Embedding 缓存全命中: %d/%d", len(texts), len(texts))
            result = np.zeros((len(texts), dim), dtype=np.float32)
            for i, vec in cached_vecs.items():
                result[i] = vec
            return result

        # 3) 调 API
        if uncached_texts:
            logger.info("Embedding: %d cached, %d via API (%s)",
                         len(cached_vecs), len(uncached_texts), provider)
        backend = self._backends[provider]
        new_vecs = backend.embed(uncached_texts)

        # 4) 写缓存
        for text, vec in zip(uncached_texts, new_vecs):
            key = make_embed_key(text, provider)
            self._cache.set(key, vec.tolist())

        # 5) 合并
        result = np.zeros((len(texts), dim), dtype=np.float32)
        for i, vec in cached_vecs.items():
            result[i] = vec
        for j, idx in enumerate(uncached_indices):
            result[idx] = new_vecs[j]
        return result

    def embed_query(self, text: str) -> List[float]:
        """单查询 embedding（用第一个 provider）。"""
        return self.embed([text])[0].tolist()

    # ---------- 双后端接口 ----------

    def embed_all(self, texts: Sequence[str]) -> Dict[str, np.ndarray]:
        """多后端同时 embed，返回 {provider_name: np.ndarray}。"""
        if not texts:
            return {p: np.zeros((0, config.EMBEDDING_DIM), dtype=np.float32) for p in self._providers}
        return {p: self._embed_with_cache(list(texts), p) for p in self._providers}

    def embed_query_all(self, text: str) -> Dict[str, List[float]]:
        """多后端单查询 embedding。"""
        result = self.embed_all([text])
        return {p: arr[0].tolist() for p, arr in result.items()}

    # ---------- 属性 ----------

    @property
    def dim(self) -> int:
        return config.EMBEDDING_DIM

    @property
    def providers(self) -> List[str]:
        return list(self._providers)

    @property
    def is_dual(self) -> bool:
        return len(self._providers) >= 2


# ---------- RRF 重排序 ----------


def rrf_rerank(
    query: str,
    top_k: Optional[int] = None,
    rrf_k: Optional[int] = None,
    rrf_top_n: Optional[int] = None,
    owner_id: str = "",
) -> List[Dict[str, Any]]:
    """RRF (Reciprocal Rank Fusion) 双路检索 + 重排序。

    流程：
      1. 用 OpenAI + Voyage 两路分别 query Chroma，各取 top-N
      2. 对两路结果做 RRF 融合
      3. 返回得分最高的 top-K

    要求 store 已入库且两路 embedding 均已写入。
    """
    from src.store import VectorStore

    embedder = get_embedder()
    where = {"owner_id": owner_id} if owner_id else None
    if not embedder.is_dual:
        # 单路退化为普通检索
        store = VectorStore()
        q_emb = embedder.embed_query(query)
        return store.query(q_emb, top_k=top_k or config.RAG_TOP_K, where=where)["hits"]

    k = top_k or config.RAG_TOP_K
    rrf_n = rrf_top_n or config.RRF_TOP_N
    rk = rrf_k or config.RRF_K

    # 1) 两路分别检索
    store = VectorStore()
    rank_lists: Dict[str, List[Dict]] = {}
    for provider in embedder.providers:
        backend = embedder._backends[provider]
        q_emb = backend.embed([query])[0].tolist()
        result = store.query(q_emb, top_k=rrf_n, where=where)
        rank_lists[provider] = result["hits"]

    # 2) RRF 融合
    rrf_scores: Dict[str, float] = {}
    hit_map: Dict[str, Dict] = {}
    for provider, hits in rank_lists.items():
        for rank, hit in enumerate(hits, 1):
            hid = hit["id"]
            rrf_scores[hid] = rrf_scores.get(hid, 0.0) + 1.0 / (rk + rank)
            if hid not in hit_map:
                hit_map[hid] = hit

    # 3) 按 RRF 得分降序取 top-K
    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)[:k]
    return [
        {**hit_map[hid], "rrf_score": round(rrf_scores[hid], 6)}
        for hid in sorted_ids
    ]


# ---------- 混合检索（v3：稠密 + BM25 稀疏 + Cross-Encoder 精排）----------

# Module-level BM25 cache
_bm25_cache: Dict[str, Any] = {"index": None, "count": 0, "timestamp": 0.0}
_BM25_CACHE_TTL = 60.0  # seconds


def hybrid_retrieve(
    query: str,
    top_k: Optional[int] = None,
    owner_id: str = "",
    use_bm25: Optional[bool] = None,
    use_reranker: Optional[bool] = None,
    rrf_top_n: Optional[int] = None,
    bm25_weight: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """混合检索管道：稠密向量 + BM25 稀疏 → RRF 融合 → Cross-Encoder 精排。

    这是 Paper Assistant v3 的核心检索函数，统一替代 rrf_rerank。

    流程：
      1. 稠密检索（OpenAI / Voyage embedding）→ 取 top-N
      2. BM25 稀疏检索 → 取 top-N
      3. RRF 融合两路结果
      4. Cross-Encoder 重排序（可选，精排）
      5. 返回 top-K

    Args:
        query: 查询文本
        top_k: 最终返回数量（默认 config.RAG_TOP_K）
        owner_id: 多用户隔离
        use_bm25: 是否启用 BM25 稀疏检索（默认 True）
        use_reranker: 是否启用 Cross-Encoder 精排（默认 True）
        rrf_top_n: 每路检索取 top-N 进行融合（默认 config.RRF_TOP_N）
        bm25_weight: BM25 在 RRF 中的权重（0-1，默认 0.3）

    Returns:
        [{"id", "document", "metadata", "score", "rerank_score"?}, ...]
    """
    from src.embed.bm25 import BM25Index
    from src.store import VectorStore

    # 参数默认值从 config 读取
    if use_bm25 is None:
        use_bm25 = config.BM25_ENABLED
    if use_reranker is None:
        use_reranker = config.RERANKER_ENABLED
    if bm25_weight is None:
        bm25_weight = config.BM25_WEIGHT

    embedder = get_embedder()
    store = VectorStore()
    where = {"owner_id": owner_id} if owner_id else None
    k = top_k or config.RAG_TOP_K
    n = rrf_top_n or config.RRF_TOP_N

    if store.count() == 0:
        return []

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Step 1 & 2: 稠密 & 稀疏双路检索
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    rank_lists: Dict[str, List[Dict]] = {}

    # 稠密检索（第一个 provider）
    dense_backend = embedder._backends[embedder.providers[0]]
    q_emb = dense_backend.embed([query])[0].tolist()
    dense_result = store.query(q_emb, top_k=n, where=where)
    rank_lists["dense"] = dense_result["hits"]
    logger.debug("稠密检索: %d hits", len(rank_lists["dense"]))

    # BM25 稀疏检索
    if use_bm25:
        try:
            # Use cached BM25 if count unchanged
            now = time.time()
            if (_bm25_cache["index"] is not None and
                _bm25_cache["count"] == store.count() and
                now - _bm25_cache["timestamp"] < _BM25_CACHE_TTL):
                bm25_hits = _bm25_cache["index"].search(query, top_k=n)
            else:
                all_items = store.peek(limit=min(store.count(), 2000))
                bm25 = BM25Index()
                docs = []
                ids = []
                for item in all_items:
                    doc_text = item.get("document", "")
                    if doc_text and doc_text.strip():
                        docs.append(doc_text)
                        ids.append(item.get("id", ""))

                if docs:
                    bm25.index(docs, ids)
                    bm25_hits = bm25.search(query, top_k=n)
                    _bm25_cache["index"] = bm25
                    _bm25_cache["count"] = store.count()
                    _bm25_cache["timestamp"] = now
                else:
                    bm25_hits = []

            if bm25_hits:
                # 将 BM25 分数归一化到 [0,1]
                max_score = max((h["score"] for h in bm25_hits), default=1.0)
                for h in bm25_hits:
                    if max_score > 0:
                        h["score"] = h["score"] / max_score * bm25_weight
                    # 回填 document 文本
                    h.setdefault("document", "")
                    h.setdefault("metadata", h.get("metadata", {}))
                rank_lists["bm25"] = bm25_hits
                logger.debug("BM25 检索: %d hits", len(bm25_hits))
        except Exception:
            logger.warning("BM25 检索失败，回退到纯稠密检索", exc_info=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Step 3: RRF 融合
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    rrf_k_param = config.RRF_K
    rrf_scores: Dict[str, float] = {}
    hit_map: Dict[str, Dict] = {}

    for source, hits in rank_lists.items():
        weight = bm25_weight if source == "bm25" else (1.0 - bm25_weight)
        for rank, hit in enumerate(hits, 1):
            hid = hit.get("id", f"unknown_{rank}")
            rrf_scores[hid] = rrf_scores.get(hid, 0.0) + weight / (rrf_k_param + rank)
            if hid not in hit_map:
                hit_map[hid] = hit

    # 按 RRF 得分降序 → 取 Top-N 作为精排候选
    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)[:n]
    fused_hits = [
        {**hit_map[hid], "rrf_score": round(rrf_scores[hid], 6)}
        for hid in sorted_ids
    ]
    logger.debug("RRF 融合后: %d 候选", len(fused_hits))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Step 4: Cross-Encoder 精排（可选）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    if use_reranker and len(fused_hits) > k:
        try:
            from src.embed.reranker import get_reranker
            reranker = get_reranker()
            if reranker is not None:
                fused_hits = reranker.rerank(query, fused_hits, top_k=k)
                logger.debug("Cross-Encoder 精排后: %d", len(fused_hits))
        except Exception:
            logger.warning("Cross-Encoder 重排失败，使用 RRF 结果", exc_info=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Step 5: 返回 top-K
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # 统一 score 字段
    for h in fused_hits[:k]:
        if "score" not in h:
            h["score"] = h.get("rerank_score") or h.get("rrf_score") or h.get("distance")
        # 保留 distance 字段（兼容旧代码）
        if "distance" not in h and "score" in h:
            h["distance"] = 1.0 / (1.0 + float(h["score"])) if h["score"] else 0.0

    return fused_hits[:k]


# ---------- 单例 ----------

_embedder: Optional[Embedder] = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


__all__ = [
    "Embedder",
    "get_embedder",
    "rrf_rerank",
    "hybrid_retrieve",
]
