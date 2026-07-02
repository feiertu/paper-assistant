"""RAG 编排器：统一检索-生成管线。

API 和 UI 都通过这个模块调用，不直接操作底层 embed/store/llm。
"""

from .orchestrator import (
    ingest_parsed_dir,
    ingest_text,
    retrieve,
    answer_rag,
    answer_rag_stream,
    summarize_paper,
    survey,
    get_store_stats,
    list_papers,
    reset_store,
)

__all__ = [
    "ingest_parsed_dir",
    "ingest_text",
    "retrieve",
    "answer_rag",
    "answer_rag_stream",
    "summarize_paper",
    "survey",
    "get_store_stats",
    "list_papers",
    "reset_store",
]
