"""Config 模块单元测试。"""

from __future__ import annotations

import pytest


class TestConfig:
    def test_config_imports(self):
        """config.py 能正常导入。"""
        import config
        assert config.PROJECT_ROOT.exists()
        assert config.CHUNK_SIZE > 0
        assert config.LLM_MODEL

    def test_default_values(self):
        """默认值合理性检查。"""
        import config
        assert config.CHUNK_SIZE == 1000
        assert config.CHUNK_OVERLAP == 200
        assert config.RAG_TOP_K == 5
        assert config.API_PORT == 8000
        assert config.RRF_K == 60

    def test_summary_contains_keys(self):
        """summary() 返回所有关键字段。"""
        import config
        s = config.summary()
        assert "LLM_MODEL" in s
        assert "EMBEDDING_PROVIDER" in s
        assert "RAG_TOP_K" in s
        assert "CACHE_ENABLED" in s

    def test_cache_defaults(self):
        """缓存默认配置。"""
        import config
        assert config.CACHE_ENABLED is False  # 测试环境关闭缓存
        assert config.CACHE_LLM_TTL == 1800
        assert config.CACHE_EMBED_TTL == 86400

    def test_task_model_fallback(self):
        """任务模型默认回退到 LLM_MODEL。"""
        import config
        assert config.LLM_QA_MODEL == config.LLM_MODEL
        assert config.LLM_SUMMARY_MODEL == config.LLM_MODEL
        assert config.LLM_SURVEY_MODEL == config.LLM_MODEL
