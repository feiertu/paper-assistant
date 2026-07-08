"""Chroma 向量库封装。

对外只暴露 `VectorStore` 一个类，内部持有 chromadb.PersistentClient。
所有 RAG 模块都通过它读写，禁止直接 import chromadb。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import chromadb
from chromadb.api.models.Collection import Collection

import config


class VectorStore:
    """单 collection 的薄封装。

    用法：
        store = VectorStore()                 # 默认 collection
        store.add(ids, docs, embs, metas)     # 写入
        hits = store.query(query_emb, top_k=5)# 检索
        n = store.count()                     # 条数
        store.reset()                         # 清空 collection（慎用）
    """

    def __init__(
        self,
        collection_name: Optional[str] = None,
        persist_dir: Optional[Path] = None,
    ) -> None:
        self._persist_dir = Path(persist_dir or config.CHROMA_DIR)
        self._persist_dir.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(self._persist_dir))
        self._collection_name = collection_name or config.RAG_COLLECTION_NAME
        self._collection: Collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={
                "hnsw:space": "cosine",
                "hnsw:M": config.HNSW_M,
                "hnsw:construction_ef": config.HNSW_EF_CONSTRUCTION,
                "hnsw:search_ef": config.HNSW_EF_SEARCH,
            },
        )

    # ---------- 基础属性 ----------

    @property
    def collection_name(self) -> str:
        return self._collection_name

    @property
    def persist_dir(self) -> Path:
        return self._persist_dir

    def count(self) -> int:
        return self._collection.count()

    def reset(self) -> None:
        """删除并重建该 collection（数据会丢）。"""
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={
                "hnsw:space": "cosine",
                "hnsw:M": config.HNSW_M,
                "hnsw:construction_ef": config.HNSW_EF_CONSTRUCTION,
                "hnsw:search_ef": config.HNSW_EF_SEARCH,
            },
        )

    # ---------- 写入 ----------

    def add(
        self,
        ids: Sequence[str],
        documents: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> None:
        if not ids:
            return
        if not (len(ids) == len(documents) == len(embeddings)):
            raise ValueError(
                f"长度不一致 ids={len(ids)} docs={len(documents)} embs={len(embeddings)}"
            )
        kwargs = dict(
            ids=list(ids),
            documents=list(documents),
            embeddings=[e.tolist() if hasattr(e, 'tolist') else list(e) for e in embeddings],
        )
        if metadatas is not None:
            if len(metadatas) != len(ids):
                raise ValueError("metadatas 长度需与 ids 一致")
            kwargs["metadatas"] = [self._sanitize_meta(m) for m in metadatas]
        self._collection.add(**kwargs)

    # ---------- 检索 ----------

    def query(
        self,
        query_embedding: Sequence[float],
        top_k: Optional[int] = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        k = top_k or config.RAG_TOP_K
        kwargs: Dict[str, Any] = dict(
            query_embeddings=[list(query_embedding)],
            n_results=k,
        )
        if where:
            kwargs["where"] = where
        result = self._collection.query(**kwargs)
        return self._normalize_query_result(result)

    # ---------- 辅助 ----------

    @staticmethod
    def _sanitize_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
        """Chroma 只接受 str/int/float/bool/None，丢掉 None，其余转 str。"""
        out: Dict[str, Any] = {}
        for k, v in meta.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                out[k] = v
            else:
                out[k] = str(v)
        return out

    @staticmethod
    def _normalize_query_result(result: Dict[str, Any]) -> Dict[str, Any]:
        """把 chromadb 的二维 list 拍平成 `[{id, document, metadata, distance}]`。"""
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        hits: List[Dict[str, Any]] = []
        for i, _id in enumerate(ids):
            hits.append(
                {
                    "id": _id,
                    "document": docs[i] if i < len(docs) else "",
                    "metadata": metas[i] if i < len(metas) else {},
                    "distance": dists[i] if i < len(dists) else None,
                }
            )
        return {"hits": hits}

    def peek(self, limit: int = 5) -> List[Dict[str, Any]]:
        data = self._collection.peek(limit=limit)
        out: List[Dict[str, Any]] = []
        for i, _id in enumerate(data.get("ids", [])):
            out.append(
                {
                    "id": _id,
                    "document": (data.get("documents") or [""])[i],
                    "metadata": (data.get("metadatas") or [{}])[i],
                }
            )
        return out

    def get_by_arxiv_id(self, arxiv_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        """按 arxiv_id 过滤查询分块，使用 ChromaDB 元数据过滤。"""
        data = self._collection.get(
            where={"arxiv_id": arxiv_id},
            limit=limit,
            include=["documents", "metadatas"],
        )
        out: List[Dict[str, Any]] = []
        for i, _id in enumerate(data.get("ids", [])):
            out.append(
                {
                    "id": _id,
                    "document": (data.get("documents") or [""])[i],
                    "metadata": (data.get("metadatas") or [{}])[i],
                }
            )
        return out


# 模块级单例（懒加载），上层可选择直接 `from src.store import store`
_store: Optional[VectorStore] = None


def get_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


__all__ = ["VectorStore", "get_store"]