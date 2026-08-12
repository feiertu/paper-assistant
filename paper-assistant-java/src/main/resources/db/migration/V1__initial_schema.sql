CREATE TABLE IF NOT EXISTS papers (
    id              BIGSERIAL PRIMARY KEY,
    arxiv_id        TEXT NOT NULL UNIQUE,
    title           TEXT DEFAULT '',
    authors         TEXT DEFAULT '',
    abstract        TEXT DEFAULT '',
    published       TEXT DEFAULT '',
    pdf_url         TEXT DEFAULT '',
    source          TEXT DEFAULT '',
    ingest_status   TEXT DEFAULT 'pending',
    chunk_count     INTEGER DEFAULT 0,
    owner_id        TEXT DEFAULT '',
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS queries (
    id              BIGSERIAL PRIMARY KEY,
    query_text      TEXT NOT NULL,
    answer_text     TEXT DEFAULT '',
    lang            TEXT DEFAULT 'zh',
    hit_count       INTEGER DEFAULT 0,
    owner_id        TEXT DEFAULT '',
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS query_papers (
    query_id    BIGINT NOT NULL REFERENCES queries(id) ON DELETE CASCADE,
    paper_id    BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    PRIMARY KEY (query_id, paper_id)
);

CREATE TABLE IF NOT EXISTS collections (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    paper_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS collection_papers (
    collection_id BIGINT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    paper_id      BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    PRIMARY KEY (collection_id, paper_id)
);

CREATE TABLE IF NOT EXISTS citations (
    id              BIGSERIAL PRIMARY KEY,
    citing_arxiv_id TEXT NOT NULL,
    cited_arxiv_id  TEXT NOT NULL,
    cited_title     TEXT DEFAULT '',
    context         TEXT DEFAULT '',
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(citing_arxiv_id, cited_arxiv_id)
);

CREATE TABLE IF NOT EXISTS fetch_history (
    id              BIGSERIAL PRIMARY KEY,
    query_text      TEXT NOT NULL,
    max_results     INTEGER NOT NULL DEFAULT 5,
    total_found     INTEGER DEFAULT 0,
    fetched         INTEGER DEFAULT 0,
    skipped         INTEGER DEFAULT 0,
    download_success INTEGER DEFAULT 0,
    download_failed INTEGER DEFAULT 0,
    parse_success   INTEGER DEFAULT 0,
    parse_failed    INTEGER DEFAULT 0,
    ingested        INTEGER DEFAULT 0,
    skipped_papers  TEXT DEFAULT '[]',
    owner_id        TEXT DEFAULT '',
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_papers_arxiv_id ON papers(arxiv_id);
CREATE INDEX IF NOT EXISTS idx_papers_owner_status ON papers(owner_id, ingest_status);
CREATE INDEX IF NOT EXISTS idx_queries_created_at ON queries(created_at);
CREATE INDEX IF NOT EXISTS idx_citations_citing ON citations(citing_arxiv_id);
CREATE INDEX IF NOT EXISTS idx_citations_cited ON citations(cited_arxiv_id);
CREATE INDEX IF NOT EXISTS idx_fetch_history_owner ON fetch_history(owner_id);
CREATE INDEX IF NOT EXISTS idx_fetch_history_created ON fetch_history(created_at);

-- PostgreSQL full-text search (替代 SQLite FTS5)
ALTER TABLE papers ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(authors, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(abstract, '')), 'C')
    ) STORED;
CREATE INDEX IF NOT EXISTS idx_papers_tsv ON papers USING GIN(tsv);
