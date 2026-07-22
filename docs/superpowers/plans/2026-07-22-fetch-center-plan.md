# 论文抓取中心 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建独立的「论文抓取中心」页面，持久化抓取历史，实现去重透明性；将 arXiv 抓取表单从 LibraryPage 移出。

**Architecture:** 新建 `fetch_history` 表存储抓取历史 (FetchHistory dataclass → FetchHistoryDAO → API 端点 → FetchPage.vue)；改造 `fetch_and_persist()` 返回跳过论文信息；修改 `POST /arxiv/pipeline` 在完成后写入历史。

**Tech Stack:** Python 3.11+ (FastAPI + SQLite), Vue 3.5 + TypeScript + Tailwind CSS v4

## Global Constraints

- 现有 `/arxiv/pipeline` API 返回值不变（向后兼容）
- 所有数据库操作按 owner_id 隔离
- 前端使用 fetch() API（非 axios），路径模式跟随 `client.ts`
- 遵循现有 DAO 工厂模式、dataclass 模式、迁移文件模式

---

## File Structure

```
新建:
  migrations/versions/002_fetch_history.py    — 新表 DDL 迁移
  frontend/src/components/pages/FetchPage.vue  — 抓取中心页面

修改:
  src/db/schema.py     — FetchHistory dataclass + DDL 追加
  src/db/dao.py        — FetchHistoryDAO + 工厂注册
  src/fetch/arxiv.py   — fetch_and_persist() 返回 dict 含跳过信息
  src/api/main.py      — 新增 GET 端点; pipeline/process-pending 写入历史
  frontend/src/api/types.ts          — FetchRecord / FetchHistoryResponse 类型
  frontend/src/api/client.ts         — fetchApi 模块
  frontend/src/router/index.ts       — /fetch 路由
  frontend/src/components/layout/Sidebar.vue   — "论文抓取" 导航项
  frontend/src/components/pages/LibraryPage.vue — 移除 arXiv 抓取 UI
```

---

### Task 1: FetchHistory dataclass + DDL + 迁移文件

**Files:**
- Modify: `src/db/schema.py` — 追加 dataclass + DDL
- Create: `migrations/versions/002_fetch_history.py`

**Interfaces:**
- Produces: `FetchHistory` dataclass — `from_row(row)`, `to_dict()`; DDL 确保表存在

- [ ] **Step 1: 在 `src/db/schema.py` 的 DDL 块末尾（`"""` 之前）追加 fetch_history 建表语句**

在文件第 223 行 `"""` 之前插入：

```sql

-- 抓取历史（实体：FetchHistory）
CREATE TABLE IF NOT EXISTS fetch_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text      TEXT    NOT NULL,
    max_results     INTEGER NOT NULL DEFAULT 5,
    total_found     INTEGER DEFAULT 0,
    fetched         INTEGER DEFAULT 0,
    skipped         INTEGER DEFAULT 0,
    download_success INTEGER DEFAULT 0,
    download_failed INTEGER DEFAULT 0,
    parse_success   INTEGER DEFAULT 0,
    parse_failed    INTEGER DEFAULT 0,
    ingested        INTEGER DEFAULT 0,
    skipped_papers  TEXT    DEFAULT '[]',
    owner_id        TEXT    DEFAULT '',
    created_at      TEXT    DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_fetch_history_owner ON fetch_history(owner_id);
CREATE INDEX IF NOT EXISTS idx_fetch_history_created ON fetch_history(created_at);
```

- [ ] **Step 2: 在 `src/db/schema.py` dataclass 区域（Collection 类之后，`# ── DDL` 之前）添加 FetchHistory dataclass**

在 `Collection` 的 `from_row` 方法之后、`# ── DDL（建表语句） ──` 注释之前插入：

```python

@dataclass
class FetchHistory:
    """抓取历史（对应 fetch_history 表）。"""

    query_text: str
    max_results: int = 5
    total_found: int = 0
    fetched: int = 0
    skipped: int = 0
    download_success: int = 0
    download_failed: int = 0
    parse_success: int = 0
    parse_failed: int = 0
    ingested: int = 0
    skipped_papers: str = "[]"
    owner_id: str = ""
    id: Optional[int] = None
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        import json as _json
        return {
            "id": self.id,
            "query_text": self.query_text,
            "max_results": self.max_results,
            "total_found": self.total_found,
            "fetched": self.fetched,
            "skipped": self.skipped,
            "download_success": self.download_success,
            "download_failed": self.download_failed,
            "parse_success": self.parse_success,
            "parse_failed": self.parse_failed,
            "ingested": self.ingested,
            "skipped_papers": _json.loads(self.skipped_papers) if self.skipped_papers else [],
            "owner_id": self.owner_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "FetchHistory":
        return cls(
            id=row["id"],
            query_text=row["query_text"],
            max_results=row["max_results"],
            total_found=row["total_found"] or 0,
            fetched=row["fetched"] or 0,
            skipped=row["skipped"] or 0,
            download_success=row["download_success"] or 0,
            download_failed=row["download_failed"] or 0,
            parse_success=row["parse_success"] or 0,
            parse_failed=row["parse_failed"] or 0,
            ingested=row["ingested"] or 0,
            skipped_papers=row["skipped_papers"] or "[]",
            owner_id=row["owner_id"] if "owner_id" in row.keys() else "",
            created_at=row["created_at"] or "",
        )
```

- [ ] **Step 3: 创建 `migrations/versions/002_fetch_history.py`**

