"""Paper Assistant FastAPI 应用。

启动：
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import config
from src.cache import get_cache_stats
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
from src.api.middleware import ApiKeyMiddleware, RateLimitMiddleware, parse_rate_limit
from src.logging_config import get_logger

logger = get_logger(__name__)

# ── App 实例 ──

app = FastAPI(
    title=config.UI_TITLE,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── 中间件（顺序重要：CORS → 鉴权 → 限流） ──

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(ApiKeyMiddleware)

max_req, rate_window = parse_rate_limit(config.API_RATE_LIMIT)
app.add_middleware(RateLimitMiddleware, max_requests=max_req, window_seconds=rate_window)

logger.info("API 服务启动: auth=%s rate_limit=%s",
            "enabled" if config.API_AUTH_ENABLED else "disabled",
            config.API_RATE_LIMIT)


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


@app.get("/papers/search")
def papers_search(
    keyword: str = Query("", description="FTS5 全文搜索关键词"),
    arxiv_id: str = Query("", description="arXiv ID 模糊匹配"),
    author: str = Query("", description="作者名模糊匹配"),
    year_from: str = Query("", description="年份起始"),
    year_to: str = Query("", description="年份截止"),
    source: str = Query("", description="来源: arxiv/grobid/pymupdf/manual"),
    status: str = Query("", description="入库状态: pending/ingested/failed"),
    sort_by: str = Query("created_at", description="排序: created_at/title/published"),
    limit: int = Query(50, ge=1, le=500),
):
    """全文搜索 + 多条件过滤。"""
    dao = get_dao("paper")
    results = dao.search(
        keyword=keyword, limit=limit, arxiv_id=arxiv_id, author=author,
        year_from=year_from, year_to=year_to, source=source, status=status,
        sort_by=sort_by,
    )
    return {"papers": [p.to_dict() for p in results], "total": len(results)}


# ── 引用关系 ──

@app.get("/papers/{arxiv_id}/citations")
def papers_citations(arxiv_id: str):
    """获取论文引用关系图。"""
    dao = get_dao("citation")
    return dao.get_graph(arxiv_id)


@app.post("/citations/extract")
def citations_extract(arxiv_ids: Optional[List[str]] = None):
    """批量提取引用关系。

    Args:
        arxiv_ids: 指定论文 ID 列表，不传则处理全部已解析论文。
    """
    from src.parse.citations import batch_extract_citations
    result = batch_extract_citations(arxiv_ids)
    return result


@app.get("/citations/stats")
def citations_stats():
    """引用关系统计。"""
    dao = get_dao("citation")
    return {"total_citations": dao.count()}


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


# ── 缓存状态 ──

@app.get("/cache/stats")
def cache_stats():
    """查看缓存命中率统计。"""
    return get_cache_stats()


@app.delete("/cache/clear")
def cache_clear(kind: str = Query("all", description="缓存类型: all / llm / embed")):
    """清空缓存。"""
    from src.cache import get_llm_cache as _llm_cache, get_embed_cache as _embed_cache
    if kind in ("all", "llm"):
        _llm_cache().clear()
    if kind in ("all", "embed"):
        _embed_cache().clear()
    return {"status": "ok", "kind": kind}


# ── PDF 在线预览 ──

@app.get("/papers/{arxiv_id}/pdf")
def papers_pdf(arxiv_id: str):
    """获取 PDF 文件（用于在线预览）。"""
    pdf_path = config.RAW_PDF_DIR / f"{arxiv_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF 不存在: {arxiv_id}")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={arxiv_id}.pdf"},
    )


# ── 论文推荐（基于向量相似度） ──

class RecommendRequest(BaseModel):
    arxiv_id: str
    top_k: int = Field(default=5, ge=1, le=20)


@app.post("/papers/recommend")
def papers_recommend(req: RecommendRequest):
    """根据论文 arxiv_id 推荐相似论文。"""
    from src.rag import recommend_similar
    try:
        results = recommend_similar(req.arxiv_id, top_k=req.top_k)
        return {"arxiv_id": req.arxiv_id, "similar": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 数据导出 ──

@app.get("/export/papers")
def export_papers(
    fmt: str = Query("json", description="导出格式: json / csv / bibtex"),
    limit: int = Query(200, ge=1, le=1000),
):
    """导出论文数据。"""
    dao = get_dao("paper")
    papers = dao.find_all(limit=limit)

    if fmt == "json":
        return {"papers": [p.to_dict() for p in papers]}

    elif fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "arxiv_id", "title", "authors", "abstract",
                          "published", "pdf_url", "source", "ingest_status", "chunk_count"])
        for p in papers:
            writer.writerow([
                p.id, p.arxiv_id, p.title, p.authors, p.abstract,
                p.published, p.pdf_url, p.source, p.ingest_status, p.chunk_count,
            ])
        csv_content = output.getvalue()
        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=papers.csv"},
        )

    elif fmt == "bibtex":
        entries = []
        for p in papers:
            author_first = p.authors.split(",")[0].strip().split()[-1] if p.authors else "Unknown"
            key = f"{author_first}{p.published[:4] if p.published else '0000'}"
            entries.append(
                f"@article{{{key},\n"
                f"  title = {{{{{p.title}}}}},\n"
                f"  author = {{{{{p.authors}}}}},\n"
                f"  year = {{{{{p.published[:4] if p.published else '????'}}}}},\n"
                f"  eprint = {{{{{p.arxiv_id}}}}},\n"
                f"  url = {{{{{p.pdf_url}}}}},\n"
                f"}}"
            )
        bib_content = "\n\n".join(entries)
        return StreamingResponse(
            iter([bib_content]),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=papers.bib"},
        )

    raise HTTPException(status_code=400, detail=f"不支持的格式: {fmt}，可选 json / csv / bibtex")


@app.get("/export/queries")
def export_queries(fmt: str = Query("json"), limit: int = Query(500)):
    """导出查询历史。"""
    dao = get_dao("query")
    records = dao.find_recent(limit=limit)

    if fmt == "json":
        return {
            "queries": [
                {"id": r.id, "query_text": r.query_text, "answer_text": r.answer_text,
                 "lang": r.lang, "hit_count": r.hit_count, "created_at": r.created_at}
                for r in records
            ]
        }

    elif fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "query_text", "answer_text", "lang", "hit_count", "created_at"])
        for r in records:
            writer.writerow([r.id, r.query_text, r.answer_text, r.lang, r.hit_count, r.created_at])
        csv_content = output.getvalue()
        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=queries.csv"},
        )

    raise HTTPException(status_code=400, detail=f"不支持的格式: {fmt}")


# ── 语言检测 ──

@app.get("/papers/{arxiv_id}/language")
def papers_language(arxiv_id: str):
    """检测论文语言（基于解析后的 JSON）。"""
    json_path = config.PARSED_DIR / f"{arxiv_id}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail=f"未找到解析文件: {arxiv_id}")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        from src.parse.language import detect_json_language
        return detect_json_language(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 向量库备份/恢复 ──

@app.post("/store/backup")
def store_backup():
    """备份 Chroma 向量库到 data/chroma_backup/。"""
    import shutil
    from datetime import datetime

    backup_dir = config.DATA_DIR / "chroma_backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
    if config.CHROMA_DIR.exists():
        shutil.copytree(str(config.CHROMA_DIR), str(backup_dir))
        logger.info("向量库备份完成: %s", backup_dir)
        return {"status": "ok", "backup_dir": str(backup_dir)}
    return {"status": "error", "detail": "Chroma 目录不存在"}


@app.get("/store/backups")
def store_backups():
    """列出备份。"""
    backup_root = config.DATA_DIR / "chroma_backup"
    if not backup_root.exists():
        return {"backups": []}
    backups = sorted(backup_root.iterdir(), key=lambda p: p.name, reverse=True)
    return {
        "backups": [
            {"name": d.name, "path": str(d), "size_mb": round(
                sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1024 / 1024, 2
            )}
            for d in backups if d.is_dir()
        ]
    }


class RestoreRequest(BaseModel):
    backup_name: str


@app.post("/store/restore")
def store_restore(req: RestoreRequest):
    """从备份恢复向量库。"""
    import shutil

    backup_dir = config.DATA_DIR / "chroma_backup" / req.backup_name
    if not backup_dir.exists():
        raise HTTPException(status_code=404, detail=f"备份不存在: {req.backup_name}")

    # 删除当前，从备份复制
    if config.CHROMA_DIR.exists():
        shutil.rmtree(str(config.CHROMA_DIR))
    shutil.copytree(str(backup_dir), str(config.CHROMA_DIR))
    logger.info("向量库恢复完成: %s", req.backup_name)
    return {"status": "ok", "restored_from": req.backup_name}


# ── 入口 ──

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=True,
    )
