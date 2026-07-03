"""Agent 子包 — LLM 自主多步推理。

架构：
    base.py          → BaseAgent 抽象类
    openai_agent.py  → OpenAIFunctionsAgent 实现
    tools.py         → 7 个 LangChain @tool
    memory.py        → AgentMemory 上下文管理
    guardrails.py    → AgentGuardrails 安全护栏
    retry.py         → 工具调用重试
    observability.py → AgentTrace 链路追踪
    compare.py       → compare_papers() 业务函数
    schemas.py       → Pydantic 请求/响应模型
"""

from .base import BaseAgent
from .openai_agent import OpenAIFunctionsAgent, run_agent_stream
from .tools import ALL_TOOLS, get_tool_by_name, get_tools_openai_format
from .schemas import AgentEvent, AgentQueryRequest, AgentQueryResponse

__all__ = [
    "BaseAgent",
    "OpenAIFunctionsAgent",
    "run_agent_stream",
    "ALL_TOOLS",
    "get_tool_by_name",
    "get_tools_openai_format",
    "AgentEvent",
    "AgentQueryRequest",
    "AgentQueryResponse",
]