```python
"""fetch_history

Revision ID: 002
Create Date: 2026-07-22

新增抓取历史表，记录每次 arXiv 抓取的结果统计和被跳过论文。
"""

revision = "002"
down_revision = "001"

DDL = """

-- 抓取历史（实体：FetchHistory）
CREATE TABLE IF NOT EXISTS fetch_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text      TEXT    NOT NULL,
    max_results     INTEGER NOT NULL DEFAULT 5,
    total_found     INTEGER DEFAULT 0,
    fetched         INTEGER DEFAULT 0,
    skipped         INTEGER DEFAULT 0,
    download_success INTEGER DEFAULT 0,
    download_failed INTEGER DEFAULT 0,
    parse_success   INTEGER DEFAULT 0,
    parse_failed    INTEGER DEFAULT 0,
    ingested        INTEGER DEFAULT 0,
    skipped_papers  TEXT    DEFAULT '[]',
    owner_id        TEXT    DEFAULT '',
    created_at      TEXT    DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_fetch_history_owner ON fetch_history(owner_id);
CREATE INDEX IF NOT EXISTS idx_fetch_history_created ON fetch_history(created_at);

"""


def upgrade():
    for stmt in DDL.split(";"):
        stmt = stmt.strip()
        if stmt and not stmt.startswith("--"):
            from src.db.schema import get_connection
            conn = get_connection()
            conn.execute(stmt)
            conn.commit()
            conn.close()


def downgrade():
    from src.db.schema import get_connection
    conn = get_connection()
    try:
        conn.execute("DROP TABLE IF EXISTS fetch_history")
    except Exception:
        pass
    conn.commit()
    conn.close()
```

- [ ] **Step 4: 验证 — 运行 Python 导入测试**

Run: `cd d:/git/paper-assistant && python -c "from src.db.schema import FetchHistory, get_connection; conn = get_connection(); conn.execute('SELECT 1 FROM fetch_history LIMIT 1'); print('OK')"`

Expected: 输出 `OK`，无异常。

- [ ] **Step 5: Commit**

```bash
git add src/db/schema.py migrations/versions/002_fetch_history.py
git commit -m "feat: add FetchHistory dataclass + fetch_history table migration

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: FetchHistoryDAO

**Files:**
- Modify: `src/db/dao.py` — 新增 FetchHistoryDAO + 工厂注册

**Interfaces:**
- Consumes: `FetchHistory` dataclass from Task 1
- Produces: `FetchHistoryDAO` via `get_dao("fetch_history")` — `insert(record)`, `find_all(limit, offset, owner_id)`, `find_by_id(id, owner_id)`, `count(owner_id)`

- [ ] **Step 1: 在 `src/db/dao.py` 的 CitationDAO 之后、`_extend_paper_dao` 之前添加 FetchHistoryDAO**

在 `CitationDAO` 类结束（约第 398 行 `def clear(self):` 之后）插入：

```python

# ══════════════════════════════════════════════
#  FetchHistoryDAO — 抓取历史访问
# ══════════════════════════════════════════════

