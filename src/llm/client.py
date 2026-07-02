"""LLM 客户端封装。

只暴露 LLMClient 一个类，统一的 chat / complete_with_context 入口。
底层是 OpenAI 兼容协议（OpenAI / DeepSeek / 通义千问 / 任意 base_url 兼容服务）。
"""

from __future__ import annotations

from typing import Any, Dict, Generator, List, Optional

import config


class LLMClient:
    """简单的 OpenAI Chat 客户端封装。

    用法：
        llm = LLMClient()
        text = llm.chat([{"role": "user", "content": "你好"}])

        # 或者直接走 RAG：
        text = llm.complete_with_context(query, hits, lang="zh")
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        from openai import OpenAI  # 延迟 import，避免 rag/store 不需要 key 时报错

        config.require_openai_key()
        self._client = OpenAI(
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_BASE_URL,
        )
        self._model = model or config.LLM_MODEL
        self._temperature = temperature if temperature is not None else config.LLM_TEMPERATURE
        self._max_tokens = max_tokens or config.LLM_MAX_TOKENS

    # ---------- 基础调用 ----------

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """最原始的 chat 调用，返回 assistant 文本。"""
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=self._max_tokens if max_tokens is None else max_tokens,
            **kwargs,
        )
        return (resp.choices[0].message.content or "").strip()

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ):
        """流式 chat 调用，逐 chunk yield 文本内容。

        用法：
            for chunk in llm.chat_stream(messages):
                print(chunk, end="", flush=True)
        """
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=self._max_tokens if max_tokens is None else max_tokens,
            stream=True,
            **kwargs,
        )
        for chunk in resp:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # ---------- 高层封装 ----------

    def complete_with_context(
        self,
        query: str,
        hits: List[Dict[str, Any]],
        lang: str = "zh",
        max_words: int = 600,
    ) -> str:
        """RAG 场景的一站式问答：拼 prompt → 调用 LLM → 返回答案文本。

        lang="zh" 用中文 prompt；"en" 用英文 prompt。
        hits 由 retriever 给出，结构见 prompts.format_context。
        """
        from . import prompts

        context = prompts.format_context(hits)
        template = prompts.RAG_QA_PROMPT_ZH if lang == "zh" else prompts.RAG_QA_PROMPT_EN
        user_prompt = template.format(context=context, query=query)
        messages = [
            {"role": "system", "content": prompts.RAG_QA_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        return self.chat(messages)

    def complete_with_context_stream(
        self,
        query: str,
        hits: List[Dict[str, Any]],
        lang: str = "zh",
    ) -> Generator[str, None, None]:
        """RAG 场景的流式问答：同 complete_with_context，但逐 chunk 输出。

        用法：
            for chunk in llm.complete_with_context_stream(query, hits):
                print(chunk, end="", flush=True)
        """
        from . import prompts

        context = prompts.format_context(hits)
        template = prompts.RAG_QA_PROMPT_ZH if lang == "zh" else prompts.RAG_QA_PROMPT_EN
        user_prompt = template.format(context=context, query=query)
        messages = [
            {"role": "system", "content": prompts.RAG_QA_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        yield from self.chat_stream(messages)

    def summarize(self, text: str, lang: str = "zh", max_words: int = 200) -> str:
        """单文档摘要：直接对原始文本调 LLM（不经过检索）。

        rag 模块做"单文档摘要"时会自己 retrieve 全量 hits 后调这个。
        """
        from . import prompts

        template = prompts.SUMMARY_PROMPT_ZH if lang == "zh" else prompts.SUMMARY_PROMPT_EN
        user_prompt = template.format(text=text, max_words=max_words)
        return self.chat([{"role": "user", "content": user_prompt}])

    def survey(self, hits: List[Dict[str, Any]], lang: str = "zh", max_words: int = 800) -> str:
        """综述生成：把多文档 hits 拼成 context，调 LLM。"""
        from . import prompts

        context = prompts.format_context(hits)
        template = prompts.SURVEY_PROMPT_ZH if lang == "zh" else prompts.SURVEY_PROMPT_ZH  # 先只做中文
        user_prompt = template.format(context=context, max_words=max_words)
        return self.chat([{"role": "user", "content": user_prompt}])

    # ---------- 调试 ----------

    @property
    def model(self) -> str:
        return self._model


# ---------- 单例 ----------

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