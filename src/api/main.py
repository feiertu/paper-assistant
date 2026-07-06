"""Paper Assistant FastAPI 应用。

启动：
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import csv
import io
import json
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import config
from src.cache import get_cache_stats
from src.db import get_dao, get_connection
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
from src.agent import AgentQueryRequest, AgentQueryResponse, run_agent_stream as agent_run_stream
from src.api.middleware import ApiKeyMiddleware, RateLimitMiddleware, parse_rate_limit
from src.logging_config import get_logger

logger = get_logger(__name__)

# ── 启动配置校验 ──


def _validate_config_on_startup() -> None:
    """启动时校验关键配置，缺失则立即报错。"""
    errors = []
    if not config.OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY 未设置")
    if "voyage" in config.EMBEDDING_PROVIDER and not config.VOYAGE_API_KEY:
        errors.append("EMBEDDING_PROVIDER 包含 voyage 但 VOYAGE_API_KEY 未设置")
    if not config.ARXIV_QUERY:
        errors.append("ARXIV_QUERY 为空")
    if errors:
        msg = "启动配置校验失败:\n  - " + "\n  - ".join(errors)
        logger.error(msg)
        raise RuntimeError(msg)

    # 软警告：默认模型不是 OpenAI 原生模型，但 base_url 未改
    if (not config.OPENAI_BASE_URL
            and config.LLM_MODEL not in ("gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo")
            and not config.LLM_MODEL.startswith("gpt-")):
        logger.warning(
            "⚠️  LLM_MODEL=%s 但 OPENAI_BASE_URL 未设置，"
            "将使用 OpenAI 默认地址 https://api.openai.com/v1，可能不兼容。"
            "如果是国产模型，请在 .env 中设置 OPENAI_BASE_URL",
            config.LLM_MODEL,
        )

    logger.info("配置校验通过")


_validate_config_on_startup()

# ── App 实例 ──

app = FastAPI(
    title=config.UI_TITLE,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── 请求体大小限制（防止大文件上传攻击） ──
_MAX_BODY_SIZE = 50 * 1024 * 1024  # 50MB


@app.middleware("http")
async def body_size_limit_middleware(request: Request, call_next):
    """拒绝超过 MAX_BODY_SIZE 的请求，在读 body 之前拦截。"""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_BODY_SIZE:
        return JSONResponse(
            status_code=413,
            content={"detail": f"请求体过大，最大允许 {_MAX_BODY_SIZE // 1024 // 1024}MB"},
        )
    return await call_next(request)


# ── 中间件（顺序重要：body size → CORS → 请求日志 → 鉴权 → 限流） ──

cors_origins = [o.strip() for o in config.API_CORS_ORIGINS.split(",") if o.strip()]
if not cors_origins:
    logger.warning(
        "⚠️  CORS origins 未设置！API 将拒绝所有跨域请求。"
        " 生产环境请在 .env 中设置 API_CORS_ORIGINS=你的域名"
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins else [],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 请求日志中间件
@app.middleware("http")
async def request_log_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000)
    logger.info("%s %s → %d (%dms)",
                request.method, request.url.path,
                response.status_code, duration_ms)
    return response

app.add_middleware(ApiKeyMiddleware)

max_req, rate_window = parse_rate_limit(config.API_RATE_LIMIT)
app.add_middleware(RateLimitMiddleware, max_requests=max_req, window_seconds=rate_window)

logger.info("API 服务启动: auth=%s rate_limit=%s cors=%s",
            "enabled" if config.API_AUTH_ENABLED else "disabled",
            config.API_RATE_LIMIT, config.API_CORS_ORIGINS)


# ── 统一错误响应 ──

def api_error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": status_code, "message": detail}},
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
    """浅层健康检查（用于 Docker HEALTHCHECK）。"""
    return {"status": "ok"}


@app.get("/health/deep")
def health_deep():
    """深度健康检查：验证 DB / Chroma / LLM 连通性。"""
    checks = {}
    healthy = True

    # 1) SQLite
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        healthy = False

    # 2) Chroma
    try:
        from src.store import get_store
        store = get_store()
        count = store.count()
        checks["chroma"] = f"ok (count={count})"
    except Exception as e:
        checks["chroma"] = f"error: {e}"
        healthy = False

    # 3) LLM API key
    checks["llm_key_set"] = bool(config.OPENAI_API_KEY)

    # 4) Embedding provider
    checks["embed_provider"] = config.EMBEDDING_PROVIDER

    # 5) Cache
    try:
        cache_s = get_cache_stats()
        checks["cache"] = cache_s
    except Exception:
        checks["cache"] = "unavailable"

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "healthy" if healthy else "degraded", "checks": checks},
    )


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


# ── Agent 多步推理 ──

@app.post("/agent/query")
def agent_query(req: AgentQueryRequest):
    """Agent 非流式查询：收集所有事件后返回完整结果。"""
    events = []
    answer_parts = []
    total_tokens = 0
    steps = 0
    duration_ms = 0

    for event in agent_run_stream(
        query=req.query,
        lang=req.lang,
        max_iterations=req.max_iterations,
        enabled_tools=req.enabled_tools,
    ):
        events.append(event.model_dump())
        if event.type == "answer_chunk":
            answer_parts.append(event.content)
        elif event.type == "usage":
            total_tokens = event.total_tokens or 0
            steps = event.steps or 0
            duration_ms = event.duration_ms or 0

    answer = "".join(answer_parts)
    if not answer.strip():
        answer = "Agent 未生成有效回答。请检查查询内容或已入库论文。"
    return AgentQueryResponse(
        query=req.query,
        answer=answer,
        reasoning_steps=events,
        iterations=steps,
        total_tokens=total_tokens,
        duration_ms=duration_ms,
    )


@app.post("/agent/query/stream")
def agent_query_stream(req: AgentQueryRequest):
    """Agent 流式查询：SSE 事件流实时展示推理过程。

    事件类型: thinking / tool_call / tool_result / answer_chunk / error / usage / done
    """
    def _gen():
        for event in agent_run_stream(
            query=req.query,
            lang=req.lang,
            max_iterations=req.max_iterations,
            enabled_tools=req.enabled_tools,
        ):
            yield f"event: step\ndata: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"
        yield "event: done\ndata: [DONE]\n\n"

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


# ── arXiv 抓取管道 ──

class ArxivFetchRequest(BaseModel):
    query: str = Field(default="", description="arXiv 搜索查询，留空使用默认配置")
    max_results: int = Field(default=5, ge=1, le=50, description="最多抓取篇数")
    auto_ingest: bool = Field(default=True, description="下载+解析后自动入库")


@app.post("/arxiv/fetch")
def arxiv_fetch(req: ArxivFetchRequest):
    """抓取 arXiv 论文：搜索 → 保存元数据。

    返回找到的论文列表及其 ID。
    """
    from src.fetch.arxiv import fetch_and_persist

    query = req.query or None
    papers = fetch_and_persist(query=query, max_results=req.max_results)
    return {
        "status": "ok",
        "count": len(papers),
        "papers": [{"arxiv_id": p["id"], "title": p["title"][:120]} for p in papers],
    }


@app.post("/arxiv/download")
def arxiv_download(req: ArxivFetchRequest):
    """下载已抓取论文的 PDF（需先调用 /arxiv/fetch）。"""
    from src.fetch.download_pdf import batch_download
    from src.db import get_dao

    dao = get_dao("paper")
    papers = dao.find_all(limit=req.max_results)
    pending = [
        {"id": p.arxiv_id, "pdf_url": p.pdf_url}
        for p in papers
        if p.pdf_url and p.ingest_status == "pending"
    ]
    if not pending:
        return {"status": "ok", "downloaded": 0, "message": "没有待下载的论文"}

    results = batch_download(pending, delay=config.PDF_DOWNLOAD_DELAY)
    return {
        "status": "ok",
        "downloaded": len(results["success"]),
        "failed": len(results["failed"]),
        "details": results,
    }


@app.post("/arxiv/parse")
def arxiv_parse():
    """解析 raw/ 下所有 PDF 为 JSON（保存到 parsed/）。"""
    import os
    from src.parse.pdf import parse_pdf_structure

    raw_dir = config.RAW_PDF_DIR
    parsed_dir = config.PARSED_DIR
    parsed_dir.mkdir(parents=True, exist_ok=True)

    pdfs = list(raw_dir.glob("*.pdf"))
    if not pdfs:
        return {"status": "ok", "parsed": 0, "message": "raw/ 目录下没有 PDF"}

    success, failed = 0, 0
    for pdf_path in pdfs:
        arxiv_id = pdf_path.stem
        json_path = parsed_dir / f"{arxiv_id}.json"
        try:
            if json_path.exists():
                logger.debug("跳过已解析: %s", arxiv_id)
                success += 1
                continue
            structure = parse_pdf_structure(str(pdf_path))
            json_path.write_text(json.dumps(structure, ensure_ascii=False, indent=2), encoding="utf-8")
            success += 1
            logger.info("解析成功: %s", arxiv_id)
        except Exception as e:
            failed += 1
            logger.error("解析失败 %s: %s", arxiv_id, e)

    return {"status": "ok", "parsed": success, "failed": failed}


class ArxivPipelineRequest(BaseModel):
    query: str = Field(default="", description="arXiv 搜索查询")
    max_results: int = Field(default=5, ge=1, le=50)
    auto_ingest: bool = Field(default=True)


@app.post("/arxiv/pipeline")
def arxiv_pipeline(req: ArxivPipelineRequest):
    """一键管道：搜索 → 下载 → 解析 → 入库。"""
    steps = []

    # 1. 搜索并保存元数据
    from src.fetch.arxiv import fetch_and_persist
    query = req.query or None
    papers = fetch_and_persist(query=query, max_results=req.max_results)
    steps.append({"step": "fetch", "count": len(papers)})
    if not papers:
        return {"status": "ok", "steps": steps, "message": "arXiv 搜索无结果"}

    # 2. 下载 PDF
    from src.fetch.download_pdf import batch_download
    import time as _time
    pending = [{"id": p["id"], "pdf_url": p["pdf_url"]} for p in papers if p.get("pdf_url")]
    dl_result = batch_download(pending, delay=config.PDF_DOWNLOAD_DELAY)
    steps.append({"step": "download", "success": len(dl_result["success"]),
                  "failed": len(dl_result["failed"])})

    # 3. 解析 PDF
    import json as _json
    from src.parse.pdf import parse_pdf_structure
    parsed_dir = config.PARSED_DIR
    parsed_dir.mkdir(parents=True, exist_ok=True)
    parsed_cnt = 0
    for p in papers:
        pdf_path = config.RAW_PDF_DIR / f"{p['id']}.pdf"
        json_path = parsed_dir / f"{p['id']}.json"
        if pdf_path.exists() and not json_path.exists():
            try:
                structure = parse_pdf_structure(str(pdf_path))
                json_path.write_text(_json.dumps(structure, ensure_ascii=False, indent=2), encoding="utf-8")
                parsed_cnt += 1
            except Exception as e:
                logger.error("解析失败 %s: %s", p['id'], e)
    steps.append({"step": "parse", "count": parsed_cnt})

    # 4. 入库
    if req.auto_ingest and parsed_cnt > 0:
        result = ingest_parsed_dir()
        ingest_count = result.get("papers", 0)
        steps.append({"step": "ingest", "papers": ingest_count,
                      "chunks": result.get("chunks", 0)})

    return {"status": "ok", "steps": steps}


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
def collections_list(limit: int = 50, offset: int = 0):
    dao = get_dao("collection")
    cols = dao.find_all(limit=limit, offset=offset)
    return {
        "collections": [{"id": c.id, "name": c.name, "description": c.description,
                          "paper_count": c.paper_count, "created_at": c.created_at}
                         for c in cols],
        "total": dao.count(),
    }


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
def collections_list_papers(collection_id: int, limit: int = 50, offset: int = 0):
    papers = get_dao("collection").list_papers(collection_id)
    total = len(papers)
    papers = papers[offset:offset + limit]
    return {"papers": [p.to_dict() for p in papers], "total": total}


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
    import re
    # 安全校验：arxiv_id 必须匹配合法格式，防止目录遍历攻击
    if not re.match(r'^[\w.-]+$', arxiv_id) or '..' in arxiv_id:
        raise HTTPException(status_code=400, detail=f"无效的 arxiv_id: {arxiv_id}")
    pdf_path = (config.RAW_PDF_DIR / f"{arxiv_id}.pdf").resolve()
    # 确保路径在 RAW_PDF_DIR 下（二次防护目录遍历）
    if not str(pdf_path).startswith(str(config.RAW_PDF_DIR.resolve())):
        raise HTTPException(status_code=400, detail=f"非法的 PDF 路径: {arxiv_id}")
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
    import os
    import uvicorn

    is_dev = os.getenv("PAPER_ASSISTANT_ENV", "dev") == "dev"
    uvicorn.run(
        "src.api.main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=is_dev,
        workers=1 if is_dev else None,  # 生产用 --workers 参数控制
    )
