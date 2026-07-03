"""Pytest fixtures for Paper Assistant tests."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# 确保项目根在 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 测试时使用测试数据目录，避免污染真实数据
os.environ.setdefault("PAPER_ASSISTANT_DATA_DIR", str(ROOT / "tests" / "_test_data"))
os.environ.setdefault("PAPER_ASSISTANT_CHROMA_DIR", str(ROOT / "tests" / "_test_data" / "chroma_test"))
os.environ.setdefault("PAPER_ASSISTANT_LOG_DIR", str(ROOT / "tests" / "_test_data" / "logs"))
os.environ.setdefault("PAPER_ASSISTANT_LOG_LEVEL", "WARNING")
os.environ.setdefault("CACHE_ENABLED", "false")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-real")

import pytest


@pytest.fixture(autouse=True)
def clean_test_dirs():
    """每个测试前确保测试目录存在，测试后清理。"""
    import shutil
    test_data = Path(ROOT / "tests" / "_test_data")
    test_data.mkdir(parents=True, exist_ok=True)

    # 重置 DB 初始化状态
    import src.db.schema as _schema
    _schema._initialized = False

    yield

    # Windows 上 SQLite 可能有文件锁，重试清理
    for _ in range(5):
        try:
            chroma_test = test_data / "chroma_test"
            if chroma_test.exists():
                shutil.rmtree(str(chroma_test), ignore_errors=True)
            test_db = test_data / "paper_assistant.db"
            if test_db.exists():
                test_db.unlink(missing_ok=True)
            break
        except (PermissionError, OSError):
            import gc
            gc.collect()
            time.sleep(0.1)
