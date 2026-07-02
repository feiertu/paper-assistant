"""src/llm 离线烟测：不调真实 LLM，只验证 import 链 + prompt 渲染。

用法：python scripts/smoke_test_llm.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    # 1. import 链
    from src.llm import get_llm, LLMClient
    from src.llm import prompts
    from src.llm.client import reset_llm

    print("[1] imports OK")

    # 2. 单例（不构造客户端，所以不校验 key）
    reset_llm()
    print("[2] reset_llm OK")

    # 3. prompts 渲染
    hits = [
        {
            "document": "本文提出一种新的检索增强生成方法，在多个基准上取得 SOTA。",
            "metadata": {
                "section_title": "Abstract",
                "page": 1,
                "source": "2606.13673v1",
            },
            "distance": 0.12,
        },
        {
            "document": "We use bge-small-zh as the embedding model and Chroma as the vector store.",
            "metadata": {
                "section_title": "Method",
                "page": 3,
                "source": "2606.13673v1",
            },
            "distance": 0.31,
        },
    ]

    ctx = prompts.format_context(hits)
    print("[3] format_context:")
    print("---")
    print(ctx)
    print("---")

    qa_prompt = prompts.RAG_QA_PROMPT_ZH.format(
        context=ctx,
        query="这篇论文用的什么 embedding 模型？",
    )
    assert "{context}" not in qa_prompt and "{query}" not in qa_prompt
    print("[4] RAG_QA_PROMPT_ZH rendered OK, length =", len(qa_prompt))

    summary_prompt = prompts.SUMMARY_PROMPT_ZH.format(
        text="这是一段示例文本，用于验证 prompt 渲染。",
        max_words=100,
    )
    assert "{text}" not in summary_prompt and "{max_words}" not in summary_prompt
    print("[5] SUMMARY_PROMPT_ZH rendered OK, length =", len(summary_prompt))

    survey_prompt = prompts.SURVEY_PROMPT_ZH.format(context=ctx, max_words=300)
    print("[6] SURVEY_PROMPT_ZH rendered OK, length =", len(survey_prompt))

    # 4. 类签名检查
    import inspect

    for name in (
        "chat", "chat_stream",
        "complete_with_context", "complete_with_context_stream",
        "summarize", "survey",
    ):
        assert hasattr(LLMClient, name), f"LLMClient 缺少方法: {name}"
    print("[7] LLMClient method signature OK (incl. stream)")

    sig = inspect.signature(LLMClient.__init__)
    params = list(sig.parameters.keys())
    print(f"[8] LLMClient.__init__ params = {params}")

    print("\nALL OK. 设了 OPENAI_API_KEY 之后可调用：")
    print("    python -c \"from src.llm import get_llm; print(get_llm().chat([{'role':'user','content':'hi'}]))\"")


if __name__ == "__main__":
    main()