"""DAO 层 — 基于第 19 章 DAO 模式。

设计原则（§19.5）：
  - 接口定义操作 → 工厂创建实例 → 具体实现
  - 上层不关心底层用什么数据库（SQLite 可随时换 PostgreSQL）
  - 符合 DIP（依赖抽象而非具体）

每个 DAO 对应一个实体表，提供:
  - insert / update / delete / findById / findAll
"""

from __future__ import annotations

from typing import Dict, List, Optional

import config  # noqa: F401 — 确保数据目录已创建
from src.logging_config import get_logger

from .schema import Collection, Paper, QueryRecord, get_connection

logger = get_logger(__name__)


# ══════════════════════════════════════════════
#  PaperDAO — 论文元数据访问
# ══════════════════════════════════════════════

class PaperDAO:
    """论文 DAO（§19.5：数据访问对象）。"""

    def insert(self, paper: Paper) -> int:
        """插入论文，返回自增 ID。存在则更新并返回已有 ID。"""
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM papers WHERE arxiv_id = ?", (paper.arxiv_id,)
            ).fetchone()
            if existing:
                # 更新已有记录
                conn.execute(
                    """UPDATE papers SET title=?, authors=?, abstract=?, published=?,
                       pdf_url=?, source=?, ingest_status=?, chunk_count=?
                       WHERE arxiv_id=?""",
                    (
                        paper.title, paper.authors, paper.abstract, paper.published,
                        paper.pdf_url, paper.source, paper.ingest_status, paper.chunk_count,
                        paper.arxiv_id,
                    ),
                )
                conn.commit()
                return existing["id"]
            cur = conn.execute(
                """INSERT INTO papers (arxiv_id, title, authors, abstract, published,
                   pdf_url, source, ingest_status, chunk_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    paper.arxiv_id, paper.title, paper.authors, paper.abstract,
                    paper.published, paper.pdf_url, paper.source,
                    paper.ingest_status, paper.chunk_count,
                ),
            )
            conn.commit()
            return cur.lastrowid

    def find_by_id(self, paper_id: int) -> Optional[Paper]:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
            return Paper.from_row(row) if row else None

    def find_by_arxiv_id(self, arxiv_id: str) -> Optional[Paper]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE arxiv_id = ?", (arxiv_id,)
            ).fetchone()
            return Paper.from_row(row) if row else None

    def find_all(self, limit: int = 50, offset: int = 0) -> List[Paper]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM papers ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [Paper.from_row(r) for r in rows]

    def find_ingested(self) -> List[Paper]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM papers WHERE ingest_status = 'ingested' ORDER BY created_at DESC"
            ).fetchall()
            return [Paper.from_row(r) for r in rows]

    def count(self) -> int:
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

    def update_status(self, arxiv_id: str, status: str, chunk_count: int = 0) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE papers SET ingest_status=?, chunk_count=? WHERE arxiv_id=?",
                (status, chunk_count, arxiv_id),
            )
            conn.commit()

    def delete(self, arxiv_id: str) -> bool:
        with get_connection() as conn:
            cur = conn.execute("DELETE FROM papers WHERE arxiv_id = ?", (arxiv_id,))
            conn.commit()
            return cur.rowcount > 0


# ══════════════════════════════════════════════
#  QueryDAO — 查询历史访问
# ══════════════════════════════════════════════

class QueryDAO:
    """查询历史 DAO。"""

    def insert(self, record: QueryRecord) -> int:
        with get_connection() as conn:
            cur = conn.execute(
                """INSERT INTO queries (query_text, answer_text, lang, hit_count)
                   VALUES (?, ?, ?, ?)""",
                (record.query_text, record.answer_text, record.lang, record.hit_count),
            )
            conn.commit()
            return cur.lastrowid

    def find_recent(self, limit: int = 20) -> List[QueryRecord]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM queries ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [QueryRecord.from_row(r) for r in rows]

    def search(self, keyword: str, limit: int = 20) -> List[QueryRecord]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM queries WHERE query_text LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{keyword}%", limit),
            ).fetchall()
            return [QueryRecord.from_row(r) for r in rows]

    def clear(self) -> None:
        with get_connection() as conn:
            conn.execute("DELETE FROM queries")
            conn.commit()

    def count(self) -> int:
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]

    # ── N:M 关系操作（§19.3：中间表） ──

    def link_paper(self, query_id: int, paper_id: int) -> None:
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO query_papers (query_id, paper_id) VALUES (?, ?)",
                (query_id, paper_id),
            )
            conn.commit()

    def get_linked_papers(self, query_id: int) -> List[int]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT paper_id FROM query_papers WHERE query_id = ?", (query_id,)
            ).fetchall()
            return [r["paper_id"] for r in rows]


# ══════════════════════════════════════════════
#  CollectionDAO — 收藏夹访问
# ══════════════════════════════════════════════

class CollectionDAO:
    """收藏夹 DAO（含 N:M 中间表操作，§19.3）。"""

    def create(self, name: str, description: str = "") -> int:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO collections (name, description) VALUES (?, ?)",
                (name, description),
            )
            conn.commit()
            return cur.lastrowid

    def find_all(self, limit: int = 100, offset: int = 0) -> List[Collection]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM collections ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [Collection.from_row(r) for r in rows]

    def count(self) -> int:
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0]

    def delete(self, collection_id: int) -> bool:
        with get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM collections WHERE id = ?", (collection_id,)
            )
            conn.commit()
            return cur.rowcount > 0

    # ── N:M 映射（§19.3：中间表 collection_papers） ──

    def add_paper(self, collection_id: int, paper_id: int) -> None:
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO collection_papers (collection_id, paper_id) VALUES (?, ?)",
                (collection_id, paper_id),
            )
            conn.execute(
                "UPDATE collections SET paper_count = (SELECT COUNT(*) FROM collection_papers WHERE collection_id = ?) WHERE id = ?",
                (collection_id, collection_id),
            )
            conn.commit()

    def remove_paper(self, collection_id: int, paper_id: int) -> None:
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM collection_papers WHERE collection_id = ? AND paper_id = ?",
                (collection_id, paper_id),
            )
            conn.execute(
                "UPDATE collections SET paper_count = (SELECT COUNT(*) FROM collection_papers WHERE collection_id = ?) WHERE id = ?",
                (collection_id, collection_id),
            )
            conn.commit()

    def list_papers(self, collection_id: int) -> List[Paper]:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT p.* FROM papers p
                   JOIN collection_papers cp ON p.id = cp.paper_id
                   WHERE cp.collection_id = ?
                   ORDER BY p.created_at DESC""",
                (collection_id,),
            ).fetchall()
            return [Paper.from_row(r) for r in rows]


