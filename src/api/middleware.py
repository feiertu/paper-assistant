"""API 鉴权与限流中间件。

特性：
- API Key 鉴权（可选，通过 API_AUTH_ENABLED 控制）
- 简单的滑动窗口限流（支持反向代理 X-Forwarded-For）
- 健康检查 /health 和 /config 端点不受鉴权限制
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

import config
from src.logging_config import get_logger

logger = get_logger(__name__)

# 限流白名单
_RATE_LIMIT_WHITELIST = {"/health", "/config", "/api/docs", "/api/redoc", "/api/openapi.json"}
_AUTH_WHITELIST = {"/health", "/config", "/api/docs", "/api/redoc", "/api/openapi.json"}


def _get_real_ip(request: Request) -> str:
    """获取真实客户端 IP，优先读取反向代理头。

    优先级: X-Forwarded-For（取第一个） > X-Real-IP > 直连 IP
    """
    # X-Forwarded-For: "client, proxy1, proxy2" — 取第一个（原始客户端）
    xff = request.headers.get("X-Forwarded-For", "").strip()
    if xff:
        return xff.split(",")[0].strip()

    # X-Real-IP: nginx 设置的单一 IP
    xri = request.headers.get("X-Real-IP", "").strip()
    if xri:
        return xri

    # 直连（本地开发、健康检查等）
    if request.client:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """简单滑动窗口限流。

    按真实客户端 IP（X-Forwarded-For）做全局限流，默认 30 req/min。
    兼容反向代理（nginx）部署场景。
    """

    def __init__(self, app, max_requests: int = 30, window_seconds: int = 60):
        super().__init__(app)
        self._max_requests = max_requests
        self._window = window_seconds
        self._clients: Dict[str, List[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 白名单不限制
        if path in _RATE_LIMIT_WHITELIST:
            return await call_next(request)

        client_ip = _get_real_ip(request)
        now = time.time()

        # 清理过期记录
        window_start = now - self._window
        self._clients[client_ip] = [
            ts for ts in self._clients[client_ip] if ts > window_start
        ]

        if len(self._clients[client_ip]) >= self._max_requests:
            logger.warning("限流触发: ip=%s path=%s count=%d",
                           client_ip, path, len(self._clients[client_ip]))
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"请求过于频繁，限制 {self._max_requests} 次/{self._window}s",
                    "retry_after": self._window,
                },
            )

        self._clients[client_ip].append(now)
        return await call_next(request)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """简单 API Key 鉴权中间件。

    通过 X-API-Key 请求头传递 API Key。
    仅在 API_AUTH_ENABLED=True 时生效。
    """

    def __init__(self, app, api_key: Optional[str] = None):
        super().__init__(app)
        self._api_key = api_key or config.API_AUTH_KEY

    async def dispatch(self, request: Request, call_next):
        # 鉴权未启用或白名单路径
        if not config.API_AUTH_ENABLED or request.url.path in _AUTH_WHITELIST:
            return await call_next(request)

        # OPTIONS 预检请求放行
        if request.method == "OPTIONS":
            return await call_next(request)

        # 鉴权已启用但 KEY 为空：拒绝所有请求（配置错误）
        if not self._api_key:
            logger.error("API_AUTH_ENABLED=true 但 API_AUTH_KEY 未设置，拒绝所有请求")
            return JSONResponse(
                status_code=500,
                content={"detail": "服务器配置错误：API 鉴权密钥未设置"},
            )

        client_key = request.headers.get("X-API-Key", "")
        if client_key != self._api_key:
            logger.warning("鉴权失败: ip=%s path=%s",
                           _get_real_ip(request),
                           request.url.path)
            return JSONResponse(
                status_code=401,
                content={"detail": "未授权：请提供有效的 X-API-Key"},
            )

        return await call_next(request)


class OwnerMiddleware(BaseHTTPMiddleware):
    """多用户隔离中间件。

    从 cookie (paper_session) 提取 owner_id，注入到 request.state.owner_id。
    白名单路径跳过。
    """

    _OWNER_WHITELIST = {"/health", "/api/docs", "/api/redoc", "/api/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._OWNER_WHITELIST:
            request.state.owner_id = ""
            return await call_next(request)

        # 优先从 cookie 读取，其次从 X-Owner-Id 头（Streamlit 内部调用）
        owner = request.cookies.get(config.SESSION_COOKIE, "")
        if not owner:
            owner = request.headers.get("X-Owner-Id", "")
        request.state.owner_id = owner
        return await call_next(request)


def get_owner_id(request: Request) -> str:
    """从请求中提取 owner_id。"""
    return getattr(request.state, "owner_id", "")


def parse_rate_limit(limit_str: str) -> tuple:
    """解析限流字符串为 (requests, seconds)。

    "30/minute" → (30, 60)
    "100/hour" → (100, 3600)
    "5/second" → (5, 1)
    """
    parts = limit_str.strip().split("/")
    if len(parts) != 2:
        return 30, 60
    try:
        count = int(parts[0])
    except ValueError:
        count = 30
    unit = parts[1].lower().rstrip("s")
    seconds = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}.get(unit, 60)
    return count, seconds
