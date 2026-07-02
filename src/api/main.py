"""Paper Assistant FastAPI 应用。

启动：
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import config
from src.db import get_dao
from src.rag import (
    answer_rag,
    answer_rag_stream,
    get_store_stats,
    ingest_parsed_dir,
    ingest_text,
    list_papers,
    reset_store,
    retrieve,
    summarize_paper,
    survey,
)

# ── App 实例 ──

app = FastAPI(
    title=config.UI_TITLE,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 请求模型 ──

class RetrieveRequest(BaseModel):
    query: str
    top_k: int = Field(default=config.RAG_TOP_K, ge=1, le=50)


class RAGQueryRequest(BaseModel):
    query: str
    top_k: int = Field(default=config.RAG_TOP_K, ge=1, le=50)
    lang: str = "zh"


class SummarizeRequest(BaseModel):
    arxiv_id: str
    lang: str = "zh"


class SurveyRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    lang: str = "zh"


class IngestRequest(BaseModel):
    reset: bool = False


class IngestTextRequest(BaseModel):
    text: str
    metadata: Optional[Dict[str, Any]] = None


# ── 健康检查 ──

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/config")
def get_config():
    return config.summary()


# ── 检索 ──

@app.post("/retrieve")
def retrieve_route(req: RetrieveRequest):
    return retrieve(req.query, top_k=req.top_k)


# ── RAG 问答 ──

@app.post("/rag/query")
def rag_query(req: RAGQueryRequest):
    answer = answer_rag(req.query, top_k=req.top_k, lang=req.lang)
    return {"answer": answer}


@app.post("/rag/query/stream")
def rag_query_stream(req: RAGQueryRequest):
    def _gen():
        for token in answer_rag_stream(req.query, top_k=req.top_k, lang=req.lang):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ── 摘要 / 综述 ──

@app.post("/summarize")
def summarize_route(req: SummarizeRequest):
    result = summarize_paper(req.arxiv_id, lang=req.lang)
    return {"summary": result}


@app.post("/survey")
def survey_route(req: SurveyRequest):
    result = survey(req.query, top_k=req.top_k, lang=req.lang)
    return {"survey": result}


# ── 数据入库 ──

@app.post("/ingest")
def ingest_route(req: IngestRequest):
    result = ingest_parsed_dir(reset=req.reset)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/ingest/text")
def ingest_text_route(req: IngestTextRequest):
    result = ingest_text(req.text, req.metadata)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── 向量库管理 ──

@app.get("/store/stats")
def store_stats():
    return get_store_stats()


@app.get("/store/papers")
def store_papers():
    return list_papers()


@app.delete("/store/reset")
def store_reset():
    result = reset_store()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


# ── 论文元数据 ──

@app.get("/papers")
def papers_list(limit: int = 50, offset: int = 0):
    dao = get_dao("paper")
    papers = dao.find_all(limit=limit, offset=offset)
    return {"papers": [p.to_dict() for p in papers], "total": dao.count()}


@app.get("/papers/{arxiv_id}")
def papers_get(arxiv_id: str):
    dao = get_dao("paper")
    p = dao.find_by_arxiv_id(arxiv_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"论文不存在: {arxiv_id}")
    return p.to_dict()


# ── 查询历史 ──

@app.get("/queries")
def queries_list(limit: int = 20):
    dao = get_dao("query")
    records = dao.find_recent(limit=limit)
    return {
        "queries": [
            {
                "id": r.id,
                "query_text": r.query_text,
                "answer_text": r.answer_text[:200] + ("…" if len(r.answer_text) > 200 else ""),
                "lang": r.lang,
                "hit_count": r.hit_count,
                "created_at": r.created_at,
            }
            for r in records
        ],
        "total": dao.count(),
    }


@app.delete("/queries")
def queries_clear():
    get_dao("query").clear()
    return {"status": "ok"}


# ── 收藏夹 ──

@app.get("/collections")
def collections_list():
    dao = get_dao("collection")
    cols = dao.find_all()
    return {"collections": [{"id": c.id, "name": c.name, "description": c.description, "paper_count": c.paper_count, "created_at": c.created_at} for c in cols]}


class CreateCollectionRequest(BaseModel):
    name: str
    description: str = ""


@app.post("/collections")
def collections_create(req: CreateCollectionRequest):
    dao = get_dao("collection")
    cid = dao.create(req.name, req.description)
    return {"id": cid, "status": "ok"}


@app.delete("/collections/{collection_id}")
def collections_delete(collection_id: int):
    ok = get_dao("collection").delete(collection_id)
    if not ok:
        raise HTTPException(status_code=404)
    return {"status": "ok"}


class CollectionPaperRequest(BaseModel):
    paper_id: int


@app.post("/collections/{collection_id}/papers")
def collections_add_paper(collection_id: int, req: CollectionPaperRequest):
    get_dao("collection").add_paper(collection_id, req.paper_id)
    return {"status": "ok"}


@app.get("/collections/{collection_id}/papers")
def collections_list_papers(collection_id: int):
    papers = get_dao("collection").list_papers(collection_id)
    return {"papers": [p.to_dict() for p in papers]}


# ── 入口 ──

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=True,
    )
