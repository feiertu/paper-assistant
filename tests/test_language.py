"""语言检测单元测试。"""

from __future__ import annotations

import pytest

from src.parse.language import detect_language


class TestLanguageDetection:
    def test_chinese_text(self):
        result = detect_language("这是一个关于深度学习的论文摘要，讨论了transformer架构在自然语言处理中的应用。")
        assert result["lang"] == "zh"
        assert result["cjk_ratio"] > 0.1

    def test_english_text(self):
        result = detect_language("This paper presents a novel approach to spatial reasoning in vision-language models.")
        assert result["lang"] == "en"
        assert result["cjk_ratio"] < 0.1

    def test_mixed_but_mostly_english(self):
        # 少量中文夹杂在英文中
        text = "We propose a method called 深度学习 for image classification tasks."
        result = detect_language(text)
        # CJK 字符比例较低
        assert result["cjk_ratio"] < 0.5

    def test_empty_text(self):
        result = detect_language("")
        assert result["lang"] == "en"
        assert result["total_chars"] == 0

    def test_cjk_count(self):
        text = "你好世界"  # 4 CJK chars
        result = detect_language(text)
        assert result["cjk_ratio"] == 1.0
        assert result["lang"] == "zh"
