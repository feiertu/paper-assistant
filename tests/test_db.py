"""DB Schema 单元测试。"""

from __future__ import annotations

import pytest


class TestSchema:
    def test_db_init(self):
        """数据库能正常初始化。"""
        from src.db.schema import get_connection, init_db

        init_db()
        conn = get_connection()

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]

        assert "papers" in table_names
        assert "queries" in table_names
        assert "collections" in table_names
        assert "citations" in table_names
        conn.close()

    def test_double_init_idempotent(self):
        """双重初始化幂等。"""
        from src.db.schema import get_connection, init_db
        init_db()
        init_db()
        conn = get_connection()
        assert conn.execute("SELECT COUNT(*) FROM papers").fetchone() is not None
        conn.close()


class TestPaperDAO:
    def test_insert_and_find(self):
        """插入论文并查找。"""
        from src.db.schema import Paper
        from src.db.dao import get_dao

        dao = get_dao("paper")
        paper = Paper(
            arxiv_id="test.12345",
            title="Test Paper",
            authors="Author A, Author B",
            abstract="This is a test abstract.",
            published="2024-01-01",
            source="test",
        )
        pid = dao.insert(paper)
        assert pid > 0

        found = dao.find_by_arxiv_id("test.12345")
        assert found is not None
        assert found.title == "Test Paper"
        assert found.abstract == "This is a test abstract."

    def test_insert_upsert(self):
        """重复插入是 upsert。"""
        from src.db.schema import Paper
        from src.db.dao import get_dao

        dao = get_dao("paper")
        p1 = Paper(arxiv_id="test.67890", title="V1")
        id1 = dao.insert(p1)
        p2 = Paper(arxiv_id="test.67890", title="V2")
        id2 = dao.insert(p2)
        assert id1 == id2

        found = dao.find_by_arxiv_id("test.67890")
        assert found.title == "V2"


class TestQueryDAO:
    def test_insert_and_search(self):
        """插入查询并搜索。"""
        from src.db.schema import QueryRecord
        from src.db.dao import get_dao

        dao = get_dao("query")
        qid = dao.insert(QueryRecord(
            query_text="What is RAG?", answer_text="Retrieval-Augmented Generation",
            lang="en", hit_count=5,
        ))
        assert qid > 0

        results = dao.search("RAG")
        assert len(results) >= 1
        assert results[0].query_text == "What is RAG?"


class TestCollectionDAO:
    def test_create_and_list(self):
        """创建收藏夹并列出。"""
        from src.db.dao import get_dao

        dao = get_dao("collection")
        cid = dao.create("My Papers", "Important papers")
        assert cid > 0

        cols = dao.find_all()
        assert any(c.name == "My Papers" for c in cols)

    def test_add_paper_to_collection(self):
        """添加论文到收藏夹。"""
        from src.db.schema import Paper
        from src.db.dao import get_dao

        paper_dao = get_dao("paper")
        pid = paper_dao.insert(Paper(arxiv_id="test.col.1", title="Collection Paper"))

        col_dao = get_dao("collection")
        cid = col_dao.create("Test Collection")
        col_dao.add_paper(cid, pid)

        papers = col_dao.list_papers(cid)
        assert len(papers) == 1
        assert papers[0].arxiv_id == "test.col.1"