class FetchHistoryDAO:
    """抓取历史 DAO。"""

    def insert(self, record) -> int:
        with get_connection() as conn:
            cur = conn.execute(
                """INSERT INTO fetch_history
                   (query_text, max_results, total_found, fetched, skipped,
                    download_success, download_failed, parse_success, parse_failed,
                    ingested, skipped_papers, owner_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record.query_text, record.max_results, record.total_found,
                 record.fetched, record.skipped, record.download_success,
                 record.download_failed, record.parse_success, record.parse_failed,
                 record.ingested, record.skipped_papers, record.owner_id),
            )
            conn.commit()
            return cur.lastrowid

    def find_all(self, limit: int = 20, offset: int = 0, owner_id: str = ""):
        from src.db.schema import FetchHistory
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM fetch_history WHERE owner_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (owner_id, limit, offset),
            ).fetchall()
            return [FetchHistory.from_row(r) for r in rows]

    def find_by_id(self, record_id: int, owner_id: str = ""):
        from src.db.schema import FetchHistory
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM fetch_history WHERE id = ? AND owner_id = ?",
                (record_id, owner_id),
            ).fetchone()
            return FetchHistory.from_row(row) if row else None

    def count(self, owner_id: str = "") -> int:
        with get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM fetch_history WHERE owner_id = ?", (owner_id,)
            ).fetchone()[0]
```

- [ ] **Step 2: 在 `get_dao()` 工厂函数中注册 `fetch_history`**

修改 `get_dao()` 函数中的 `_daos` 字典（约第 292 行），添加一行：

```python
_daos = {
    "paper": PaperDAO(),
    "query": QueryDAO(),
    "collection": CollectionDAO(),
    "citation": CitationDAO(),
    "fetch_history": FetchHistoryDAO(),
}
```

- [ ] **Step 3: 验证 — 测试 DAO 插入和查询**

Run: `cd d:/git/paper-assistant && python -c "
from src.db.dao import get_dao
from src.db.schema import FetchHistory

dao = get_dao('fetch_history')
r = FetchHistory(query_text='test', max_results=5, total_found=5, fetched=3, skipped=2, owner_id='test')
rid = dao.insert(r)
print(f'Inserted id={rid}')
rows = dao.find_all(limit=5, owner_id='test')
print(f'Found {len(rows)} records, first skipped_papers={rows[0].skipped_papers}')
print('OK')
"`

Expected: 输出 `Inserted id=1`, `Found 1 records`, `OK`。

- [ ] **Step 4: Commit**

```bash
git add src/db/dao.py
git commit -m "feat: add FetchHistoryDAO with CRUD + factory registration

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 改造 `fetch_and_persist()` 返回跳过论文

**Files:**
- Modify: `src/fetch/arxiv.py` — 函数签名和返回值

**Interfaces:**
- Consumes: `get_dao("paper").get_existing_ids()` (existing)
- Produces: `fetch_and_persist()` 现在返回 `dict` 而非 `List[Dict]`

- [ ] **Step 1: 修改 `save_metadata_to_db` 调用前的逻辑，记录跳过论文详情**

在 `src/fetch/arxiv.py` 的 `fetch_and_persist` 函数中（约第 161-163 行），修改去重逻辑以记录跳过论文的 id 和 title：

```python
def fetch_and_persist(query: Optional[str] = None, max_results: Optional[int] = None,
                      owner_id: str = "") -> dict:
    """抓取 arXiv 元数据并保存到数据库。已入库的论文自动跳过不重复抓取。

    Returns:
        dict: {
            "papers": List[Dict],    # 新论文（或全部论文，若无新论文）
            "skipped_papers": List[Dict],  # [{"id": str, "title": str}, ...]
            "total_found": int,
            "new_count": int,
        }
    """
    from src.db import get_dao

    paper_dao = get_dao("paper")

    papers = fetch_arxiv_metadata(query=query, max_results=max_results)

    # 过滤已入库论文 — 待处理/失败的仍允许重试
    ingested_ids = paper_dao.get_existing_ids(owner_id=owner_id)
    new_papers = [p for p in papers if p["id"] not in ingested_ids]
    skipped_papers = [{"id": p["id"], "title": p["title"]}
                      for p in papers if p["id"] in ingested_ids]
    skipped = len(papers) - len(new_papers)

    if new_papers:
        saved = save_metadata_to_db(new_papers, owner_id=owner_id)
        if skipped > 0:
            logger.info("已保存 %d/%d 条元数据，跳过 %d 篇已入库论文",
                        saved, len(new_papers), skipped)
        else:
            logger.info("已保存 %d/%d 条元数据到数据库", saved, len(papers))
    elif papers and skipped == len(papers):
        logger.info("全部 %d 篇论文已入库，跳过", skipped)

    return {
        "papers": new_papers if new_papers else papers,
        "skipped_papers": skipped_papers,
        "total_found": len(papers),
        "new_count": len(new_papers),
    }
```

- [ ] **Step 2: 验证 — 测试返回值结构**

Run: `cd d:/git/paper-assistant && python -c "
from src.fetch.arxiv import fetch_and_persist
result = fetch_and_persist(query='cat:cs.AI', max_results=1, owner_id='test')
print('Keys:', list(result.keys()))
print('Has papers:', 'papers' in result)
print('Has skipped_papers:', 'skipped_papers' in result)
print('Has total_found:', 'total_found' in result)
print('OK')
"`

Expected: 输出 keys 包含 `papers, skipped_papers, total_found, new_count`，`OK`。

- [ ] **Step 3: Commit**

```bash
git add src/fetch/arxiv.py
git commit -m "feat: fetch_and_persist returns dict with skipped paper info

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 后端 API — 历史端点 + pipeline 改造

**Files:**
- Modify: `src/api/main.py` — 更新调用点 + 新增端点

**Interfaces:**
- Consumes: `fetch_and_persist()` 新返回值 (Task 3), `get_dao("fetch_history")` (Task 2)
- Produces: `GET /fetch/history`, `GET /fetch/history/{id}`; 修改 `POST /arxiv/pipeline`, `POST /arxiv/process-pending`

- [ ] **Step 1: 更新 `arxiv_fetch()` 端点适配新的 `fetch_and_persist` 返回值**

在 `src/api/main.py` 中找到 `def arxiv_fetch` 函数（约第 492 行），修改：

```python
@app.post("/arxiv/fetch")
def arxiv_fetch(req: ArxivFetchRequest, request: Request):
    """抓取 arXiv 论文：搜索 → 保存元数据。"""
    from src.fetch.arxiv import fetch_and_persist

    owner_id = get_owner_id(request)
    query = req.query or None
    result = fetch_and_persist(query=query, max_results=req.max_results, owner_id=owner_id)
    papers = result["papers"]
    return {
        "status": "ok",
        "count": len(papers),
        "papers": [{"arxiv_id": p["id"], "title": p["title"][:120]} for p in papers],
        "skipped": len(result["skipped_papers"]),
    }
```

- [ ] **Step 2: 更新 `arxiv_pipeline()` 端点适配新返回值 + 写入历史**

在 `src/api/main.py` 中找到 `def arxiv_pipeline` 函数（约第 571 行），完整重写：

```python
@app.post("/arxiv/pipeline")
def arxiv_pipeline(req: ArxivPipelineRequest, request: Request):
    """一键管道：搜索 → 下载 → 解析 → 入库。"""
    import json as _json
    import time as _time

    owner_id = get_owner_id(request)
    steps = []
    dl_errors = []
    parse_errors = []

    # 1. 搜索并保存元数据
    from src.fetch.arxiv import fetch_and_persist
    query = req.query or None
    fetch_result = fetch_and_persist(query=query, max_results=req.max_results, owner_id=owner_id)
    papers = fetch_result["papers"]
    steps.append({"step": "fetch", "count": len(papers)})
    if not papers:
        # 全部被跳过，也写入历史
        _save_fetch_history(
            query=req.query, max_results=req.max_results,
            total_found=fetch_result["total_found"],
            fetched=0, skipped=len(fetch_result["skipped_papers"]),
            skipped_papers=fetch_result["skipped_papers"],
            download_success=0, download_failed=0,
            parse_success=0, parse_failed=0, ingested=0,
            owner_id=owner_id,
        )
        return {"status": "ok", "steps": steps, "message": "arXiv 搜索无结果或全部已入库"}

    # 2. 下载 PDF
    from src.fetch.download_pdf import batch_download
    pending = [{"id": p["id"], "pdf_url": p["pdf_url"]} for p in papers if p.get("pdf_url")]
    dl_result = batch_download(pending, delay=config.PDF_DOWNLOAD_DELAY)
    steps.append({"step": "download", "success": len(dl_result["success"]),
                  "failed": len(dl_result["failed"])})
    dl_errors = [{"id": f["id"], "error": f.get("error", "下载失败")} for f in dl_result.get("failed", [])]

    # 3. 解析 PDF
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
                parse_errors.append({"id": p['id'], "error": str(e)[:200]})
    steps.append({"step": "parse", "count": parsed_cnt})

    # 4. 入库
    ingest_count = 0
    chunk_count = 0
    if req.auto_ingest:
        result = ingest_parsed_dir(owner_id=owner_id)
        if "error" in result:
            steps.append({"step": "ingest", "error": result["error"]})
        else:
            ingest_count = result.get("papers", 0)
            chunk_count = result.get("chunks", 0)
            steps.append({"step": "ingest", "papers": ingest_count, "chunks": chunk_count})

    # 5. 写入抓取历史
    _save_fetch_history(
        query=req.query, max_results=req.max_results,
        total_found=fetch_result["total_found"],
        fetched=fetch_result["new_count"],
        skipped=len(fetch_result["skipped_papers"]),
        skipped_papers=fetch_result["skipped_papers"],
        download_success=len(dl_result["success"]),
        download_failed=len(dl_result["failed"]),
        parse_success=parsed_cnt,
        parse_failed=len(parse_errors),
        ingested=ingest_count,
        owner_id=owner_id,
    )

    return {
        "status": "ok",
        "steps": steps,
        "errors": {
            "download": dl_errors,
            "parse": parse_errors,
        },
    }
```

- [ ] **Step 3: 添加 `_save_fetch_history` 辅助函数**

在 `src/api/main.py` 中，`class ArxivFetchRequest` 之前（约第 484 行之前）添加：

```python

# ── 抓取历史辅助 ──

def _save_fetch_history(
    query: str, max_results: int,
    total_found: int, fetched: int, skipped: int,
    skipped_papers: list,
    download_success: int, download_failed: int,
    parse_success: int, parse_failed: int,
    ingested: int, owner_id: str,
) -> None:
    """将抓取结果写入 fetch_history 表。"""
    import json as _json
    from src.db.schema import FetchHistory

    dao = get_dao("fetch_history")
    record = FetchHistory(
        query_text=query or "",
        max_results=max_results,
        total_found=total_found,
        fetched=fetched,
        skipped=skipped,
        download_success=download_success,
        download_failed=download_failed,
        parse_success=parse_success,
        parse_failed=parse_failed,
        ingested=ingested,
        skipped_papers=_json.dumps(skipped_papers, ensure_ascii=False),
        owner_id=owner_id,
    )
    rid = dao.insert(record)
    logger.info("抓取历史已保存: id=%d query=%s fetched=%d skipped=%d",
                rid, query[:50], fetched, skipped)
```

- [ ] **Step 4: 在 `arxiv_process_pending` 端点中写入抓取历史**

在 `src/api/main.py` 的 `def arxiv_process_pending` 函数末尾，`return` 语句之前添加写入历史逻辑。

在 `ingest_error` 赋值之前找到 `return` 语句（约第 686-695 行），在 `return` 之前插入：

```python
    # 写入抓取历史
    _save_fetch_history(
        query="<手动处理待入库>",
        max_results=len(pending),
        total_found=len(pending),
        fetched=0,
        skipped=0,
        skipped_papers=[],
        download_success=dl_ok,
        download_failed=dl_fail,
        parse_success=parsed_cnt,
        parse_failed=max(0, dl_ok - parsed_cnt),
        ingested=ingest_result.get("papers", 0),
        owner_id=owner_id,
    )
```

- [ ] **Step 5: 新增 `GET /fetch/history` 和 `GET /fetch/history/{id}` 端点**

在 `src/api/main.py` 的 arXiv 相关端点区域（约第 696 行 `process_pending` 之后）添加：

```python

# ── 抓取历史 ──

@app.get("/fetch/history")
def fetch_history_list(limit: int = Query(20, ge=1, le=100),
                       offset: int = Query(0, ge=0),
                       request: Request = None):
    """查询抓取历史（按 owner 隔离，分页）。"""
    owner_id = get_owner_id(request) if request else ""
    dao = get_dao("fetch_history")
    records = dao.find_all(limit=limit, offset=offset, owner_id=owner_id)
    return {
        "records": [r.to_dict() for r in records],
        "total": dao.count(owner_id=owner_id),
    }


@app.get("/fetch/history/{record_id}")
def fetch_history_detail(record_id: int, request: Request = None):
    """单次抓取历史详情。"""
    owner_id = get_owner_id(request) if request else ""
    dao = get_dao("fetch_history")
    record = dao.find_by_id(record_id, owner_id=owner_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"抓取记录不存在: {record_id}")
    return record.to_dict()
```

- [ ] **Step 6: 验证 — 调用 pipeline 并检查历史端点**

```bash
cd d:/git/paper-assistant && python -c "
from src.api.main import app
from fastapi.testclient import TestClient

client = TestClient(app)
# 1. 调用 pipeline
resp = client.post('/arxiv/pipeline', json={'query': 'cat:cs.AI', 'max_results': 1}, headers={'X-Owner-Id': 'test'})
print('Pipeline status:', resp.status_code)
data = resp.json()
print('Steps:', [(s['step'], s.get('count', s.get('success', '?'))) for s in data['steps']])

# 2. 查询历史
resp2 = client.get('/fetch/history', headers={'X-Owner-Id': 'test'})
print('History status:', resp2.status_code)
hdata = resp2.json()
print('History total:', hdata['total'], 'records')
print('OK')
"`

Expected: `Pipeline status: 200`，`History total: >= 1`，`OK`。

(需要先 `pip install httpx` 如果未安装 TestClient 依赖)

- [ ] **Step 7: Commit**

```bash
git add src/api/main.py
git commit -m "feat: add fetch history API endpoints + pipeline auto-record

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 前端 — 类型定义 + API Client + 路由

**Files:**
- Modify: `frontend/src/api/types.ts` — 新增 FetchRecord / FetchHistoryResponse
- Modify: `frontend/src/api/client.ts` — 新增 fetchApi
- Modify: `frontend/src/router/index.ts` — 新增 /fetch 路由

**Interfaces:**
- Consumes: API 端点 `/fetch/history`, `/fetch/history/{id}` (Task 4)
- Produces: `FetchRecord`, `FetchHistoryResponse` 类型; `fetchApi` 客户端; `/fetch` 路由

- [ ] **Step 1: 在 `frontend/src/api/types.ts` 末尾添加新类型**

在文件末尾追加：

```typescript

// ══════════════════════════════════════════════════════════════
//  Fetch History
// ══════════════════════════════════════════════════════════════

export interface SkippedPaper {
  id: string
  title: string
}

export interface FetchRecord {
  id: number
  query_text: string
  max_results: number
  total_found: number
  fetched: number
  skipped: number
  download_success: number
  download_failed: number
  parse_success: number
  parse_failed: number
  ingested: number
  skipped_papers: SkippedPaper[]
  owner_id: string
  created_at: string
}

export interface FetchHistoryResponse {
  records: FetchRecord[]
  total: number
}
```

- [ ] **Step 2: 在 `frontend/src/api/client.ts` 末尾（`exportApi` 之后）添加 fetchApi**

在文件最后的 `exportApi` 块之后添加：

```typescript

// ══════════════════════════════════════════════════════════════
//  Fetch History
// ══════════════════════════════════════════════════════════════

export const fetchApi = {
  history: (ownerId: string, limit = 20, offset = 0) =>
    get('/fetch/history', ownerId, { limit, offset }).then(r => json<import('./types').FetchHistoryResponse>(r)),

  historyDetail: (ownerId: string, id: number) =>
    get(`/fetch/history/${id}`, ownerId).then(r => json<import('./types').FetchRecord>(r)),
}
```

- [ ] **Step 3: 在 `frontend/src/router/index.ts` 的 routes 数组中添加 `/fetch` 路由**

在 `routes` 数组中，`/library` 路由之前插入（保持侧边栏顺序）：

```typescript
    {
      path: '/fetch',
      name: 'fetch',
      component: () => import('@/components/pages/FetchPage.vue'),
      meta: { title: '论文抓取' },
    },
```

- [ ] **Step 4: 验证 — 前端编译检查**

Run: `cd d:/git/paper-assistant/frontend && npx vue-tsc --noEmit 2>&1 | head -20`

Expected: 无类型错误（可能有预先存在的 warning，确认无新增 ERROR）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/router/index.ts
git commit -m "feat: add frontend fetch history types, API client, and route

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 前端 — Sidebar 导航项

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.vue` — 新增 nav item

**Interfaces:**
- Consumes: 路由 `/fetch` (Task 5)
- Produces: 侧边栏「论文抓取」入口

- [ ] **Step 1: 在 `navItems` 数组中添加「论文抓取」项**

在 [Sidebar.vue](frontend/src/components/layout/Sidebar.vue) 的 `navItems` 数组（约第 21-30 行），在 `library` 之前插入 `fetch`：

```typescript
const navItems: NavItem[] = [
  { key: 'qa', label: '智能问答', icon: '' },
  { key: 'agent', label: '智能分析', icon: '' },
  { key: 'fetch', label: '论文抓取', icon: '' },
  { key: 'library', label: '论文库', icon: '' },
  { key: 'summary', label: '摘要 & 综述', icon: '' },
  { key: 'citations', label: '引用关系', icon: '' },
  { key: 'data', label: '数据管理', icon: '' },
  { key: 'system', label: '系统设置', icon: '' },
  { key: 'help', label: '帮助', icon: '' },
]
```

- [ ] **Step 2: 验证 — 前端编译**

Run: `cd d:/git/paper-assistant/frontend && npx vue-tsc --noEmit 2>&1 | head -10`

Expected: 无新增类型错误。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/layout/Sidebar.vue
git commit -m "feat: add fetch center nav item to sidebar

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: FetchPage.vue — 抓取中心页面

**Files:**
- Create: `frontend/src/components/pages/FetchPage.vue`

**Interfaces:**
- Consumes: `arxivApi`, `fetchApi` from `@/api/client`; `useAuthStore`; `useToastStore`
- Produces: 完整的抓取中心 UI — 表单、本次结果、历史列表

- [ ] **Step 1: 创建 `frontend/src/components/pages/FetchPage.vue`**

```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { arxivApi, fetchApi } from '@/api/client'
import type { FetchRecord, SkippedPaper } from '@/api/types'
import Pagination from '@/components/common/Pagination.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useToastStore } from '@/stores/toast'

const auth = useAuthStore()
const toast = useToastStore()

// ── 抓取表单 ──
const fetchQuery = ref('cat:cs.AI AND ti:learning')
const fetchN = ref(5)
const fetching = ref(false)

// ── 本次结果 ──
const lastResult = ref<{
  total_found: number
  fetched: number
  skipped: number
  failed: number
  skipped_papers: SkippedPaper[]
} | null>(null)
const showSkipped = ref(true)

// ── 历史 ──
const history = ref<FetchRecord[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyLimit = 20
const historyTotalPages = ref(1)
const loadingHistory = ref(false)

// ── 历史详情展开 ──
const expandedId = ref<number | null>(null)

async function doFetch() {
  fetching.value = true
  lastResult.value = null
  try {
    const result = await arxivApi.pipeline(auth.ownerId, fetchQuery.value, fetchN.value)

    // 解析各步骤数据
    let totalFound = fetchN.value
    let fetched = 0
    let skipped = 0
    let failed = 0
    let skippedPapers: SkippedPaper[] = []

    for (const step of result.steps) {
      if (step.step === 'fetch') {
        totalFound = step.count ?? 0
      } else if (step.step === 'download') {
        failed += step.failed ?? 0
      } else if (step.step === 'ingest') {
        const ingested = step.papers ?? 0
        // fetched = ingested + non-ingested new papers that were saved
        // simplified: use total pipeline info
      }
    }

    // 后端返回的 steps 已包含 fetch 统计
    // 重新获取本次历史记录来展示完整信息
    const hResp = await fetchApi.history(auth.ownerId, 1, 0)
    if (hResp.records.length > 0) {
      const latest = hResp.records[0]
      lastResult.value = {
        total_found: latest.total_found,
        fetched: latest.fetched,
        skipped: latest.skipped,
        failed: latest.download_failed + latest.parse_failed,
        skipped_papers: latest.skipped_papers,
      }
    } else {
      // fallback: 从步骤估算
      const fetchStep = result.steps.find(s => s.step === 'fetch')
      const dlStep = result.steps.find(s => s.step === 'download')
      lastResult.value = {
        total_found: fetchStep?.count ?? 0,
        fetched: fetchStep?.count ?? 0,
        skipped: 0,
        failed: dlStep?.failed ?? 0,
        skipped_papers: [],
      }
    }

    for (const step of result.steps) {
      const labels: Record<string, string> = { fetch: '搜索', download: '下载', parse: '解析', ingest: '入库' }
      const label = labels[step.step] || step.step
      if (step.step === 'fetch') toast.info(`${label}: 找到 ${step.count} 篇`)
      else if (step.step === 'download') toast.info(`${label}: 成功 ${step.success} 篇${step.failed ? `, 失败 ${step.failed} 篇` : ''}`)
      else if (step.step === 'ingest') toast.success(`${label}: ${step.papers} 篇 / ${step.chunks} chunks`)
    }

    await loadHistory()
    toast.success('管道完成！同名论文自动去重。')
  } catch (e) {
    toast.error('arXiv 抓取失败：' + (e instanceof Error ? e.message : '未知错误'))
  } finally {
    fetching.value = false
  }
}

async function loadHistory() {
  loadingHistory.value = true
  try {
    const resp = await fetchApi.history(auth.ownerId, historyLimit, (historyPage.value - 1) * historyLimit)
    history.value = resp.records
    historyTotal.value = resp.total
    historyTotalPages.value = Math.max(1, Math.ceil(resp.total / historyLimit))
  } catch (e) {
    console.error('Failed to load fetch history:', e)
  } finally {
    loadingHistory.value = false
  }
}

function toggleExpand(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}

function changeHistoryPage(p: number) {
  historyPage.value = p
  loadHistory()
}

function formatTime(iso: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso + 'Z')
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    const hh = String(d.getHours()).padStart(2, '0')
    const mi = String(d.getMinutes()).padStart(2, '0')
    return `${mm}-${dd} ${hh}:${mi}`
  } catch {
    return iso.slice(0, 16)
  }
}

function truncateQuery(q: string): string {
  return q.length > 30 ? q.slice(0, 28) + '…' : q
}

onMounted(() => {
  loadHistory()
})
</script>

<template>
  <div class="fetch-page">
    <h2>论文抓取</h2>
    <p class="page-desc">从 arXiv 搜索并抓取论文，查看抓取历史与去重结果。</p>

    <!-- 抓取表单 -->
    <section class="section-card">
      <h3 class="section-title">📥 抓取论文</h3>
      <div class="fetch-form">
        <div class="form-group">
          <label class="form-label">查询语法</label>
          <input
            v-model="fetchQuery"
            class="form-input"
            placeholder="arXiv 查询语法，如 cat:cs.AI AND ti:learning"
          />
        </div>
        <div class="form-group" style="max-width:120px">
          <label class="form-label">最大篇数</label>
          <input
            v-model.number="fetchN"
            class="form-input"
            type="number"
            min="1"
            max="50"
          />
        </div>
        <button
          class="btn-primary fetch-btn"
          :disabled="fetching"
          @click="doFetch"
        >
          {{ fetching ? '抓取中…' : '一键抓取' }}
        </button>
      </div>
    </section>

    <!-- 本次结果 -->
    <section v-if="lastResult" class="section-card result-section">
      <h3 class="section-title">📊 本次抓取结果</h3>
      <div class="stat-row">
        <div class="stat-item">
          <span class="stat-num">{{ lastResult.total_found }}</span>
          <span class="stat-label">找到</span>
        </div>
        <div class="stat-item stat-success">
          <span class="stat-num">{{ lastResult.fetched }}</span>
          <span class="stat-label">成功入库</span>
        </div>
        <div class="stat-item stat-skipped">
          <span class="stat-num">{{ lastResult.skipped }}</span>
          <span class="stat-label">跳过(已入库)</span>
        </div>
        <div class="stat-item stat-failed">
          <span class="stat-num">{{ lastResult.failed }}</span>
          <span class="stat-label">失败</span>
        </div>
      </div>

      <!-- 跳过论文列表 -->
      <div v-if="lastResult.skipped_papers.length > 0" class="skipped-list">
        <button class="skipped-toggle" @click="showSkipped = !showSkipped">
          {{ showSkipped ? '▼' : '▶' }} 跳过论文（{{ lastResult.skipped_papers.length }} 篇，因已入库）
        </button>
        <div v-if="showSkipped" class="skipped-items">
          <div v-for="sp in lastResult.skipped_papers" :key="sp.id" class="skipped-item">
            <span class="skipped-id">{{ sp.id }}</span>
            <span class="skipped-title">{{ sp.title }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 历史记录 -->
    <section class="section-card">
      <h3 class="section-title">📜 抓取历史</h3>
      <div v-if="loadingHistory" class="loading">加载中…</div>
      <EmptyState v-else-if="!history.length" title="暂无抓取记录" description="发起一次抓取后这里会显示历史记录" />

      <div v-else>
        <div class="history-table-wrap">
          <table class="history-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>查询</th>
                <th>最大</th>
                <th>找到</th>
                <th>成功</th>
                <th>跳过</th>
                <th>失败</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="r in history" :key="r.id">
                <tr class="history-row" :class="{ expanded: expandedId === r.id }" @click="toggleExpand(r.id)">
                  <td class="col-time">{{ formatTime(r.created_at) }}</td>
                  <td class="col-query" :title="r.query_text">{{ truncateQuery(r.query_text) }}</td>
                  <td class="col-num">{{ r.max_results }}</td>
                  <td class="col-num">{{ r.total_found }}</td>
                  <td class="col-num col-green">{{ r.fetched }}</td>
                  <td class="col-num col-yellow">{{ r.skipped }}</td>
                  <td class="col-num col-red">{{ r.download_failed + r.parse_failed }}</td>
                </tr>
                <!-- 展开详情 -->
                <tr v-if="expandedId === r.id" class="expand-row">
                  <td colspan="7">
                    <div class="expand-detail">
                      <div class="detail-stats">
                        <span>下载成功: <strong>{{ r.download_success }}</strong></span>
                        <span>下载失败: <strong>{{ r.download_failed }}</strong></span>
                        <span>解析成功: <strong>{{ r.parse_success }}</strong></span>
                        <span>解析失败: <strong>{{ r.parse_failed }}</strong></span>
                        <span>入库: <strong>{{ r.ingested }}</strong></span>
                      </div>
                      <div v-if="r.skipped_papers.length > 0" class="detail-skipped">
                        <div class="detail-label">跳过论文:</div>
                        <div v-for="sp in r.skipped_papers" :key="sp.id" class="skipped-item">
                          <span class="skipped-id">{{ sp.id }}</span>
                          <span class="skipped-title">{{ sp.title }}</span>
                        </div>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <Pagination
          :page="historyPage"
          :total-pages="historyTotalPages"
          :total="historyTotal"
          @change="changeHistoryPage"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.fetch-page { max-width: 1100px; }
.page-desc { font-size: 14px; color: var(--color-body); margin-bottom: 24px; }

.section-card {
  background: var(--color-canvas);
  border: 1px solid var(--color-hairline);
  border-radius: var(--radius-md);
  padding: 20px 24px;
  margin-bottom: 20px;
}
.section-title {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 16px 0;
  color: var(--color-ink);
}

/* ── 表单 ── */
.fetch-form { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
.form-group { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 160px; }
.form-label { font-size: 12px; color: var(--color-mute); }
.fetch-btn { margin-top: auto; white-space: nowrap; }

/* ── 统计卡片 ── */
.stat-row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.stat-item {
  flex: 1; min-width: 100px;
  padding: 16px;
  background: var(--color-canvas-soft);
  border-radius: var(--radius-sm);
  text-align: center;
}
.stat-item.stat-success { background: #dcfce7; }
.stat-item.stat-skipped { background: #fef3c7; }
.stat-item.stat-failed { background: #fee2e2; }
.stat-num { display: block; font-size: 28px; font-weight: 700; color: var(--color-ink); }
.stat-label { font-size: 13px; color: var(--color-mute); margin-top: 4px; }

/* ── 跳过论文 ── */
.skipped-list { margin-top: 8px; }
.skipped-toggle {
  background: none; border: none;
  font-size: 13px; color: var(--color-body); cursor: pointer;
  padding: 4px 0;
}
.skipped-toggle:hover { color: var(--color-ink); }
.skipped-items { margin-top: 8px; }
.skipped-item {
  display: flex; gap: 12px; align-items: baseline;
  padding: 6px 0;
  border-bottom: 1px solid var(--color-hairline);
  font-size: 13px;
}
.skipped-item:last-child { border-bottom: none; }
.skipped-id {
  font-family: monospace;
  color: var(--color-primary);
  white-space: nowrap;
  min-width: 100px;
}
.skipped-title { color: var(--color-body); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── 历史表格 ── */
.history-table-wrap { overflow-x: auto; }
.history-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.history-table th {
  text-align: left; padding: 8px 10px; font-weight: 600;
  color: var(--color-mute); border-bottom: 2px solid var(--color-hairline);
  white-space: nowrap;
}
.history-table td { padding: 8px 10px; border-bottom: 1px solid var(--color-hairline); }
.history-row { cursor: pointer; transition: background 0.1s; }
.history-row:hover { background: var(--color-canvas-soft); }
.history-row.expanded { background: var(--color-canvas-soft); }
.col-time { white-space: nowrap; font-size: 12px; color: var(--color-mute); }
.col-query { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.col-num { text-align: center; width: 50px; }
.col-green { color: #16a34a; font-weight: 600; }
.col-yellow { color: #ca8a04; font-weight: 600; }
.col-red { color: #dc2626; font-weight: 600; }

/* ── 展开详情 ── */
.expand-row td { padding: 0; }
.expand-detail {
  padding: 16px 24px;
  background: var(--color-canvas-soft);
  border-top: 1px solid var(--color-hairline);
}
.detail-stats {
  display: flex; gap: 20px; flex-wrap: wrap;
  font-size: 13px; color: var(--color-body); margin-bottom: 12px;
}
.detail-label { font-size: 13px; font-weight: 600; color: var(--color-ink); margin-bottom: 4px; }
.detail-skipped { margin-top: 8px; }

.loading { text-align: center; padding: 32px 0; color: var(--color-mute); }
</style>
```

- [ ] **Step 2: 验证 — 前端编译**

Run: `cd d:/git/paper-assistant/frontend && npx vue-tsc --noEmit 2>&1 | head -20`

Expected: 无新增类型错误。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/pages/FetchPage.vue
git commit -m "feat: add FetchPage — arXiv fetch center with history and dedup transparency

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: LibraryPage 清理 — 移除 arXiv 抓取 UI

**Files:**
- Modify: `frontend/src/components/pages/LibraryPage.vue` — 移除 fetch 相关代码

**Interfaces:**
- None (纯移除操作，不产生新接口)

- [ ] **Step 1: 移除 LibraryPage.vue 中与 arXiv 抓取相关的代码**

在 [LibraryPage.vue](frontend/src/components/pages/LibraryPage.vue) 中执行以下编辑：

**a) 移除 import：** 第 4 行删除 `arxivApi`：

```typescript
import { papersApi, arxivApi, storeApi } from '@/api/client'
```
改为：
```typescript
import { papersApi, storeApi } from '@/api/client'
```

**b) 移除变量声明（约第 30-31 行）：** 删除：

```typescript
const fetchQuery = ref('cat:cs.AI AND ti:learning')
const fetchN = ref(5)
const fetching = ref(false)
```

**c) 移除 `doFetch` 函数（约第 78-97 行）：** 删除整个 `async function doFetch() { ... }` 函数块。

**d) 移除模板中 arXiv 抓取的 `<details>` 面板（约第 144-155 行）：**

```html
      <div class="arxiv-section">
        <details>
          <summary>从 arXiv 抓取论文</summary>
          <div class="arxiv-form">
            <input v-model="fetchQuery" class="form-input" placeholder="arXiv 查询语法" />
            <input v-model.number="fetchN" class="form-input" type="number" min="1" max="50" style="width:80px" />
            <button class="btn-primary" :disabled="fetching" @click="doFetch">
              {{ fetching ? '抓取中…' : '一键抓取' }}
            </button>
          </div>
        </details>
      </div>
```

替换为一个指向抓取中心的快捷链接：

```html
      <router-link to="/fetch" class="btn-secondary" style="text-decoration:none">前往论文抓取 →</router-link>
```

需要在 `<script setup>` 中无需额外 import（`<router-link>` 是 Vue Router 全局组件）。

**e) 移除 `<style scoped>` 中的 `.arxiv-form` 样式（约第 212 行）：** 删除：

```css
.arxiv-form { display: flex; gap: 8px; margin-top: 12px; align-items: center; }
```

- [ ] **Step 2: 验证 — 前端编译**

Run: `cd d:/git/paper-assistant/frontend && npx vue-tsc --noEmit 2>&1 | head -20`

Expected: 无新增类型错误（特别检查 `arxivApi` 不再被引用）。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/pages/LibraryPage.vue
git commit -m "refactor: remove arXiv fetch UI from LibraryPage, link to fetch center

Co-Authored-By: Claude <noreply@anthropic.com>"
```
