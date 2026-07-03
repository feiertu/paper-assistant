"""数据库 Schema — 基于第 19 章 ER 模型设计。

ER 映射规则（§19.3）：
  - 实体 → 表
  - N:1  → 多方外键
  - N:M  → 中间表（联合主键）

ORM 映射（§19.4）：
  - 类 → 表
  - 属性 → 列
  - 实例 → 行
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import config

# ── 数据库路径 ──

DB_PATH: Path = config.DATA_DIR / "paper_assistant.db"

# ── ORM 数据类（§19.4：类 → 表） ──


@dataclass
class Paper:
    """论文元数据（对应 papers 表）。"""

    arxiv_id: str
    title: str = ""
    authors: str = ""
    abstract: str = ""
    published: str = ""
    pdf_url: str = ""
    source: str = ""  # "arxiv" / "grobid" / "manual"
    ingest_status: str = "pending"  # "pending" | "ingested" | "failed"
    chunk_count: int = 0
    id: Optional[int] = None  # 自增主键，由数据库分配
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "published": self.published,
            "pdf_url": self.pdf_url,
            "source": self.source,
            "ingest_status": self.ingest_status,
            "chunk_count": self.chunk_count,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Paper":
        return cls(
            id=row["id"],
            arxiv_id=row["arxiv_id"],
            title=row["title"] or "",
            authors=row["authors"] or "",
            abstract=row["abstract"] or "",
            published=row["published"] or "",
            pdf_url=row["pdf_url"] or "",
            source=row["source"] or "",
            ingest_status=row["ingest_status"] or "pending",
            chunk_count=row["chunk_count"] or 0,
            created_at=row["created_at"] or "",
        )


@dataclass
class QueryRecord:
    """查询历史（对应 queries 表）。"""

    query_text: str
    answer_text: str = ""
    lang: str = "zh"
    hit_count: int = 0
    id: Optional[int] = None
    created_at: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "QueryRecord":
        return cls(
            id=row["id"],
            query_text=row["query_text"],
            answer_text=row["answer_text"] or "",
            lang=row["lang"] or "zh",
            hit_count=row["hit_count"] or 0,
            created_at=row["created_at"] or "",
        )


@dataclass
class Collection:
    """论文收藏夹（对应 collections 表）。"""

    name: str
    description: str = ""
    paper_count: int = 0
    id: Optional[int] = None
    created_at: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Collection":
        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            paper_count=row["paper_count"] or 0,
            created_at=row["created_at"] or "",
        )


# ── DDL（建表语句） ──

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


# ── 初始化 ──

_initialized = False


def get_connection() -> sqlite3.Connection:
    """获取数据库连接（自动初始化）。"""
    global _initialized
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not _initialized:
        conn.executescript(DDL)
        conn.commit()
        _initialized = True
    return conn


def init_db() -> None:
    """显式初始化数据库（幂等）。"""
    conn = get_connection()
    conn.close()
