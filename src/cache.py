"""查询缓存层。

提供两层缓存：
1. LLM 响应缓存 — 避免相同 context+query 重复调用 LLM
2. Embedding 缓存 — 避免相同文本重复调用 embedding API

使用 LRU + TTL 策略，适合单机部署。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import config


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

    def __init__(self, maxsize: int = 500, ttl: int = 3600, persist_path: Optional[str] = None) -> None:
        self._maxsize = maxsize
        self._ttl = ttl  # 秒
        self._store: Dict[str, Tuple[float, Any]] = {}  # key -> (expire_at, value)
        self._access: Dict[str, float] = {}  # key -> last_access_time
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._persist_path = persist_path
        self._dirty = False

        # Load from disk if persist path provided
        if self._persist_path:
            self._load()

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
            self._dirty = True
        # Save to disk outside the lock (throttled: only if persist_path set)
        if self._persist_path:
            self._save()

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

    def _save(self) -> None:
        """Persist cache to disk as JSON. Thread-safe: copies store under lock."""
        if not self._persist_path:
            return
        try:
            with self._lock:
                if not self._dirty:
                    return
                # Copy current store: {key: (expire_at, value)}
                data = {k: list(v) for k, v in self._store.items()}
                self._dirty = False
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass  # Silently ignore persistence errors

    def _load(self) -> None:
        """Load cache from disk on startup. Skips expired entries."""
        if not self._persist_path:
            return
        try:
            if not os.path.exists(self._persist_path):
                return
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = time.time()
            loaded = 0
            with self._lock:
                for key, entry in data.items():
                    if not isinstance(entry, list) or len(entry) != 2:
                        continue
                    expire_at, value = entry
                    if now < expire_at:
                        self._store[key] = (expire_at, value)
                        self._access[key] = now
                        loaded += 1
            if loaded > 0:
                import logging
                logging.getLogger(__name__).debug("TTLCache loaded %d entries from %s", loaded, self._persist_path)
        except Exception:
            pass  # Silently ignore load errors

    def flush(self) -> None:
        """Force save to disk immediately."""
        self._dirty = True
        self._save()

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = round(self._hits / max(total, 1), 3)
            # 估算 token 节省（假设每次缓存命中节省约 200 tokens）
            estimated_tokens_saved = self._hits * 200
            return {
                "size": len(self._store),
                "maxsize": self._maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "total_requests": total,
                "hit_rate": hit_rate,
                "hit_rate_pct": f"{hit_rate * 100:.1f}%",
                "estimated_tokens_saved": estimated_tokens_saved,
                "ttl_seconds": self._ttl,
                "efficiency": "高" if hit_rate > 0.5 else ("中" if hit_rate > 0.2 else "低"),
            }


# ══════════════════════════════════════════════
#  全局缓存实例
# ══════════════════════════════════════════════

_llm_cache = TTLCache(maxsize=200, ttl=1800, persist_path=str(config.DATA_DIR / "cache_llm.json"))  # LLM 回答缓存 30 分钟
_embed_cache = TTLCache(maxsize=2000, ttl=86400, persist_path=str(config.DATA_DIR / "cache_embed.json"))  # Embedding 缓存 24 小时


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
