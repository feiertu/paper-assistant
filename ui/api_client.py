"""Paper Assistant API Client.

前端与后端之间的 HTTP 通信层。所有 UI 操作必须通过此模块调用 API，
不再直接 import 后端模块（src.db, src.rag, src.store 等）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Generator, List, Optional

import requests

import config


class APIClient:
    """HTTP API 客户端，封装所有后端通信。

    Usage:
        client = APIClient(owner_id="session_xxx")
        papers = client.list_papers(limit=20, offset=0)
    """

    def __init__(self, owner_id: str = ""):
        self._base = f"http://127.0.0.1:{config.API_PORT}"
        self._owner_id = owner_id

    def _headers(self) -> dict:
        h = {"X-Owner-Id": self._owner_id}
        if config.API_AUTH_ENABLED and config.API_AUTH_KEY:
            h["X-API-Key"] = config.API_AUTH_KEY
        return h

    def _get(self, path: str, params: dict = None, timeout: int = 30) -> requests.Response:
        return requests.get(
            f"{self._base}{path}", params=params,
            headers=self._headers(), timeout=timeout,
        )

    def _post(self, path: str, data: dict = None, timeout: int = 120) -> requests.Response:
        return requests.post(
            f"{self._base}{path}", json=data or {},
            headers=self._headers(), timeout=timeout,
        )

    def _delete(self, path: str, timeout: int = 30) -> requests.Response:
        return requests.delete(
            f"{self._base}{path}", headers=self._headers(), timeout=timeout,
        )

    # ── 健康检查 ──

    def health(self) -> dict:
        return self._get("/health").json()

    # ── 论文元数据 ──

    def list_papers(self, limit: int = 50, offset: int = 0) -> dict:
        """获取论文列表（分页）。"""
        return self._get("/papers", {"limit": limit, "offset": offset}).json()

    def get_paper(self, arxiv_id: str) -> dict:
        return self._get(f"/papers/{arxiv_id}").json()

    def search_papers(
        self,
        keyword: str = "",
        author: str = "",
        year_from: str = "",
        year_to: str = "",
        status: str = "",
        sort_by: str = "created_at",
        limit: int = 1000,
    ) -> dict:
        """全文搜索 + 多条件过滤。"""
        params = {"limit": limit, "sort_by": sort_by}
        if keyword:
            params["keyword"] = keyword
        if author:
            params["author"] = author
        if year_from:
            params["year_from"] = year_from
        if year_to:
            params["year_to"] = year_to
        if status:
            params["status"] = status
        return self._get("/papers/search", params).json()

    def get_paper_chunks(self, arxiv_id: str, limit: int = 500) -> dict:
        """获取论文在向量库中的分块内容。"""
        return self._get(f"/papers/{arxiv_id}/chunks", {"limit": limit}).json()

    def get_paper_pdf(self, arxiv_id: str) -> requests.Response:
        return self._get(f"/papers/{arxiv_id}/pdf", timeout=60)

    # ── 论文推荐 ──

    def recommend_similar(self, arxiv_id: str, top_k: int = 5) -> dict:
        return self._post("/papers/recommend", {"arxiv_id": arxiv_id, "top_k": top_k}).json()

    # ── 全局分析 ──

    def analyze_all(self, query: str = "", lang: str = "zh") -> dict:
        return self._post("/papers/analyze", {"query": query, "lang": lang}).json()

    # ── 检索 ──

    def retrieve(self, query: str, top_k: int = 5) -> dict:
        return self._post("/retrieve", {"query": query, "top_k": top_k}).json()

    # ── RAG 问答 ──

    def rag_query(self, query: str, top_k: int = 5, lang: str = "zh") -> dict:
        return self._post("/rag/query", {"query": query, "top_k": top_k, "lang": lang}).json()

    def rag_query_stream(self, query: str, top_k: int = 5, lang: str = "zh",
                         temperature: float = None) -> Generator[str, None, None]:
        """流式 RAG 问答 — SSE 事件流。"""
        body: dict = {"query": query, "top_k": top_k, "lang": lang}
        if temperature is not None:
            body["temperature"] = temperature
        resp = requests.post(
            f"{self._base}/rag/query/stream",
            json=body,
            headers=self._headers(),
            stream=True,
            timeout=120,
        )
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                token = line[5:].strip()
                if token == "[DONE]":
                    return
                yield token

    # ── 论文摘要 ──

    def summarize(self, arxiv_id: str, lang: str = "zh") -> dict:
        return self._post("/summarize", {"arxiv_id": arxiv_id, "lang": lang}).json()

    # ── 综述 ──

    def survey(self, query: str, top_k: int = 10, lang: str = "zh") -> dict:
        return self._post("/survey", {"query": query, "top_k": top_k, "lang": lang}).json()

    # ── 数据入库 ──

    def ingest(self, reset: bool = False, parsed_dir: str = "") -> dict:
        return self._post("/ingest", {
            "reset": reset,
            "parsed_dir": parsed_dir,
        }, timeout=300).json()

    # ── arXiv 管道 ──

    def arxiv_pipeline(self, query: str, max_results: int = 5) -> dict:
        return self._post("/arxiv/pipeline", {
            "query": query,
            "max_results": max_results,
            "auto_ingest": True,
        }, timeout=600).json()

    def arxiv_process_pending(self) -> dict:
        return self._post("/arxiv/process-pending", timeout=600).json()

    def arxiv_fetch(self, query: str, max_results: int = 5) -> dict:
        return self._post("/arxiv/fetch", {
            "query": query,
            "max_results": max_results,
            "auto_ingest": False,
        }).json()

    # ── Agent 查询 ──

    def agent_query_stream(
        self, query: str, lang: str = "zh",
        max_iterations: int = 10, temperature: float = 0.1,
    ) -> Generator[Dict[str, Any], None, None]:
        """流式 Agent 查询 — SSE 事件流。"""
        resp = requests.post(
            f"{self._base}/agent/query/stream",
            json={
                "query": query, "lang": lang,
                "max_iterations": max_iterations,
                "temperature": temperature,
            },
            headers=self._headers(),
            stream=True,
            timeout=600,
        )
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    return
                try:
                    yield json.loads(data_str)
                except json.JSONDecodeError:
                    pass

    # ── 向量库管理 ──

    def store_stats(self) -> dict:
        return self._get("/store/stats").json()

    def store_papers(self) -> list:
        return self._get("/store/papers").json()

    def store_reset(self) -> dict:
        return self._delete("/store/reset").json()

    def store_backup(self) -> dict:
        return self._post("/store/backup").json()

    def store_restore(self, backup_name: str) -> dict:
        return self._post("/store/restore", {"backup_name": backup_name}).json()

    # ── 缓存 ──

    def cache_stats(self) -> dict:
        return self._get("/cache/stats").json()

    def cache_clear(self, kind: str = "all") -> dict:
        return self._delete(f"/cache/clear?kind={kind}").json()

    # ── 引用关系 ──

    def citations_graph(self, arxiv_id: str) -> dict:
        return self._get(f"/papers/{arxiv_id}/citations").json()

    def citations_extract(self, arxiv_ids: list = None) -> dict:
        return self._post("/citations/extract", arxiv_ids).json()

    def citations_stats(self) -> dict:
        return self._get("/citations/stats").json()

    # ── 查询历史 ──

    def queries_list(self, limit: int = 20) -> dict:
        return self._get("/queries", {"limit": limit}).json()

    def queries_clear(self) -> dict:
        return self._delete("/queries").json()

    # ── 收藏夹 ──

    def collections_list(self, limit: int = 50, offset: int = 0) -> dict:
        return self._get("/collections", {"limit": limit, "offset": offset}).json()

    def collections_create(self, name: str, description: str = "") -> dict:
        return self._post("/collections", {"name": name, "description": description}).json()

    def collections_delete(self, collection_id: int) -> dict:
        return self._delete(f"/collections/{collection_id}").json()

    def collections_add_paper(self, collection_id: int, paper_id: int) -> dict:
        return self._post(f"/collections/{collection_id}/papers", {"paper_id": paper_id}).json()

    def collections_list_papers(self, collection_id: int, limit: int = 50, offset: int = 0) -> dict:
        return self._get(f"/collections/{collection_id}/papers", {"limit": limit, "offset": offset}).json()

    # ── 导出 ──

    def export_papers(self, fmt: str = "json", limit: int = 200) -> requests.Response:
        return self._get("/export/papers", {"fmt": fmt, "limit": limit}, timeout=60)

    def export_queries(self, fmt: str = "json", limit: int = 500) -> requests.Response:
        return self._get("/export/queries", {"fmt": fmt, "limit": limit}, timeout=60)


# ── 模块级便捷工厂 ──

def get_client(owner_id: str = "") -> APIClient:
    """获取 API 客户端实例（轻量工厂，不需要缓存 — 请求都是无状态的）。"""
    return APIClient(owner_id=owner_id)
