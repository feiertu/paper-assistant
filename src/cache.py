"""查询缓存层。

提供两层缓存：
1. LLM 响应缓存 — 避免相同 context+query 重复调用 LLM
2. Embedding 缓存 — 避免相同文本重复调用 embedding API

使用 LRU + TTL 策略，适合单机部署。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple


class TTLCache:
    """带 TTL 的 LRU 缓存。

    特性：
    - 最大容量限制（maxsize），超出后淘汰最久未使用项
    - TTL 过期自动失效
    - 线程安全
    - 命中率统计

    用法：
        cache = TTLCache(maxsize=500, ttl=3600)
        cache.set("key", value)
        value = cache.get("key")  # None if expired or missing
    """

    def __init__(self, maxsize: int = 500, ttl: int = 3600) -> None:
        self._maxsize = maxsize
        self._ttl = ttl  # 秒
        self._store: Dict[str, Tuple[float, Any]] = {}  # key -> (expire_at, value)
        self._access: Dict[str, float] = {}  # key -> last_access_time
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值，过期或不存在返回 None。"""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            expire_at, value = entry
            if time.time() > expire_at:
                del self._store[key]
                self._access.pop(key, None)
                self._misses += 1
                return None
            self._access[key] = time.time()
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """写入缓存。ttl 为 None 则用默认 TTL。"""
        with self._lock:
            # 淘汰旧数据
            if len(self._store) >= self._maxsize:
                self._evict()
            expire_at = time.time() + (ttl if ttl is not None else self._ttl)
            self._store[key] = (expire_at, value)
            self._access[key] = time.time()

    def clear(self) -> None:
        """清空缓存。"""
        with self._lock:
            self._store.clear()
            self._access.clear()
            self._hits = 0
            self._misses = 0

    def _evict(self) -> None:
        """淘汰最久未访问的条目 + 过期条目。"""
        now = time.time()
        # 先清理过期
        expired = [k for k, (exp, _) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
            self._access.pop(k, None)
        # 如果还超量，淘汰最久未访问
        if len(self._store) >= self._maxsize:
            sorted_keys = sorted(self._access, key=lambda k: self._access[k])
            to_remove = max(1, len(sorted_keys) // 10)  # 一次淘汰 10%
            for k in sorted_keys[:to_remove]:
                del self._store[k]
                del self._access[k]

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._store),
                "maxsize": self._maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / max(total, 1), 3),
            }


# ══════════════════════════════════════════════
#  全局缓存实例
# ══════════════════════════════════════════════

_llm_cache = TTLCache(maxsize=200, ttl=1800)  # LLM 回答缓存 30 分钟
_embed_cache = TTLCache(maxsize=2000, ttl=86400)  # Embedding 缓存 24 小时


def get_llm_cache() -> TTLCache:
    return _llm_cache


def get_embed_cache() -> TTLCache:
    return _embed_cache


# ══════════════════════════════════════════════
#  缓存 key 生成
# ══════════════════════════════════════════════


def make_llm_key(query: str, context_hash: str, lang: str, task: str) -> str:
    """生成 LLM 缓存 key：query + context_hash + lang + task。"""
    raw = f"{task}|{lang}|{query}|{context_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_embed_key(text: str, provider: str) -> str:
    """生成 Embedding 缓存 key：text + provider。"""
    raw = f"{provider}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_context_hash(texts: list) -> str:
    """对 context 文本列表生成短哈希。"""
    return hashlib.sha256(json.dumps(texts, sort_keys=True).encode()).hexdigest()[:16]


def get_cache_stats() -> Dict[str, Any]:
    """返回两层缓存的命中率统计。"""
    return {
        "llm": _llm_cache.stats,
        "embed": _embed_cache.stats,
    }
