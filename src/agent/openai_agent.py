"""OpenAI Functions Agent 实现。

基于 OpenAI function calling 协议的自定义 Agent 循环。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Generator, List, Optional

import config
from src.llm.client import LLMClient, get_llm
from src.logging_config import get_logger

from .base import BaseAgent
from .guardrails import AgentGuardrails
from .memory import AgentMemory
from .observability import AgentTrace
from .retry import execute_tool_with_retry
from .schemas import AgentEvent
from .tools import ALL_TOOLS, TOOL_BY_NAME, get_tools_openai_format

logger = get_logger(__name__)

# ── System Prompt ──

SYSTEM_PROMPT_ZH = """你是论文研究助手，能够使用工具来帮助你检索、分析、比较和综述学术论文。

## 可用工具
1. **search** — 搜索论文（支持关键词全文搜索、语义搜索、列出已入库论文）
2. **get_paper** — 获取指定论文的详细元数据（标题/作者/摘要/日期）
3. **summarize_paper** — 对指定论文生成结构化摘要
4. **get_citations** — 查看论文的引用关系图（引用+被引）
5. **compare_papers** — 对比两篇论文的异同（问题/方法/结果/意义）
6. **recommend_similar** — 推荐与指定论文相似的其他论文
7. **generate_survey** — 生成多论文主题综述或导出论文数据

## 工作指南
1. 收到用户问题后，先判断需要哪些工具，分步骤执行
2. 搜索到论文后，如果用户想深入了解，主动调用 summarize_paper 或 get_paper
3. 对比分析时，先确认两篇论文都在库中，再调用 compare_papers
4. 只使用工具返回的真实信息，不要编造
5. 回答结构清晰，引用具体的论文标题、arXiv ID 和数据
6. 如果工具返回错误，如实告知用户，并尝试其他方法
7. 如果多次搜索无结果，建议用户调整关键词或研究方向

## 回答格式
- 先简要分析用户的需求
- 列出执行步骤（如果使用了多个工具）
- 给出最终答案，关键信息加粗或编号"""

SYSTEM_PROMPT_EN = """You are a research paper assistant with access to tools for searching, analyzing, comparing, and surveying academic papers.

## Available Tools
1. **search** — Search papers (keyword FTS, semantic, or list)
2. **get_paper** — Get detailed metadata for a paper
3. **summarize_paper** — Generate a structured summary for a paper
4. **get_citations** — View citation graph (cites + cited by)
5. **compare_papers** — Compare two papers (problem/method/results/significance)
6. **recommend_similar** — Recommend similar papers by vector similarity
7. **generate_survey** — Generate multi-paper survey or export data

