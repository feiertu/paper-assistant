"""工具调用重试逻辑。

错误分类：可重试错误（网络/限流）vs 不可重试（参数错误/文件缺失）。
"""

from __future__ import annotations

import time
from typing import Any

from src.logging_config import get_logger

logger = get_logger(__name__)


class RetryableError(Exception):
    """可重试错误：网络超时、API 限流等。"""
    pass


class NonRetryableError(Exception):
    """不可重试错误：参数错误、文件缺失等。"""
    pass


def execute_tool_with_retry(
    tool_func,
    args: dict,
    max_retries: int = 2,
) -> str:
    """执行工具调用，失败时自动重试。

    重试策略：
    - 可重试：指数退避 2^n 秒，最多 max_retries 次
    - 不可重试：立即返回错误信息

    Args:
        tool_func: 工具函数（@tool 装饰后的 .func 或直接调用）
        args: 工具参数字典
        max_retries: 最大重试次数

    Returns:
        工具执行结果（字符串）
    """
    for attempt in range(max_retries + 1):
        try:
            result = tool_func(**args)
            return str(result)
        except Exception as e:
            error_type = _classify_error(e)

            if error_type == "non_retryable":
                return f"工具调用失败（参数或数据错误）: {e}"

            # 可重试
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning(
                    "工具调用失败 (attempt=%d/%d, wait=%ds): %s",
                    attempt + 1, max_retries + 1, wait, e,
                )
                time.sleep(wait)
                continue
            else:
                return (
                    f"工具调用失败，已重试 {max_retries} 次。"
                    f"错误: {e}。请尝试其他方法或修改参数。"
                )

    return "工具调用失败（未知原因）"


def _classify_error(e: Exception) -> str:
    """分类错误类型。"""
    name = type(e).__name__
    msg = str(e).lower()

    # 不可重试
    non_retryable = [
        "valueerror", "typeerror", "keyerror", "filenotfounderror",
        "notfounderror", "404", "not found", "不存在",
    ]
    for pattern in non_retryable:
        if pattern in name.lower() or pattern in msg:
            return "non_retryable"

    # 默认可重试（网络、超时等）
    return "retryable"
