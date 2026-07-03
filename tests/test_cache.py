"""缓存模块单元测试。"""

from __future__ import annotations

import time

import pytest

from src.cache import TTLCache, make_llm_key, make_embed_key, make_context_hash


class TestTTLCache:
    def test_set_get(self):
        cache = TTLCache(maxsize=10, ttl=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_miss(self):
        cache = TTLCache(maxsize=10, ttl=60)
        assert cache.get("nonexistent") is None

    def test_expiry(self):
        cache = TTLCache(maxsize=10, ttl=0.01)
        cache.set("key1", "value1")
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_maxsize_eviction(self):
        cache = TTLCache(maxsize=5, ttl=60)
        for i in range(10):
            cache.set(f"key{i}", f"value{i}")
        assert cache.stats["size"] <= 5

    def test_stats(self):
        cache = TTLCache(maxsize=10, ttl=60)
        cache.set("a", 1)
        cache.get("a")
        cache.get("b")  # miss
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_clear(self):
        cache = TTLCache(maxsize=10, ttl=60)
        cache.set("a", 1)
        cache.clear()
        assert cache.get("a") is None
        assert cache.stats["size"] == 0


class TestCacheKeys:
    def test_make_llm_key_different(self):
        k1 = make_llm_key("query", "hash1", "zh", "qa")
        k2 = make_llm_key("query", "hash2", "zh", "qa")
        assert k1 != k2

    def test_make_llm_key_same(self):
        k1 = make_llm_key("query", "hash", "zh", "qa")
        k2 = make_llm_key("query", "hash", "zh", "qa")
        assert k1 == k2

    def test_make_embed_key(self):
        k1 = make_embed_key("hello world", "openai")
        k2 = make_embed_key("hello world", "voyage")
        assert k1 != k2

    def test_context_hash_deterministic(self):
        h1 = make_context_hash(["a", "b"])
        h2 = make_context_hash(["a", "b"])
        assert h1 == h2
