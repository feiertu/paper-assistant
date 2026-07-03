"""测试 AgentGuardrails 安全护栏。"""

from __future__ import annotations

import pytest


class TestGuardrails:
    def test_allows_first_call(self):
        from src.agent.guardrails import AgentGuardrails
        g = AgentGuardrails(max_iterations=10, max_same_tool_calls=3)
        reason = g.check("search", {"query": "RL", "mode": "fts"})
        assert reason is None  # 允许

    def test_blocks_repeated_same_call(self):
        from src.agent.guardrails import AgentGuardrails
        g = AgentGuardrails(max_same_tool_calls=2)
        args = {"query": "RL", "mode": "fts"}
        assert g.check("search", args) is None  # 1st: OK
        assert g.check("search", args) is None  # 2nd: OK
        # 3rd with same args: blocked (> max_same_tool_calls=2)
        reason = g.check("search", args)
        assert reason is not None
        assert "阻止" in reason

    def test_allows_different_args(self):
        from src.agent.guardrails import AgentGuardrails
        g = AgentGuardrails(max_same_tool_calls=2)
        assert g.check("search", {"query": "A"}) is None
        assert g.check("search", {"query": "A"}) is None
        # 不同参数，重置计数
        assert g.check("search", {"query": "B"}) is None
        assert g.check("search", {"query": "B"}) is None

    def test_terminates_at_max_iterations(self):
        from src.agent.guardrails import AgentGuardrails
        g = AgentGuardrails(max_iterations=3)
        assert g.should_terminate(0) is None
        assert g.should_terminate(1) is None
        assert g.should_terminate(2) is None
        reason = g.should_terminate(3)
        assert reason is not None
        assert "最大" in reason

    def test_loop_detection(self):
        from src.agent.guardrails import AgentGuardrails
        g = AgentGuardrails()
        # 模拟 A-B-A-B-A-B 循环
        for _ in range(8):
            result = g.check("search", {"q": "x"})
            g.check("get_paper", {"id": "y"})
        # 应检测到循环
        reason = g.check("search", {"q": "x"})
        if reason:
            assert "循环" in reason

    def test_reset(self):
        from src.agent.guardrails import AgentGuardrails
        g = AgentGuardrails(max_same_tool_calls=1)
        g.check("search", {"q": "x"})
        g.reset()
        assert g.check("search", {"q": "x"}) is None  # 重置后可再次调用
