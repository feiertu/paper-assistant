"""LLM 子包：客户端封装 + prompt 模板。

上层统一通过 `get_llm()` 拿客户端；不要在业务代码里直接 import openai。
Prompt 模板集中在 prompts.py，便于后续评测时调整。
"""

from .client import LLMClient, get_llm
from . import prompts

__all__ = ["LLMClient", "get_llm", "prompts"]