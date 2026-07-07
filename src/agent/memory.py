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
        """如果消息过多，安全删除最早的完整 assistant+tool 交互组。

        必须保持 OpenAI API 要求的消息配对：
        - 每条 role=tool 消息前面必须有对应的 assistant(tool_calls) 消息
        - 截断时以完整交互组为单位删除，不留孤立的 tool 消息
        """
        max_msgs = 20
        if len(self.messages) <= max_msgs:
            return

        keep_start = min(2, len(self.messages))  # 保留 system + user

        # 从 keep_start 开始，找到完整的 assistant+tool 组并逐个移除
        while len(self.messages) > max_msgs:
            i = keep_start
            found_group = False
            while i < len(self.messages):
                msg = self.messages[i]
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    # 找到这个 assistant 对应的所有 tool 消息
                    tc_ids = {tc.get("id", "") for tc in msg["tool_calls"]}
                    group_end = i + 1
                    while group_end < len(self.messages) and tc_ids:
                        next_msg = self.messages[group_end]
                        if next_msg.get("role") == "tool":
                            tid = next_msg.get("tool_call_id", "")
                            tc_ids.discard(tid)
                        group_end += 1
                    # 安全移除整个 group
                    group_size = group_end - i
                    del self.messages[i:group_end]
                    found_group = True
                    logger.debug("AgentMemory: 移除 assistant+tool 组 (%d 条)", group_size)
                    break
                elif msg.get("role") == "assistant":
                    # 无 tool_calls 的 assistant — 安全移除
                    del self.messages[i]
                    found_group = True
                    logger.debug("AgentMemory: 移除单条 assistant 消息")
                    break
                elif msg.get("role") == "tool":
                    # 孤立的 tool 消息（异常情况）— 移除
                    del self.messages[i]
                    found_group = True
                    logger.debug("AgentMemory: 移除孤立 tool 消息")
                    break
                i += 1

            if not found_group:
                logger.warning(
                    "AgentMemory: 无法安全截断，当前 %d 条 > 上限 %d 条",
                    len(self.messages), max_msgs,
                )
                break

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
