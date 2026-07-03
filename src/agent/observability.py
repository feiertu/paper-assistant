"""Agent 可观测性 — 链路追踪、token 统计、延迟监控。"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List

from src.logging_config import get_logger

logger = get_logger(__name__)


class AgentTrace:
    """记录单次 Agent 运行的完整链路。

    用法：
        trace = AgentTrace(query_id)
        trace.add_step({"type": "tool_call", "tool": "search", ...})
        trace.add_step({"type": "tool_result", "result": "..."})
        ...
        summary = trace.to_dict()  # 最终上报
    """

    def __init__(self, query_id: str = ""):
        self.query_id = query_id or str(uuid.uuid4())[:8]
        self.start_time = time.time()
        self.steps: List[Dict[str, Any]] = []
        self.total_tokens: int = 0
        self.total_tool_calls: int = 0

    def add_step(self, step: Dict[str, Any]) -> None:
        """记录一个推理步骤。"""
        step["timestamp_ms"] = round((time.time() - self.start_time) * 1000)
        self.steps.append(step)

        if step.get("type") == "tool_call":
            self.total_tool_calls += 1

    def add_tokens(self, tokens: int) -> None:
        """累加 token 用量。"""
        self.total_tokens += tokens

    def to_dict(self) -> Dict[str, Any]:
        """转为可序列化的字典。"""
        duration_ms = round((time.time() - self.start_time) * 1000)
        result = {
            "query_id": self.query_id,
            "duration_ms": duration_ms,
            "total_tokens": self.total_tokens,
            "total_tool_calls": self.total_tool_calls,
            "step_count": len(self.steps),
            "steps": self.steps,
        }
        logger.info(
            "AgentTrace[%s]: %dms, %d tokens, %d tool_calls, %d steps",
            self.query_id, duration_ms, self.total_tokens,
            self.total_tool_calls, len(self.steps),
        )
        return result
