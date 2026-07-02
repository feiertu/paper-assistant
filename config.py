"""Paper Assistant 全局配置。

所有模块从这里导入配置项，不要在模块里硬编码路径 / API key / 模型名。
环境变量（.env 或系统环境）优先级最高，没有则使用下面默认值。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(key)
    return val if val not in (None, "") else default


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "") or default)
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, "") or default)
    except (TypeError, ValueError):
        return default


# ---------- 项目根目录 ----------

PROJECT_ROOT: Path = Path(__file__).resolve().parent

# ---------- 数据目录 ----------

DATA_DIR: Path = Path(_env("PAPER_ASSISTANT_DATA_DIR", str(PROJECT_ROOT / "data")))
RAW_PDF_DIR: Path = DATA_DIR / "raw"
PARSED_DIR: Path = DATA_DIR / "parsed"
CHROMA_DIR: Path = Path(_env("PAPER_ASSISTANT_CHROMA_DIR", str(PROJECT_ROOT / "data" / "chroma_db")))
PROCESSED_DIR: Path = DATA_DIR / "processed"
LOG_DIR: Path = Path(_env("PAPER_ASSISTANT_LOG_DIR", str(PROJECT_ROOT / "logs")))

for d in (RAW_PDF_DIR, PARSED_DIR, CHROMA_DIR, PROCESSED_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---------- arXiv 抓取 ----------

ARXIV_QUERY: str = _env("ARXIV_QUERY", "cat:cs.AI AND ti:learning") or "cat:cs.AI AND ti:learning"
ARXIV_MAX_RESULTS: int = _env_int("ARXIV_MAX_RESULTS", 5)
ARXIV_REQUEST_TIMEOUT: int = _env_int("ARXIV_REQUEST_TIMEOUT", 20)
PDF_DOWNLOAD_DELAY: float = _env_float("PDF_DOWNLOAD_DELAY", 3.0)

# ---------- PDF 解析 ----------

PDF_MIN_BODY_SIZE: float = _env_float("PDF_MIN_BODY_SIZE", 6.5)

# ---------- 文本分块 ----------

CHUNK_SIZE: int = _env_int("CHUNK_SIZE", 1000)
CHUNK_OVERLAP: int = _env_int("CHUNK_OVERLAP", 200)

# ---------- Embedding ----------

# provider: 逗号分隔，可选 "openai" / "voyage"，例如 "openai,voyage" 开启 RRF 双路检索
EMBEDDING_PROVIDER: str = _env("EMBEDDING_PROVIDER", "openai,voyage") or "openai,voyage"
EMBEDDING_MODEL: str = _env("EMBEDDING_MODEL", "text-embedding-3-large") or "text-embedding-3-large"
EMBEDDING_DIM: int = _env_int("EMBEDDING_DIM", 1024)
EMBEDDING_BATCH_SIZE: int = _env_int("EMBEDDING_BATCH_SIZE", 32)
# RRF 重排序参数
RRF_TOP_N: int = _env_int("RRF_TOP_N", 20)  # 每路检索取 top-N 进行融合
RRF_K: int = _env_int("RRF_K", 60)  # RRF 平滑常数

# ---------- LLM ----------

OPENAI_API_KEY: Optional[str] = _env("OPENAI_API_KEY")
OPENAI_BASE_URL: Optional[str] = _env("OPENAI_BASE_URL")
LLM_MODEL: str = _env("LLM_MODEL", "qwen-2.5-72b-instruct") or "qwen-2.5-72b-instruct"
LLM_TEMPERATURE: float = _env_float("LLM_TEMPERATURE", 0.2)
LLM_MAX_TOKENS: int = _env_int("LLM_MAX_TOKENS", 1024)

# ---------- Voyage AI ----------

VOYAGE_API_KEY: Optional[str] = _env("VOYAGE_API_KEY")

# ---------- RAG 检索 ----------

RAG_TOP_K: int = _env_int("RAG_TOP_K", 5)
RAG_COLLECTION_NAME: str = _env("RAG_COLLECTION_NAME", "knowledge") or "knowledge"

# ---------- API 服务 ----------

API_HOST: str = _env("API_HOST", "127.0.0.1") or "127.0.0.1"
API_PORT: int = _env_int("API_PORT", 8000)

# ---------- Streamlit UI ----------

UI_TITLE: str = _env("UI_TITLE", "📚 Paper Assistant") or "📚 Paper Assistant"


# ---------- 校验 ----------

def require_openai_key() -> str:
    """需要 OpenAI key 的地方（embed / llm）调用，缺失则立即报错。"""
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "未配置 OPENAI_API_KEY。请在 .env 中设置，或导出环境变量。"
        )
    return OPENAI_API_KEY


def summary() -> dict:
    """打印/调试用：返回当前生效的配置快照（脱敏）。"""
    return {
        "PROJECT_ROOT": str(PROJECT_ROOT),
        "DATA_DIR": str(DATA_DIR),
        "CHROMA_DIR": str(CHROMA_DIR),
        "ARXIV_QUERY": ARXIV_QUERY,
        "ARXIV_MAX_RESULTS": ARXIV_MAX_RESULTS,
        "CHUNK_SIZE": CHUNK_SIZE,
        "CHUNK_OVERLAP": CHUNK_OVERLAP,
        "EMBEDDING_PROVIDER": EMBEDDING_PROVIDER,
        "EMBEDDING_MODEL": EMBEDDING_MODEL,
        "EMBEDDING_DIM": EMBEDDING_DIM,
        "RRF_TOP_N": RRF_TOP_N,
        "LLM_MODEL": LLM_MODEL,
        "OPENAI_API_KEY_SET": bool(OPENAI_API_KEY),
        "OPENAI_BASE_URL": OPENAI_BASE_URL,
        "VOYAGE_API_KEY_SET": bool(VOYAGE_API_KEY),
        "RAG_TOP_K": RAG_TOP_K,
        "RAG_COLLECTION_NAME": RAG_COLLECTION_NAME,
        "API_HOST": API_HOST,
        "API_PORT": API_PORT,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(summary(), ensure_ascii=False, indent=2))