# ── DAO 工厂（§19.5：通过工厂类解耦） ──

_daos: Optional[Dict[str, object]] = None


def get_dao(name: str):
    """DAO 工厂：按名称获取 DAO 单例。

    用法：
        paper_dao = get_dao("paper")
        papers = paper_dao.find_all()
    """
    global _daos
    if _daos is None:
        _daos = {
            "paper": PaperDAO(),
            "query": QueryDAO(),
            "collection": CollectionDAO(),
            "citation": CitationDAO(),
        }
    dao = _daos.get(name)
    if dao is None:
        raise ValueError(f"未知 DAO: {name!r}，可选: paper / query / collection / citation")
    return dao


# ══════════════════════════════════════════════
#  CitationDAO — 引用关系访问
# ══════════════════════════════════════════════

class CitationDAO:
    """引用关系 DAO。"""

    def insert(self, citing_arxiv_id: str, cited_arxiv_id: str,
               cited_title: str = "", context: str = "") -> bool:
        """添加引用关系（幂等：已存在则忽略）。"""
        with get_connection() as conn:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO citations
                       (citing_arxiv_id, cited_arxiv_id, cited_title, context)
                       VALUES (?, ?, ?, ?)""",
                    (citing_arxiv_id, cited_arxiv_id, cited_title, context),
                )
                conn.commit()
                return True
            except Exception:
                logger.warning("引用插入失败: %s → %s", citing_arxiv_id, cited_arxiv_id)
                return False

    def batch_insert(self, rows: list) -> int:
        """批量插入引用关系 [(citing_id, cited_id, title, context), ...]"""
        with get_connection() as conn:
            count = 0
            for citing_arxiv_id, cited_arxiv_id, cited_title, context in rows:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO citations
                           (citing_arxiv_id, cited_arxiv_id, cited_title, context)
                           VALUES (?, ?, ?, ?)""",
                        (citing_arxiv_id, cited_arxiv_id, cited_title, context),
                    )
                    count += 1
                except Exception:
                    logger.warning("批量引用插入跳过: %s → %s", citing_arxiv_id, cited_arxiv_id)
                    pass
            conn.commit()
            return count

    def find_citations_from(self, arxiv_id: str) -> List[Dict]:
        """查找某论文引用了哪些论文（outgoing）。"""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT c.*, p.title as paper_title
                   FROM citations c
                   LEFT JOIN papers p ON c.cited_arxiv_id = p.arxiv_id
                   WHERE c.citing_arxiv_id = ?
                   ORDER BY c.id""",
                (arxiv_id,),
            ).fetchall()
            return [{
                "cited_arxiv_id": r["cited_arxiv_id"],
                "cited_title": r["cited_title"] or r["paper_title"] or "",
                "context": r["context"] or "",
                "in_db": bool(r["paper_title"]),
            } for r in rows]

    def find_citations_to(self, arxiv_id: str) -> List[Dict]:
        """查找哪些论文引用了这篇（incoming）。"""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT c.*, p.title as paper_title
                   FROM citations c
                   LEFT JOIN papers p ON c.citing_arxiv_id = p.arxiv_id
                   WHERE c.cited_arxiv_id = ?
                   ORDER BY c.id""",
                (arxiv_id,),
            ).fetchall()
            return [{
                "citing_arxiv_id": r["citing_arxiv_id"],
                "citing_title": r["paper_title"] or r["citing_arxiv_id"],
                "context": r["context"] or "",
                "in_db": bool(r["paper_title"]),
            } for r in rows]

    def get_graph(self, arxiv_id: str) -> Dict:
        """获取完整引用图（citing + cited）。"""
        return {
            "arxiv_id": arxiv_id,
            "cites": self.find_citations_from(arxiv_id),
            "cited_by": self.find_citations_to(arxiv_id),
        }

    def count(self) -> int:
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0]

    def clear(self) -> None:
        with get_connection() as conn:
            conn.execute("DELETE FROM citations")
            conn.commit()


