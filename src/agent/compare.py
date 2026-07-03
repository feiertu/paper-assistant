"""论文对比函数。

给定两个 arXiv ID，从 parsed JSON 加载全文，调 LLM 生成结构化对比分析。
"""

from __future__ import annotations

import json

import config
from src.logging_config import get_logger

logger = get_logger(__name__)


def compare_papers(
    arxiv_id1: str,
    arxiv_id2: str,
    lang: str = "zh",
    max_chars: int = 6000,
) -> str:
    """对比两篇论文的异同。

    从 data/parsed/{arxiv_id}.json 加载全文，
    截断后调 LLM 生成四段式对比：问题/方法/结果/意义。

    Args:
        arxiv_id1: 论文 A 的 arXiv ID
        arxiv_id2: 论文 B 的 arXiv ID
        lang: "zh" 或 "en"
        max_chars: 每篇论文传给 LLM 的文本上限

    Returns:
        对比分析文本，或错误提示
    """
    text1 = _load_paper_text(arxiv_id1, max_chars)
    if text1.startswith("⚠️"):
        return f"论文 A 加载失败: {text1}"

    text2 = _load_paper_text(arxiv_id2, max_chars)
    if text2.startswith("⚠️"):
        return f"论文 B 加载失败: {text2}"

    from src.llm import get_llm, prompts

    llm = get_llm()
    template = prompts.COMPARE_PROMPT_ZH if lang == "zh" else prompts.COMPARE_PROMPT_EN
    user_prompt = template.format(text1=text1, text2=text2)

    try:
        return llm.chat(
            [{"role": "user", "content": user_prompt}],
            model=config.LLM_SUMMARY_MODEL,
        )
    except Exception as e:
        logger.error("对比失败 %s vs %s: %s", arxiv_id1, arxiv_id2, e)
        return f"对比失败: {e}"


def _load_paper_text(arxiv_id: str, max_chars: int) -> str:
    """从 parsed JSON 加载论文正文文本。"""
    json_path = config.PARSED_DIR / f"{arxiv_id}.json"
    if not json_path.exists():
        return f"⚠️ 未找到解析文件: {json_path}"

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"⚠️ 无法读取: {e}"

    sections = data.get("sections", [])
    text_parts = []
    for sec in sections:
        content = sec.get("content", "").strip()
        if content:
            text_parts.append(content)
        for sub in sec.get("subsections", []):
            sc = sub.get("content", "").strip()
            if sc:
                text_parts.append(sc)

    full_text = "\n\n".join(text_parts)
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "…"

    return full_text
