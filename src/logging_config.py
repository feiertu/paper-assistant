"""结构化日志配置。

使用 Python 标准库 logging，支持：
- 按日期轮转的文件日志（logs/paper_assistant.log）
- 控制台输出
- 可配置日志级别
- 模块级 logger 获取

用法：
    from src.logging_config import get_logger
    logger = get_logger(__name__)
    logger.info("something happened")
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import config

# 日志格式
_FORMAT = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_CONSOLE_FORMAT = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s",
    datefmt="%H:%M:%S",
)

_initialized = False


def setup_logging(
    level: Optional[int] = None,
    log_dir: Optional[Path] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> None:
    """初始化全局日志配置（幂等，多次调用安全）。

    Args:
        level: 日志级别，默认 INFO；DEBUG 可通过 PAPER_ASSISTANT_LOG_LEVEL=DEBUG 设置。
        log_dir: 日志目录，默认 config.LOG_DIR。
        max_bytes: 单个日志文件最大字节数。
        backup_count: 保留的历史日志文件数。
    """
    global _initialized
    if _initialized:
        return

    if level is None:
        raw = config._env("PAPER_ASSISTANT_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, raw, logging.INFO)

    log_dir = Path(log_dir or config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # 清除已有 handler（防止重复）
    root.handlers.clear()

    # ── 文件 handler（轮转） ──
    file_handler = RotatingFileHandler(
        filename=log_dir / "paper_assistant.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(_FORMAT)
    root.addHandler(file_handler)

    # ── 控制台 handler ──
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(_CONSOLE_FORMAT)
    root.addHandler(console_handler)

    # ── 降低第三方库噪音 ──
    for noisy in ("chromadb", "urllib3", "httpx", "openai", "voyageai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _initialized = True
    root.info("日志系统初始化完成 (level=%s, dir=%s)", logging.getLevelName(level), log_dir)


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger。

    首次调用会自动触发 setup_logging()。
    """
    setup_logging()
    return logging.getLogger(name)


def shutdown_logging() -> None:
    """测试/重启用：关闭所有 handler 并重置初始化状态。"""
    global _initialized
    logging.shutdown()
    _initialized = False
