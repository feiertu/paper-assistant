"""测试 compare_papers 函数。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def sample_parsed_dir():
    """创建临时 parsed JSON 文件。"""
    import config
    original = config.PARSED_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # 覆盖 PARSED_DIR 指向测试目录
        import config as cfg
        cfg.PARSED_DIR = tmp
        yield tmp
        cfg.PARSED_DIR = original


class TestComparePapers:
    def test_compare_basic(self, monkeypatch):
        """基础对比：两个有效论文。"""
        import shutil
        from unittest.mock import patch
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        monkeypatch.setattr("config.PARSED_DIR", tmp)

        paper1 = {"metadata": {"title": "P1"}, "sections": [
            {"title": "Abstract", "content": "This is paper 1 about RL.", "subsections": []}
        ]}
        paper2 = {"metadata": {"title": "P2"}, "sections": [
            {"title": "Abstract", "content": "This is paper 2 about RL.", "subsections": []}
        ]}
        (tmp / "test.1v1.json").write_text(json.dumps(paper1))
        (tmp / "test.2v1.json").write_text(json.dumps(paper2))

        # Patch at the import location used by compare.py
        mock_llm = type("MockLLM", (), {
            "chat": lambda self, messages, model=None: "对比结果：两篇论文都关于强化学习。"
        })()
        monkeypatch.setattr("src.llm.client._llm", mock_llm)

        from src.agent.compare import compare_papers
        result = compare_papers("test.1v1", "test.2v1")
        assert "对比" in result
        shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_paper(self, monkeypatch):
        """论文缺失返回错误信息。"""
        import shutil
        tmp = Path(tempfile.mkdtemp())
        monkeypatch.setattr("config.PARSED_DIR", tmp)

        from src.agent.compare import compare_papers
        result = compare_papers("missing.1", "missing.2")
        assert "⚠️" in result or "失败" in result
        shutil.rmtree(tmp, ignore_errors=True)


class TestCompareTool:
    def test_tool_wrapper(self, monkeypatch):
        """工具包装层正确调用 compare_papers。"""
        import shutil
        tmp = Path(tempfile.mkdtemp())
        monkeypatch.setattr("config.PARSED_DIR", tmp)

        p = {"metadata": {}, "sections": [{"title": "X", "content": "text", "subsections": []}]}
        (tmp / "a.1.json").write_text(json.dumps(p))
        (tmp / "b.1.json").write_text(json.dumps(p))

        mock_llm = type("MockLLM", (), {
            "chat": lambda self, messages, model=None: "对比完成。"
        })()
        monkeypatch.setattr("src.llm.client._llm", mock_llm)

        from src.agent.tools import compare_papers as compare_tool
        result = compare_tool.func("a.1", "b.1")
        assert isinstance(result, str)
        assert "对比" in result
        shutil.rmtree(tmp, ignore_errors=True)
