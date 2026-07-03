"""Agent 请求/响应 Pydantic 模型。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentQueryRequest(BaseModel):
    """Agent 查询请求。"""
    query: str
    lang: str = "zh"
    max_iterations: int = Field(default=10, ge=1, le=30)
    enabled_tools: Optional[List[str]] = None  # None = 全部启用


class AgentEvent(BaseModel):
    """Agent 流式事件。"""
    type: str  # "thinking" | "tool_call" | "tool_result" | "answer_chunk" | "error" | "usage" | "done"
    content: str = ""
    tool: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    result: Optional[str] = None
    total_tokens: Optional[int] = None
    steps: Optional[int] = None
    duration_ms: Optional[int] = None
    message: Optional[str] = None  # 错误消息


class AgentQueryResponse(BaseModel):
    """Agent 查询响应（非流式）。"""
    query: str
    answer: str
    reasoning_steps: List[AgentEvent] = Field(default_factory=list)
    iterations: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
