"""Agent 安全护栏。

防止 Agent 陷入死循环、过度调用同一工具或超出推理限制。
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from src.logging_config import get_logger

logger = get_logger(__name__)


class AgentGuardrails:
    """Agent 执行时的安全护栏。

    规则：
    1. 同一工具+同参数连续调用 > max_same_tool_calls → 阻止
    2. 总迭代次数 > max_iterations → 阻止
    3. 检测到 3 步以上的工具调用循环 → 阻止
    """

    def __init__(
        self,
        max_iterations: int = 10,
        max_same_tool_calls: int = 3,
    ):
        self.max_iterations = max_iterations
        self.max_same_tool_calls = max_same_tool_calls
        self.call_history: list[str] = []
        self.consecutive_same: int = 0
        self._last_signature: str = ""

    def check(self, tool_name: str, args: dict) -> Optional[str]:
        """检查工具调用是否应被允许。

        Returns:
            None = 允许; str = 阻止原因
        """
        # 生成调用签名
        sig = _call_signature(tool_name, args)

        # 规则 1: 同一工具+同参数连续调用
        if sig == self._last_signature:
            self.consecutive_same += 1
            if self.consecutive_same > self.max_same_tool_calls:
                reason = (
                    f"同一工具 '{tool_name}' 使用相同参数连续调用了 "
                    f"{self.consecutive_same} 次，已被阻止。请尝试其他方法或给出最终答案。"
                )
                logger.warning("Guardrails 阻止: %s", reason[:100])
                return reason
        else:
            self.consecutive_same = 1

        self._last_signature = sig
        self.call_history.append(sig)

        # 规则 3: 循环检测（最近 6 次调用中是否有重复模式）
        if len(self.call_history) >= 6:
            recent = self.call_history[-6:]
            if len(set(recent)) <= 2:  # 只有 2 种不同调用在循环
                reason = "检测到工具调用循环，已终止。请直接基于已有信息给出最终答案。"
                logger.warning("Guardrails 阻止: 循环检测")
                return reason

        return None

    def should_terminate(self, iteration: int) -> Optional[str]:
        """检查是否应终止 Agent 循环。

        Returns:
            None = 继续; str = 终止原因
        """
        if iteration >= self.max_iterations:
            return (
                f"已达到最大推理步数 ({self.max_iterations})，"
                f"请基于目前收集到的信息给出最终答案。"
            )
        return None

    def reset(self) -> None:
        """重置护栏状态（每次 Agent 查询用新的护栏）。"""
        self.call_history.clear()
        self.consecutive_same = 0
        self._last_signature = ""


def _call_signature(tool_name: str, args: dict) -> str:
    """生成工具调用的唯一签名。"""
    raw = tool_name + json.dumps(args, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()[:12]
