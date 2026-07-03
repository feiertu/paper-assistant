"""测试 Agent 工具定义。"""

from __future__ import annotations

import pytest


class TestToolsExist:
    def test_all_tools_defined(self):
        from src.agent.tools import ALL_TOOLS
        assert len(ALL_TOOLS) == 7

    def test_tool_names(self):
        from src.agent.tools import ALL_TOOLS
        names = {t.name for t in ALL_TOOLS}
        assert names == {
            "search", "get_paper", "summarize_paper",
            "get_citations", "compare_papers", "recommend_similar",
            "generate_survey",
        }

    def test_tool_by_name(self):
        from src.agent.tools import TOOL_BY_NAME, get_tool_by_name
        assert get_tool_by_name("search") is not None
        assert get_tool_by_name("get_paper") is not None
        assert get_tool_by_name("nonexistent") is None

    def test_openai_format(self):
        from src.agent.tools import get_tools_openai_format
        tools = get_tools_openai_format()
        assert len(tools) == 7
        assert all(t["type"] == "function" for t in tools)
        assert all("name" in t["function"] for t in tools)

    def test_openai_format_filtered(self):
        from src.agent.tools import get_tools_openai_format
        tools = get_tools_openai_format(["search", "get_paper"])
        assert len(tools) == 2


class TestSearchTool:
    def test_search_fts(self):
        """FTS 搜索返回结果。"""
        from src.agent.tools import search
        result = search.func(query="test", mode="fts", top_k=3)
        assert isinstance(result, str)

    def test_search_semantic(self):
        """语义搜索处理空向量库。"""
        from src.agent.tools import search
        result = search.func(query="deep learning", mode="semantic", top_k=3)
        assert isinstance(result, str)

    def test_search_list(self):
        """列表模式返回结果。"""
        from src.agent.tools import search
        result = search.func(query="", mode="list", top_k=10)
        assert isinstance(result, str)


class TestGetPaperTool:
    def test_get_missing(self):
        from src.agent.tools import get_paper
        result = get_paper.func("nonexistent.99999")
        assert "未找到" in result or "失败" in result


class TestRecommendTool:
    def test_recommend_empty_store(self):
        from src.agent.tools import recommend_similar
        result = recommend_similar.func("nonexistent.99999")
        assert isinstance(result, str)
