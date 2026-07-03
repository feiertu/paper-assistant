"""Agent 上下文记忆管理。

管理多步推理中的对话历史和上下文窗口。
自动截断过期内容，保留关键信息。
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.logging_config import get_logger

logger = get_logger(__name__)


class AgentMemory:
    """管理 Agent 对话历史和上下文窗口。

    策略：
    - 保留 system prompt（始终不删）
    - 保留 user query（始终不删）
    - tool_result 超过 2000 字符自动截断
    - 总消息数接近上限时删除最早的 tool 交互对
    """

    def __init__(self, max_tokens: int = 8000):
        self.messages: List[Dict[str, Any]] = []
        self.max_tokens = max_tokens

    def add(self, message: Dict[str, Any]) -> None:
        """添加消息到历史。"""
        msg = dict(message)

        # 截断过长的 tool 结果
        if msg.get("role") == "tool" and "content" in msg:
            content = msg["content"]
            if isinstance(content, str) and len(content) > 2000:
                msg["content"] = content[:2000] + "\n…(截断)"

        self.messages.append(msg)
        self._truncate_if_needed()

    def _truncate_if_needed(self) -> None:
        """如果消息过多，删除最早的 tool 交互对。"""
        # 简单策略：保留 system + user + 最近 8 条消息
        max_msgs = 20
        if len(self.messages) <= max_msgs:
            return

        # 找到第一个 assistant+tool 交互对的位置（跳过 system 和 user）
        keep_start = min(2, len(self.messages))  # 至少保留前 2 条
        if len(self.messages) > max_msgs:
            removed = len(self.messages) - max_msgs - keep_start + 4
            if removed > 0:
                logger.debug("AgentMemory: 截断 %d 条旧消息", removed)
                # 保留开头 + 末尾
                self.messages = (
                    self.messages[:keep_start] +
                    self.messages[keep_start + removed:]
                )

    def summarize_context(self) -> str:
        """将当前上下文压缩为简短摘要（给 LLM 的 context prompt）。"""
        parts = []
        for msg in self.messages:
            role = msg.get("role", "?")
            if role == "system":
                parts.append("[系统提示]")
            elif role == "user":
                parts.append(f"[用户] {msg.get('content', '')[:100]}")
            elif role == "assistant":
                has_tools = bool(msg.get("tool_calls"))
                parts.append(
                    f"[助手{'调用工具' if has_tools else ''}] "
                    f"{msg.get('content', '')[:80]}"
                )
            elif role == "tool":
                parts.append("[工具结果]")
        return "\n".join(parts)

    def to_openai_messages(self) -> List[Dict[str, Any]]:
        """转为 OpenAI API 兼容的消息格式。"""
        result = []
        for msg in self.messages:
            m = {"role": msg["role"]}
            if "content" in msg:
                m["content"] = msg["content"]
            if "tool_calls" in msg:
                m["tool_calls"] = msg["tool_calls"]
            if "tool_call_id" in msg:
                m["tool_call_id"] = msg["tool_call_id"]
            if "name" in msg:
                m["name"] = msg["name"]
            result.append(m)
        return result
