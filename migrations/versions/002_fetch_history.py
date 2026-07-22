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