# ══════════════════════════════════════════════
#  PaperDAO 扩展：全文搜索
# ══════════════════════════════════════════════

def _extend_paper_dao():
    """给 PaperDAO 动态添加 FTS 搜索方法（不改原类避免冲突）。"""
    def search(self, keyword: str, limit: int = 50,
               arxiv_id: str = "", author: str = "",
               year_from: str = "", year_to: str = "",
               source: str = "", status: str = "",
               sort_by: str = "created_at") -> List:
        """全文搜索 + 多条件过滤。

        Args:
            keyword: FTS5 搜索关键词
            limit: 最大返回数
            arxiv_id: arXiv ID 模糊匹配
            author: 作者名模糊匹配
            year_from / year_to: 年份范围
            source: 来源过滤 (arxiv / grobid / pymupdf / manual)
            status: 状态过滤 (pending / ingested / failed)
            sort_by: 排序字段 (created_at / title / published)
        """
        conditions = []
        params: list = []

        if keyword and keyword.strip():
            conditions.append("p.id IN (SELECT rowid FROM papers_fts WHERE papers_fts MATCH ?)")
            params.append(keyword.strip())

        if arxiv_id:
            conditions.append("p.arxiv_id LIKE ?")
            params.append(f"%{arxiv_id}%")

        if author:
            conditions.append("p.authors LIKE ?")
            params.append(f"%{author}%")

        if year_from:
            conditions.append("p.published >= ?")
            params.append(year_from)

        if year_to:
            conditions.append("p.published <= ?")
            params.append(year_to + "-12-31")

        if source:
            conditions.append("p.source = ?")
            params.append(source)

        if status:
            conditions.append("p.ingest_status = ?")
            params.append(status)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""

        allowed_sort = {"created_at": "p.created_at DESC", "title": "p.title ASC",
                        "published": "p.published DESC"}
        order = allowed_sort.get(sort_by, "p.created_at DESC")

        with get_connection() as conn:
            sql = f"SELECT p.* FROM papers p {where} ORDER BY {order} LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [Paper.from_row(r) for r in rows]

    PaperDAO.search = search


_extend_paper_dao()
