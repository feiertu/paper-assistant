"""测试 AgentMemory 上下文管理。"""

from __future__ import annotations

import pytest


class TestAgentMemory:
    def test_basic_add(self):
        from src.agent.memory import AgentMemory
        mem = AgentMemory(max_tokens=1000)
        mem.add({"role": "system", "content": "You are helpful."})
        mem.add({"role": "user", "content": "Hello"})
        assert len(mem.messages) == 2

    def test_tool_result_truncation(self):
        from src.agent.memory import AgentMemory
        mem = AgentMemory(max_tokens=8000)
        long_content = "x" * 3000
        mem.add({"role": "tool", "content": long_content, "tool_call_id": "1"})
        # 应被截断
        content = mem.messages[0]["content"]
        assert len(content) <= 2100  # 2000 + "…(截断)"

    def test_truncation_keeps_system_user(self):
        from src.agent.memory import AgentMemory
        mem = AgentMemory(max_tokens=100)  # 很小的限制
        mem.add({"role": "system", "content": "S"})
        mem.add({"role": "user", "content": "U"})
        for i in range(30):
            mem.add({"role": "tool", "content": f"result {i}", "tool_call_id": str(i)})
        # system 和 user 应该还在
        assert mem.messages[0]["role"] == "system"
        assert mem.messages[1]["role"] == "user"

    def test_to_openai_messages(self):
        from src.agent.memory import AgentMemory
        mem = AgentMemory()
        mem.add({"role": "system", "content": "S"})
        mem.add({"role": "user", "content": "U"})
        msgs = mem.to_openai_messages()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "S"
