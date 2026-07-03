"""LLM 客户端封装。

只暴露 LLMClient 一个类，统一的 chat / complete_with_context 入口。
底层是 OpenAI 兼容协议（OpenAI / DeepSeek / 通义千问 / 任意 base_url 兼容服务）。

特性：
- 任务级模型分离：QA / summary / survey 可配置不同模型
- LLM 响应缓存：相同 query+context 避免重复调用
- 结构化日志
"""

from __future__ import annotations

from typing import Any, Dict, Generator, List, Optional

import config
from src.cache import get_llm_cache, make_llm_key, make_context_hash
from src.logging_config import get_logger

logger = get_logger(__name__)


class LLMClient:
    """OpenAI Chat 客户端封装，支持缓存和任务级模型。

    用法：
        llm = LLMClient()
        text = llm.chat([{"role": "user", "content": "你好"}])

        # 或者直接走 RAG（自动缓存）：
        text = llm.complete_with_context(query, hits, lang="zh")
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        from openai import OpenAI

        config.require_openai_key()
        self._client = OpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
        )
        self._model = model or config.LLM_MODEL
        self._temperature = temperature if temperature is not None else config.LLM_TEMPERATURE
        self._max_tokens = max_tokens or config.LLM_MAX_TOKENS

        # ── 任务级模型 ──
        self._qa_model = config.LLM_QA_MODEL
        self._summary_model = config.LLM_SUMMARY_MODEL
        self._survey_model = config.LLM_SURVEY_MODEL

        self._cache = get_llm_cache() if config.CACHE_ENABLED else None

        logger.info(
            "LLMClient 初始化 model=%s temp=%.2f max_tokens=%d cache=%s",
            self._model, self._temperature, self._max_tokens,
            "enabled" if self._cache else "disabled",
        )

    # ────────── 基础调用 ──────────

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """最原始的 chat 调用，返回 assistant 文本。"""
        use_model = model or self._model
        logger.debug("chat: model=%s msg_count=%d", use_model, len(messages))
        resp = self._client.chat.completions.create(
            model=use_model,
            messages=messages,
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=self._max_tokens if max_tokens is None else max_tokens,
            **kwargs,
        )
        result = (resp.choices[0].message.content or "").strip()
        logger.debug("chat: result_len=%d tokens_used=%s", len(result),
                      resp.usage.total_tokens if resp.usage else "?")
        return result

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ):
        """流式 chat 调用，逐 chunk yield 文本内容。"""
        use_model = model or self._model
        resp = self._client.chat.completions.create(
            model=use_model,
            messages=messages,
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=self._max_tokens if max_tokens is None else max_tokens,
            stream=True,
            **kwargs,
        )
        for chunk in resp:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # ────────── 高层封装（带缓存） ──────────

    def complete_with_context(
        self,
        query: str,
        hits: List[Dict[str, Any]],
        lang: str = "zh",
        max_words: int = 600,
    ) -> str:
        """RAG 场景的一站式问答：拼 prompt → 调 LLM → 返回答案文本。

        先在缓存中查找，命中则直接返回。
        """
        from . import prompts

        context = prompts.format_context(hits)
        ctx_hash = make_context_hash([h.get("document", "") for h in hits])

        # ── 尝试缓存命中 ──
        if self._cache:
            cache_key = make_llm_key(query, ctx_hash, lang, "qa")
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.info("LLM 缓存命中 (QA): query=%.60s", query)
                return cached

        template = prompts.RAG_QA_PROMPT_ZH if lang == "zh" else prompts.RAG_QA_PROMPT_EN
        user_prompt = template.format(context=context, query=query)
        messages = [
            {"role": "system", "content": prompts.RAG_QA_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        logger.info("LLM 调用 (QA): model=%s query=%.60s hits=%d",
                     self._qa_model, query, len(hits))
        result = self.chat(messages, model=self._qa_model)

        # ── 写入缓存 ──
        if self._cache:
            self._cache.set(cache_key, result)

        return result

    def complete_with_context_stream(
        self,
        query: str,
        hits: List[Dict[str, Any]],
        lang: str = "zh",
    ) -> Generator[str, None, None]:
        """RAG 场景的流式问答（不走缓存，因为流式无法缓存）。"""
        from . import prompts

        context = prompts.format_context(hits)
        template = prompts.RAG_QA_PROMPT_ZH if lang == "zh" else prompts.RAG_QA_PROMPT_EN
        user_prompt = template.format(context=context, query=query)
        messages = [
            {"role": "system", "content": prompts.RAG_QA_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        logger.info("LLM 流式调用 (QA): model=%s query=%.60s hits=%d",
                     self._qa_model, query, len(hits))
        yield from self.chat_stream(messages, model=self._qa_model)

    def summarize(self, text: str, lang: str = "zh", max_words: int = 200) -> str:
        """单文档摘要（带缓存）。"""
        from . import prompts

        # ── 缓存 ──
        if self._cache:
            cache_key = make_llm_key(text[:200], make_context_hash([text]), lang, "summary")
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.info("LLM 缓存命中 (summary): text=%.60s", text)
                return cached

        template = prompts.SUMMARY_PROMPT_ZH if lang == "zh" else prompts.SUMMARY_PROMPT_EN
        user_prompt = template.format(text=text, max_words=max_words)
        logger.info("LLM 调用 (summary): model=%s lang=%s text_len=%d",
                     self._summary_model, lang, len(text))
        result = self.chat([{"role": "user", "content": user_prompt}], model=self._summary_model)

        if self._cache:
            self._cache.set(cache_key, result)
        return result

    def survey(self, hits: List[Dict[str, Any]], lang: str = "zh", max_words: int = 800) -> str:
        """综述生成（带缓存）。"""
        from . import prompts

        context = prompts.format_context(hits)
        ctx_hash = make_context_hash([h.get("document", "") for h in hits])

        # ── 缓存 ──
        if self._cache:
            cache_key = make_llm_key("survey", ctx_hash, lang, "survey")
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.info("LLM 缓存命中 (survey): hits=%d", len(hits))
                return cached

        template = prompts.SURVEY_PROMPT_ZH if lang == "zh" else prompts.SURVEY_PROMPT_EN
        user_prompt = template.format(context=context, max_words=max_words)
        logger.info("LLM 调用 (survey): model=%s lang=%s hits=%d",
                     self._survey_model, lang, len(hits))
        result = self.chat([{"role": "user", "content": user_prompt}], model=self._survey_model)

        if self._cache:
            self._cache.set(cache_key, result)
        return result

    # ────────── Agent / Tool Calling ──────────

    def chat_raw(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """与 chat() 相同，但返回完整 message 对象（含 tool_calls）。

        供 Agent 循环使用，需要从响应中提取 tool_calls 来执行工具。

        Returns:
            {"message": {"role": "assistant", "content": "...", "tool_calls": [...]},
             "usage": {"total_tokens": N, ...}}
        """
        use_model = model or self._model
        logger.debug("chat_raw: model=%s msg_count=%d tools=%d",
                     use_model, len(messages), len(tools or []))
        resp = self._client.chat.completions.create(
            model=use_model,
            messages=messages,
            tools=tools or [],
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=self._max_tokens if max_tokens is None else max_tokens,
            **kwargs,
        )
        choice = resp.choices[0]
        message: Dict[str, Any] = {
            "role": "assistant",
            "content": choice.message.content or "",
        }
        if choice.message.tool_calls:
            message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]
        usage = {}
        if resp.usage:
            usage = {
                "total_tokens": resp.usage.total_tokens,
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            }
        return {"message": message, "usage": usage}

    def chat_raw_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        **kwargs: Any,
    ):
        """流式版 chat_raw，逐 chunk yield 完整 delta（含 tool_calls 增量）。

        用法：
            for chunk in llm.chat_raw_stream(messages, tools):
                # chunk = {"delta": {"content": "...", "tool_calls": [...]}, "finish_reason": ...}
        """
        use_model = model or self._model
        resp = self._client.chat.completions.create(
            model=use_model,
            messages=messages,
            tools=tools or [],
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=self._max_tokens if max_tokens is None else max_tokens,
            stream=True,
            stream_options={"include_usage": True},
            **kwargs,
        )
        for chunk in resp:
            delta: Dict[str, Any] = {"content": ""}
            choice = chunk.choices[0] if chunk.choices else None
            if choice is None:
                # usage chunk (stream_options enabled)
                usage = getattr(chunk, "usage", None)
                if usage:
                    yield {"usage": {
                        "total_tokens": usage.total_tokens,
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                    }}
                continue
            if choice.delta.content:
                delta["content"] = choice.delta.content
            if choice.delta.tool_calls:
                delta["tool_calls"] = []
                for tc in choice.delta.tool_calls:
                    delta["tool_calls"].append({
                        "index": tc.index,
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        } if tc.function else {},
                    })
            yield {"delta": delta, "finish_reason": choice.finish_reason}

    # ────────── 调试 ──────────

    @property
    def model(self) -> str:
        return self._model

    @property
    def cache_stats(self) -> Optional[dict]:
        if self._cache:
            return self._cache.stats
        return None


# ────────── 单例 ──────────

_llm: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    """获取 LLMClient 单例。第一次调用时会校验 OPENAI_API_KEY。"""
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm


def reset_llm() -> None:
    """测试用：清掉单例，下次 get_llm() 会重新构造。"""
    global _llm
    _llm = None


__all__ = ["LLMClient", "get_llm", "reset_llm"]
