"""论文语言检测。

简单启发式：根据解析后的 JSON 文本中中文字符占比判断语言。
阈值 > 10% 中文字符 → "zh"，否则 "en"。
"""

from __future__ import annotations

import re
from typing import Any, Dict


# Unicode 中文字符范围
_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


def detect_language(text: str) -> Dict[str, Any]:
    """检测单段文本的语言。

    Returns:
        {"lang": "zh"|"en", "cjk_ratio": float, "total_chars": int}
    """
    total = len(text)
    if total == 0:
        return {"lang": "en", "cjk_ratio": 0.0, "total_chars": 0}
    cjk_count = len(_CJK_RE.findall(text))
    ratio = cjk_count / total
    lang = "zh" if ratio > 0.10 else "en"
    return {"lang": lang, "cjk_ratio": round(ratio, 4), "total_chars": total}


def detect_json_language(data: Dict[str, Any]) -> Dict[str, Any]:
    """对 parsed JSON 整体检测语言。

    收集所有 section/subsection 的 content 拼接后检测。
    """
    texts = []
    for sec in data.get("sections", []) or []:
        if sec.get("content"):
            texts.append(sec["content"])
        for sub in sec.get("subsections", []) or []:
            if sub.get("content"):
                texts.append(sub["content"])

    full_text = " ".join(texts)
    result = detect_language(full_text)
    result["title"] = data.get("metadata", {}).get("title", "")
    return result
