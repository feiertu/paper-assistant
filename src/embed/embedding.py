"""Embedding 客户端封装。

支持两种后端，可单独使用或同时启用（RRF 双路检索）：
1. OpenAI — text-embedding-3-large（dim=1024）
2. Voyage AI — voyage-3（dim=1024）

通过 config.EMBEDDING_PROVIDER 用逗号分隔，例如 "openai,voyage"。
两路维度统一为 1024，均做 L2 归一化以支持 cosine 检索。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

import config


# ---------- 后端实现 ----------


class _OpenAIBackend:
    def __init__(self, model_name: str) -> None:
        from openai import OpenAI

        config.require_openai_key()
        self._client = OpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
        )
        self._model = model_name

    @property
    def name(self) -> str:
        return "openai"

    def embed(self, texts: List[str]) -> np.ndarray:
        resp = self._client.embeddings.create(
            model=self._model,
            input=texts,
            dimensions=config.EMBEDDING_DIM,
        )
        arr = np.asarray([d.embedding for d in resp.data], dtype=np.float32)
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

        for p in self._providers:
            self._backends[p] = self._build_backend(p)

    def _build_backend(self, provider: str):
        if provider == "openai":
            return _OpenAIBackend(self._model_name)
        if provider == "voyage":
            return _VoyageBackend(self._model_name)
        raise ValueError(
            f"未知 EMBEDDING_PROVIDER={provider!r}，可选: openai / voyage"
        )

    # ---------- 单后端接口 ----------

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """用第一个 provider 做 embedding。单后端场景使用。"""
        if not texts:
            return np.zeros((0, config.EMBEDDING_DIM), dtype=np.float32)
        primary = self._backends[self._providers[0]]
        return primary.embed(list(texts))

    def embed_query(self, text: str) -> List[float]:
        """单查询 embedding（用第一个 provider）。"""
        return self.embed([text])[0].tolist()

    # ---------- 双后端接口 ----------

    def embed_all(self, texts: Sequence[str]) -> Dict[str, np.ndarray]:
        """多后端同时 embed，返回 {provider_name: np.ndarray}。"""
        if not texts:
            return {p: np.zeros((0, config.EMBEDDING_DIM), dtype=np.float32) for p in self._providers}
        return {p: backend.embed(list(texts)) for p, backend in self._backends.items()}

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
    if not embedder.is_dual:
        # 单路退化为普通检索
        store = VectorStore()
        q_emb = embedder.embed_query(query)
        return store.query(q_emb, top_k=top_k or config.RAG_TOP_K)["hits"]

    k = top_k or config.RAG_TOP_K
    rrf_n = rrf_top_n or config.RRF_TOP_N
    rk = rrf_k or config.RRF_K

    # 1) 两路分别检索
    store = VectorStore()
    rank_lists: Dict[str, List[Dict]] = {}
    for provider in embedder.providers:
        backend = embedder._backends[provider]
        q_emb = backend.embed([query])[0].tolist()
        result = store.query(q_emb, top_k=rrf_n)
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
]