## Guidelines
1. Decompose the user's question, use tools step by step
2. After finding papers, proactively summarize or get details when the user wants depth
3. For comparisons, verify both papers exist before calling compare_papers
4. Only use real information from tools — do not fabricate
5. Structure answers clearly, cite paper titles and arXiv IDs
6. If a tool errors, tell the user honestly and try alternatives"""


class OpenAIFunctionsAgent(BaseAgent):
    """基于 OpenAI function calling 的 Agent 实现。

    用法：
        agent = OpenAIFunctionsAgent(model="gpt-4o")
        for event in agent.run_stream("对比两篇论文..."):
            print(event)
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_iterations: Optional[int] = None,
        enabled_tools: Optional[List[str]] = None,
    ):
        self._model = model or config.LLM_AGENT_MODEL
        self._temperature = (
            temperature if temperature is not None else config.AGENT_TEMPERATURE
        )
        self._max_iterations = max_iterations or config.AGENT_MAX_ITERATIONS
        self._enabled_tools = enabled_tools  # None = all

    def run(self, query: str, lang: str = "zh") -> Generator:
        """执行 Agent 推理（同步 Generator，FastAPI SSE 兼容）。"""
        yield from self.run_stream(query, lang=lang)

    def run_stream(
        self,
        query: str,
        lang: str = "zh",
    ) -> Generator[AgentEvent, None, None]:
        """同步流式执行 Agent（用于 FastAPI SSE）。

        事件类型：
        - thinking: Agent 开始思考
        - tool_call: Agent 决定调用工具
        - tool_result: 工具执行完成
        - error: 工具执行出错
        - answer_chunk: 最终答案的文本片段
        - usage: 统计信息（token 用量、步数、耗时）
        - done: 执行完成

        Yields:
            AgentEvent
        """
        llm = LLMClient(model=self._model, temperature=self._temperature)
        memory = AgentMemory(max_tokens=config.AGENT_MAX_CONTEXT_TOKENS)
        guardrails = AgentGuardrails(max_iterations=self._max_iterations)
        trace = AgentTrace()

        system_prompt = SYSTEM_PROMPT_ZH if lang == "zh" else SYSTEM_PROMPT_EN
        tools_schema = get_tools_openai_format(self._enabled_tools)

        # 初始化消息
        memory.add({"role": "system", "content": system_prompt})
        memory.add({"role": "user", "content": query})

        yield AgentEvent(type="thinking", content=f"开始分析用户问题…（最多 {self._max_iterations} 步）")

        for iteration in range(self._max_iterations):
            # ── 护栏检查 ──
            term_reason = guardrails.should_terminate(iteration)
            if term_reason:
                yield AgentEvent(type="thinking", content=term_reason)
                # 强制要求 LLM 给出最终答案
                memory.add({
                    "role": "user",
                    "content": f"⚠️ {term_reason} 请基于目前已有信息，直接给出最终答案，不要再调用工具。",
                })
                # 最后一次不带 tools 的调用
                msgs = memory.to_openai_messages()
                response = llm.chat_raw(msgs, tools=[])  # 不带 tools 强制文本输出
                answer = response["message"].get("content", "")
                trace.add_tokens(response.get("usage", {}).get("total_tokens", 0))
                yield AgentEvent(type="answer_chunk", content=answer)
                trace.add_step({"type": "final_forced", "answer": answer, "iteration": iteration + 1})
                break

            # ── 调用 LLM ──
            yield AgentEvent(type="thinking",
                             content=f"推理第 {iteration + 1}/{self._max_iterations} 步…")

            msgs = memory.to_openai_messages()
            response = llm.chat_raw(msgs, tools=tools_schema)
            msg = response["message"]
            usage = response.get("usage", {})
            trace.add_tokens(usage.get("total_tokens", 0))

            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])

            # ── 无 tool_calls：最终答案 ──
            if not tool_calls:
                if content:
                    yield AgentEvent(type="answer_chunk", content=content)
                    trace.add_step({"type": "final_answer", "answer": content, "iteration": iteration + 1})
                break

            # ── 有 tool_calls：执行工具 ──
            # 添加 assistant 消息到历史
            memory.add(msg)

            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                try:
                    tool_args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                # ── 护栏检查 ──
                block_reason = guardrails.check(tool_name, tool_args)
                if block_reason:
                    yield AgentEvent(
                        type="error", tool=tool_name,
                        message=block_reason, args=tool_args,
                    )
                    memory.add({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "name": tool_name,
                        "content": block_reason,
                    })
                    trace.add_step({"type": "tool_blocked", "tool": tool_name, "reason": block_reason})
                    continue

                # ── 发送 tool_call 事件 ──
                yield AgentEvent(
                    type="tool_call", tool=tool_name,
                    args=tool_args,
                    content=f"调用 {tool_name}…",
                )

                # ── 执行工具（带重试） ──
                tool_obj = TOOL_BY_NAME.get(tool_name)
                if tool_obj is None:
                    result_str = f"未知工具: {tool_name}"
                    yield AgentEvent(type="error", tool=tool_name, message=result_str)
                else:
                    try:
                        result_str = execute_tool_with_retry(
                            tool_obj.func, tool_args, max_retries=config.AGENT_TOOL_RETRY,
                        )
                    except Exception as e:
                        result_str = f"工具执行异常: {e}"
                        yield AgentEvent(type="error", tool=tool_name, message=str(e))

                # ── 发送 tool_result 事件 ──
                yield AgentEvent(
                    type="tool_result", tool=tool_name,
                    result=result_str[:2000],
                )

                # ── 添加 tool 结果到历史 ──
                memory.add({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": tool_name,
                    "content": result_str[:2000],
                })

                trace.add_step({
                    "type": "tool_call",
                    "tool": tool_name,
                    "args": tool_args,
                    "result_len": len(result_str),
                })

        # ── 结束事件 ──
        trace_summary = trace.to_dict()
        yield AgentEvent(
            type="usage",
            total_tokens=trace_summary["total_tokens"],
            steps=trace_summary["total_tool_calls"],
            duration_ms=trace_summary["duration_ms"],
        )
        yield AgentEvent(type="done", content="")


# ── 便捷入口 ──

def run_agent_stream(
    query: str,
    model: Optional[str] = None,
    lang: str = "zh",
    max_iterations: Optional[int] = None,
    enabled_tools: Optional[List[str]] = None,
    temperature: Optional[float] = None,
) -> Generator[AgentEvent, None, None]:
    """快速启动 Agent 流式推理。

    Args:
        query: 用户问题
        model: LLM 模型（None 用 config.LLM_AGENT_MODEL）
        lang: "zh" 或 "en"
        max_iterations: 最大推理步数
        enabled_tools: 启用的工具名列表（None = 全部）
        temperature: LLM 温度（None 用 config.AGENT_TEMPERATURE）

    Yields:
        AgentEvent
    """
    agent = OpenAIFunctionsAgent(
        model=model,
        temperature=temperature,
        max_iterations=max_iterations,
        enabled_tools=enabled_tools,
    )
    yield from agent.run_stream(query, lang=lang)
