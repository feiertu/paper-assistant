"""RAG 编排器。

将所有底层模块（embed/store/llm）串联为高层业务函数。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Sequence

import config
from src.db import Paper, PaperDAO, QueryDAO, QueryRecord, get_dao
from src.embed import get_embedder, split_doc, rrf_rerank
from src.embed.chunk import iter_doc_files, find_parsed_dir, split_text
from src.store import VectorStore, get_store


def _get_store() -> VectorStore:
    return get_store()


def _get_embedder():
    return get_embedder()


# ──────────────────────────────────────────────
#  数据入库
# ──────────────────────────────────────────────

def ingest_parsed_dir(
    parsed_dir: Optional[str] = None, reset: bool = False
) -> Dict[str, Any]:
    """将 parsed JSON 目录中的全部论文导入向量库。

    Args:
        parsed_dir: 解析后 JSON 目录，None 则自动探测。
        reset: 是否先清空 collection。

    Returns:
        {"status": "ok", "papers": N, "chunks": M} 或 {"error": "..."}
    """
    try:
        store = _get_store()
        if reset:
            store.reset()

        src_dir = Path(parsed_dir) if parsed_dir else find_parsed_dir()
        if not src_dir.exists():
            return {"error": f"目录不存在: {src_dir}"}

        docs = list(iter_doc_files(src_dir))
        if not docs:
            return {"error": f"在 {src_dir} 中未找到任何 JSON 文件"}

        embedder = _get_embedder()
        all_ids: List[str] = []
        all_texts: List[str] = []
        all_metas: List[Dict] = []
        paper_count = len(docs)

        for fp, doc in docs:
            chunks = split_doc(doc)
            for chunk in chunks:
                idx = len(all_ids)
                arxiv_id = fp.stem
                all_ids.append(f"{arxiv_id}_{idx}")
                all_texts.append(chunk["text"])
                all_metas.append(
                    {
                        "title": chunk.get("title") or "",
                        "section_title": chunk.get("section_title") or "",
                        "page": int(chunk.get("page") or 0),
                        "source": chunk.get("source") or arxiv_id,
                        "arxiv_id": arxiv_id,
                    }
                )

        if not all_texts:
            return {"error": "分块结果为空"}

        # 分批入库（embedding API 有批量限制）
        bs = config.EMBEDDING_BATCH_SIZE
        total_chunks = len(all_texts)
        for start in range(0, total_chunks, bs):
            end = min(start + bs, total_chunks)
            batch_texts = all_texts[start:end]
            embs = embedder.embed(batch_texts)
            store.add(
                ids=all_ids[start:end],
                documents=batch_texts,
                embeddings=embs,
                metadatas=all_metas[start:end],
            )

        # ── 记录到传统数据库（§19 ER模型） ──
        paper_dao: PaperDAO = get_dao("paper")
        # 统计每篇论文的 chunk 数
        chunk_counts: Dict[str, int] = {}
        for m in all_metas:
            aid = m.get("arxiv_id") or ""
            chunk_counts[aid] = chunk_counts.get(aid, 0) + 1

        for fp, doc in docs:
            arxiv_id = fp.stem
            meta = doc.get("metadata") or {}
            paper_dao.insert(
                Paper(
                    arxiv_id=arxiv_id,
                    title=meta.get("title") or "",
                    authors=meta.get("author") or "",
                    abstract="",
                    source=meta.get("source") or "pymupdf",
                    ingest_status="ingested",
                    chunk_count=chunk_counts.get(arxiv_id, 0),
                )
            )

        return {
            "status": "ok",
            "papers": paper_count,
            "chunks": total_chunks,
        }

    except Exception as e:
        return {"error": str(e)}


def ingest_text(
    text: str, metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """导入一段原始文本（含元数据）到向量库。

    Args:
        text: 文本内容。
        metadata: 可选元数据（title, section_title, page, source, arxiv_id）。

    Returns:
        {"status": "ok", "chunks": N}
    """
    try:
        store = _get_store()
        embedder = _get_embedder()
        pieces = split_text(text)
        if not pieces:
            return {"error": "文本分割后为空"}

        meta = metadata or {}
        ids: List[str] = []
        metas: List[Dict] = []
        for i in range(len(pieces)):
            ids.append(f"text_{store.count() + i}")
            metas.append(
                {
                    "title": meta.get("title") or "",
                    "section_title": meta.get("section_title") or "",
                    "page": int(meta.get("page") or 0),
                    "source": meta.get("source") or "manual",
                    "arxiv_id": meta.get("arxiv_id") or "",
                }
            )

        embs = embedder.embed(pieces)
        store.add(ids=ids, documents=pieces, embeddings=embs, metadatas=metas)
        return {"status": "ok", "chunks": len(pieces)}

    except Exception as e:
        return {"error": str(e)}


# ──────────────────────────────────────────────
#  检索
# ──────────────────────────────────────────────

def retrieve(
    query: str, top_k: Optional[int] = None
) -> Dict[str, Any]:
    """向量检索（单路或 RRF 双路）。

    Args:
        query: 查询文本。
        top_k: 返回命中数，None 则用 config.RAG_TOP_K。

    Returns:
        {"hits": [...], "query": query}
    """
    try:
        embedder = _get_embedder()
        store = _get_store()
        k = top_k or config.RAG_TOP_K

        if store.count() == 0:
            return {"hits": [], "query": query}

        if embedder.is_dual:
            hits = rrf_rerank(query, top_k=k)
        else:
            q_vec = embedder.embed_query(query)
            hits = store.query(q_vec, top_k=k)["hits"]

        return {"hits": hits, "query": query}

    except Exception as e:
        return {"hits": [], "query": query, "error": str(e)}


# ──────────────────────────────────────────────
#  RAG 问答
# ──────────────────────────────────────────────

def answer_rag(
    query: str,
    top_k: Optional[int] = None,
    lang: str = "zh",
) -> str:
    """RAG 问答（非流式），自动记录查询历史。"""
    from src.llm import get_llm

    store = _get_store()
    if store.count() == 0:
        return "⚠️ 向量库为空，请先导入论文数据。"

    result = retrieve(query, top_k=top_k)
    hits = result.get("hits", [])
    if not hits:
        return "未找到相关论文片段，请尝试修改查询。"

    llm = get_llm()
    answer = llm.complete_with_context(query, hits, lang=lang)

    # ── 记录查询历史（§19 DAO） ──
    try:
        query_dao: QueryDAO = get_dao("query")
        qid = query_dao.insert(QueryRecord(
            query_text=query, answer_text=answer, lang=lang, hit_count=len(hits)
        ))
        # 记录涉及论文（N:M 中间表）
        paper_ids: set[int] = set()
        paper_dao: PaperDAO = get_dao("paper")
        for hit in hits:
            meta = hit.get("metadata") or {}
            aid = meta.get("arxiv_id") or ""
            if aid:
                p = paper_dao.find_by_arxiv_id(aid)
                if p and p.id:
                    paper_ids.add(p.id)
        for pid in paper_ids:
            query_dao.link_paper(qid, pid)
    except Exception:
        pass  # 历史记录失败不阻塞主流程

    return answer


def answer_rag_stream(
    query: str,
    top_k: Optional[int] = None,
    lang: str = "zh",
) -> Generator[str, None, None]:
    """RAG 问答（流式），检索结果缓存用于历史记录。"""
    from src.llm import get_llm

    store = _get_store()
    if store.count() == 0:
        yield "⚠️ 向量库为空，请先导入论文数据。"
        return

    result = retrieve(query, top_k=top_k)
    hits = result.get("hits", [])
    if not hits:
        yield "未找到相关论文片段，请尝试修改查询。"
        return

    llm = get_llm()
    full_answer = ""
    for token in llm.complete_with_context_stream(query, hits, lang=lang):
        full_answer += token
        yield token

    # ── 流式结束后记录查询历史 ──
    try:
        query_dao: QueryDAO = get_dao("query")
        qid = query_dao.insert(QueryRecord(
            query_text=query, answer_text=full_answer, lang=lang, hit_count=len(hits)
        ))
        paper_ids: set[int] = set()
        paper_dao: PaperDAO = get_dao("paper")
        for hit in hits:
            meta = hit.get("metadata") or {}
            aid = meta.get("arxiv_id") or ""
            if aid:
                p = paper_dao.find_by_arxiv_id(aid)
                if p and p.id:
                    paper_ids.add(p.id)
        for pid in paper_ids:
            query_dao.link_paper(qid, pid)
    except Exception:
        pass


# ──────────────────────────────────────────────
#  单文档摘要
# ──────────────────────────────────────────────

def summarize_paper(
    arxiv_id: str,
    lang: str = "zh",
    max_chars: int = 8000,
) -> str:
    """对指定论文生成摘要。

    从 data/parsed/{arxiv_id}.json 读取全文并调 LLM。

    Args:
        arxiv_id: arXiv ID，如 "2606.13673v1"。
        lang: "zh" 或 "en"。
        max_chars: 传给 LLM 的文本上限（截断）。

    Returns:
        摘要文本。
    """
    from src.llm import get_llm

    json_path = config.PARSED_DIR / f"{arxiv_id}.json"
    if not json_path.exists():
        return f"⚠️ 未找到解析文件：{json_path}"

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        sections = data.get("sections", [])
        text_parts = []
        for sec in sections:
            content = sec.get("content", "").strip()
            if content:
                text_parts.append(content)
            for sub in sec.get("subsections", []):
                sc = sub.get("content", "").strip()
                if sc:
                    text_parts.append(sc)

        full_text = "\n\n".join(text_parts)
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "…"

        llm = get_llm()
        return llm.summarize(full_text, lang=lang)
    except Exception as e:
        return f"摘要生成失败: {e}"


# ──────────────────────────────────────────────
#  综述
# ──────────────────────────────────────────────

def survey(
    query: str,
    top_k: Optional[int] = None,
    lang: str = "zh",
) -> str:
    """多文档综述生成。

    Args:
        query: 搜索主题。
        top_k: 检索命中数（建议 10+ 以保证覆盖面）。
        lang: "zh" 或 "en"。

    Returns:
        综述文本。
    """
    from src.llm import get_llm

    result = retrieve(query, top_k=top_k or max(config.RAG_TOP_K, 10))
    hits = result.get("hits", [])
    if not hits:
        return "未找到相关论文片段，无法生成综述。"

    llm = get_llm()
    return llm.survey(hits, lang=lang)


# ──────────────────────────────────────────────
#  向量库管理
# ──────────────────────────────────────────────

def get_store_stats() -> Dict[str, Any]:
    """返回向量库状态。"""
    store = _get_store()
    return {
        "collection_name": store.collection_name,
        "count": store.count(),
        "persist_dir": str(store.persist_dir),
    }


def list_papers() -> List[Dict[str, str]]:
    """列出已入库论文（优先查传统数据库，回退到向量库扫描）。"""
    paper_dao: PaperDAO = get_dao("paper")
    db_papers = paper_dao.find_ingested()
    if db_papers:
        return [{"arxiv_id": p.arxiv_id, "title": p.title} for p in db_papers]

    # 回退：从向量库元数据扫描
    store = _get_store()
    if store.count() == 0:
        return []
    seen: Dict[str, str] = {}
    sample = store.peek(limit=min(store.count(), 500))
    for item in sample:
        meta = item.get("metadata") or {}
        aid = meta.get("arxiv_id") or ""
        title = meta.get("title") or meta.get("source") or ""
        if aid and aid not in seen:
            seen[aid] = title
    return [{"arxiv_id": k, "title": v} for k, v in seen.items()]


def reset_store() -> Dict[str, Any]:
    """清空向量库。"""
    try:
        store = _get_store()
        store.reset()
        return {"status": "ok", "count": 0}
    except Exception as e:
        return {"error": str(e)}
