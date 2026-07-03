"""initial schema

Revision ID: 001
Create Date: 2026-07-03

当前完整 schema：papers, queries, query_papers, collections, collection_papers, citations, papers_fts
"""

revision = "001"
down_revision = None

DDL = """

-- 论文元数据（实体：Paper）
CREATE TABLE IF NOT EXISTS papers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_id    TEXT    NOT NULL UNIQUE,
    title       TEXT    DEFAULT '',
    authors     TEXT    DEFAULT '',
    abstract    TEXT    DEFAULT '',
    published   TEXT    DEFAULT '',
    pdf_url     TEXT    DEFAULT '',
    source      TEXT    DEFAULT '',
    ingest_status TEXT  DEFAULT 'pending',
    chunk_count INTEGER DEFAULT 0,
    created_at  TEXT    DEFAULT (datetime('now', 'localtime'))
);

-- 查询历史（实体：Query）
CREATE TABLE IF NOT EXISTS queries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text  TEXT    NOT NULL,
    answer_text TEXT    DEFAULT '',
    lang        TEXT    DEFAULT 'zh',
    hit_count   INTEGER DEFAULT 0,
    created_at  TEXT    DEFAULT (datetime('now', 'localtime'))
);

-- N:M 关系中间表（§19.3：查询 ↔ 论文）
CREATE TABLE IF NOT EXISTS query_papers (
    query_id    INTEGER NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    paper_id    INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    PRIMARY KEY (query_id, paper_id)
);

-- 收藏夹（实体：Collection）
CREATE TABLE IF NOT EXISTS collections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    description TEXT    DEFAULT '',
    paper_count INTEGER DEFAULT 0,
    created_at  TEXT    DEFAULT (datetime('now', 'localtime'))
);

-- N:M 关系中间表（§19.3：收藏夹 ↔ 论文）
CREATE TABLE IF NOT EXISTS collection_papers (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    paper_id      INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    PRIMARY KEY (collection_id, paper_id)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_papers_arxiv_id ON papers(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_queries_created_at ON queries(created_at);
CREATE INDEX IF NOT EXISTS idx_query_papers_query ON query_papers(query_id);
CREATE INDEX IF NOT EXISTS idx_collection_papers_col ON collection_papers(collection_id);

-- 引用关系（§15：论文 ↔ 论文）
CREATE TABLE IF NOT EXISTS citations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    citing_arxiv_id TEXT    NOT NULL,
    cited_arxiv_id  TEXT    NOT NULL,
    cited_title     TEXT    DEFAULT '',
    context         TEXT    DEFAULT '',   -- 引用处的上下文
    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    UNIQUE(citing_arxiv_id, cited_arxiv_id)
);

CREATE INDEX IF NOT EXISTS idx_citations_citing ON citations(citing_arxiv_id);
CREATE INDEX IF NOT EXISTS idx_citations_cited ON citations(cited_arxiv_id);

-- 全文搜索虚拟表（论文标题 + 摘要 + 作者）
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    title, authors, abstract, content='papers', content_rowid='id'
);

-- FTS 同步触发器
CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
    INSERT INTO papers_fts(rowid, title, authors, abstract)
    VALUES (new.id, new.title, new.authors, new.abstract);
END;

CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, title, authors, abstract)
    VALUES ('delete', old.id, old.title, old.authors, old.abstract);
END;

CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, title, authors, abstract)
    VALUES ('delete', old.id, old.title, old.authors, old.abstract);
    INSERT INTO papers_fts(rowid, title, authors, abstract)
    VALUES (new.id, new.title, new.authors, new.abstract);
END;

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
    for tbl in ["papers_fts", "collection_papers", "query_papers",
                "citations", "collections", "queries", "papers"]:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        except Exception:
            pass
    conn.commit()
    conn.close()
