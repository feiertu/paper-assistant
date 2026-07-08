"""Agent 工具定义。

7 个 LangChain @tool，LLM 自主选择调用。
所有工具返回字符串（Agent 循环要求），内部 try/except 保证不抛异常。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langchain.tools import tool

from src.logging_config import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════
#  工具 1: search — 统一搜索入口
# ══════════════════════════════════════════════

@tool
def search(
    query: str,
    mode: str = "fts",
    top_k: int = 5,
    author: str = "",
    year_from: str = "",
    year_to: str = "",
) -> str:
    """搜索论文。支持三种模式：
    - mode="fts": 全文搜索（关键词匹配标题/作者/摘要）
    - mode="semantic": 向量语义搜索（根据含义检索相关内容）
    - mode="list": 列出已入库论文

    参数:
        query: 搜索关键词或语义查询文本
        mode: 搜索模式，可选 "fts" / "semantic" / "list"，默认 "fts"
        top_k: 返回数量，默认 5
        author: 作者名过滤（仅 fts 模式有效）
        year_from: 年份起始（仅 fts 模式有效）
        year_to: 年份截止（仅 fts 模式有效）

    返回:
        格式化的搜索结果文本
    """
    try:
        if mode == "semantic":
            from src.rag import retrieve
            result = retrieve(query, top_k=top_k)
            if "error" in result:
                return f"语义搜索失败: {result['error']}"
            hits = result.get("hits", [])
            if not hits:
                return "未找到语义相关的论文片段。"
            lines = []
            for i, hit in enumerate(hits, 1):
                meta = hit.get("metadata", {})
                doc = (hit.get("document") or "")[:400].replace("\n", " ")
                lines.append(
                    f"[{i}] {meta.get('arxiv_id','?')} | "
                    f"{meta.get('section_title','')} | "
                    f"p.{meta.get('page','?')}\n  {doc}"
                )
            return "\n\n".join(lines)

        elif mode == "list":
            from src.rag import list_papers
            papers = list_papers()
            if not papers:
                return "暂无已入库论文。"
            lines = [f"共 {len(papers)} 篇论文："]
            for p in papers[:top_k]:
                lines.append(f"  • {p['arxiv_id']}: {p['title'][:80]}")
            return "\n".join(lines)

        else:  # fts
            from src.db import get_dao
            dao = get_dao("paper")
            results = dao.search(
                keyword=query, limit=top_k,
                author=author, year_from=year_from, year_to=year_to,
            )
            if not results:
                return f"未找到匹配 '{query}' 的论文。"
            lines = [f"全文搜索 '{query}' 找到 {len(results)} 篇："]
            for p in results:
                lines.append(
                    f"  • {p.arxiv_id}: {p.title}\n"
                    f"    作者: {p.authors or '未知'} | "
                    f"日期: {p.published or '未知'} | "
                    f"摘要: {(p.abstract or '')[:150]}"
                )
            return "\n".join(lines)

    except Exception as e:
        logger.error("search 工具失败: %s", e)
        return f"搜索失败: {e}"


# ══════════════════════════════════════════════
#  工具 2: get_paper — 论文详情
# ══════════════════════════════════════════════

@tool
def get_paper(arxiv_id: str) -> str:
    """获取指定论文的完整元数据。

    参数:
        arxiv_id: 论文 arXiv ID，如 "2606.13673v1" 或 "2301.12345"

    返回:
        论文的标题、作者、摘要、发布日期、PDF 链接、入库状态等
    """
    try:
        from src.db import get_dao
        dao = get_dao("paper")
        p = dao.find_by_arxiv_id(arxiv_id)
        if not p:
            return f"未找到论文: {arxiv_id}"

        return (
            f"arXiv ID: {p.arxiv_id}\n"
            f"标题: {p.title}\n"
            f"作者: {p.authors or '未知'}\n"
            f"摘要: {p.abstract or '（无摘要）'}\n"
            f"发布日期: {p.published or '未知'}\n"
            f"来源: {p.source}\n"
            f"入库状态: {p.ingest_status} | chunks: {p.chunk_count}\n"
            f"PDF: {p.pdf_url or '无'}"
        )
    except Exception as e:
        logger.error("get_paper 工具失败: %s", e)
        return f"获取论文失败: {e}"


# ══════════════════════════════════════════════
#  工具 3: summarize_paper — 单文档摘要
# ══════════════════════════════════════════════

@tool
def summarize_paper(arxiv_id: str, lang: str = "zh") -> str:
    """对指定论文生成结构化摘要（三段式：问题/方法/结论）。

    参数:
        arxiv_id: 论文 arXiv ID
        lang: 输出语言，"zh" 中文或 "en" 英文，默认 "zh"

    返回:
        结构化摘要文本
    """
    try:
        from src.rag import summarize_paper as _summarize
        result = _summarize(arxiv_id, lang=lang)
        return result
    except Exception as e:
        logger.error("summarize_paper 工具失败: %s", e)
        return f"摘要生成失败: {e}"


# ══════════════════════════════════════════════
#  工具 4: get_citations — 引用关系图
# ══════════════════════════════════════════════

@tool
def get_citations(arxiv_id: str) -> str:
    """获取论文的引用关系图（引用了哪些论文 + 被哪些论文引用）。

    参数:
        arxiv_id: 论文 arXiv ID

    返回:
        格式化的引用关系文本
    """
    try:
        from src.db import get_dao
        dao = get_dao("citation")
        graph = dao.get_graph(arxiv_id)

        lines = [f"论文 {arxiv_id} 的引用关系：\n"]

        lines.append(f"引用了 {len(graph['cites'])} 篇论文：")
        for cite in graph["cites"][:10]:
            badge = "[DB]" if cite["in_db"] else "[WEB]"
            title = cite.get("cited_title") or cite.get("cited_arxiv_id") or "?"
            lines.append(f"  {badge} {cite['cited_arxiv_id']}: {title[:80]}")

        lines.append(f"\n被 {len(graph['cited_by'])} 篇论文引用：")
        for cite in graph["cited_by"][:10]:
            badge = "[DB]" if cite["in_db"] else "[WEB]"
            title = cite.get("citing_title") or cite.get("citing_arxiv_id") or "?"
            lines.append(f"  {badge} {cite['citing_arxiv_id']}: {title[:80]}")

        return "\n".join(lines)
    except Exception as e:
        logger.error("get_citations 工具失败: %s", e)
        return f"获取引用关系失败: {e}"


# ══════════════════════════════════════════════
#  工具 5: compare_papers — 论文对比
# ══════════════════════════════════════════════

@tool
def compare_papers(arxiv_id1: str, arxiv_id2: str, lang: str = "zh") -> str:
    """对比两篇论文的异同。生成四段式分析：问题/方法/结果/意义。

    参数:
        arxiv_id1: 第一篇论文的 arXiv ID
        arxiv_id2: 第二篇论文的 arXiv ID
        lang: 输出语言，默认 "zh"

    返回:
        结构化对比分析文本
    """
    try:
        from src.agent.compare import compare_papers as _compare
        return _compare(arxiv_id1, arxiv_id2, lang=lang)
    except Exception as e:
        logger.error("compare_papers 工具失败: %s", e)
        return f"对比失败: {e}"


# ══════════════════════════════════════════════
#  工具 6: recommend_similar — 相似论文推荐
# ══════════════════════════════════════════════

@tool
def recommend_similar(arxiv_id: str, top_k: int = 5) -> str:
    """根据向量相似度推荐与指定论文相似的论文。

    参数:
        arxiv_id: 论文 arXiv ID
        top_k: 推荐数量，默认 5

    返回:
        格式化的推荐列表（含相似度分数）
    """
    try:
        from src.rag import recommend_similar as _recommend
        results = _recommend(arxiv_id, top_k=top_k)
        if not results:
            return f"未找到与 {arxiv_id} 相似的论文。"
        lines = [f"与 {arxiv_id} 相似的论文 ({len(results)} 篇)："]
        for i, r in enumerate(results, 1):
            lines.append(
                f"  [{i}] {r['arxiv_id']}: {r['title'][:80]}\n"
                f"      相似度: {r['score']:.4f} | 共同片段: {r['shared_chunks']}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.error("recommend_similar 工具失败: %s", e)
        return f"推荐失败: {e}"


# ══════════════════════════════════════════════
#  工具 7: generate_survey — 综述 / 导出
# ══════════════════════════════════════════════

@tool
def generate_survey(
    topic: str,
    mode: str = "survey",
    top_k: int = 10,
    lang: str = "zh",
    fmt: str = "json",
) -> str:
    """生成多论文综述或导出论文数据。

    - mode="survey": 根据主题搜索论文，生成文献综述
    - mode="export": 导入论文元数据（JSON/CSV/BibTeX）

    参数:
        topic: 综述主题关键词或导出搜索关键词
        mode: "survey" 或 "export"
        top_k: 检索论文数（仅 survey 模式）
        lang: 输出语言
        fmt: 导出格式（仅 export 模式）："json" / "csv" / "bibtex"

    返回:
        综述文本或导出数据
    """
    try:
        if mode == "export":
            from src.db import get_dao
            dao = get_dao("paper")
            papers = dao.search(keyword=topic, limit=top_k)
            if not papers:
                return f"未找到与 '{topic}' 相关的论文。"

            if fmt == "json":
                data = [p.to_dict() for p in papers]
                return json.dumps(data, ensure_ascii=False, indent=2)
            elif fmt == "bibtex":
                entries = []
                for p in papers:
                    author_first = (p.authors or "Unknown").split(",")[0].strip().split()[-1] if p.authors else "Unknown"
                    key = f"{author_first}{p.published[:4] if p.published else '0000'}"
                    entries.append(
                        f"@article{{{key},\n"
                        f"  title = {{{{{p.title}}}}},\n"
                        f"  author = {{{{{p.authors or 'Unknown'}}}}},\n"
                        f"  year = {{{{{p.published[:4] if p.published else '????'}}}}},\n"
                        f"  eprint = {{{{{p.arxiv_id}}}}},\n"
                        f"}}"
                    )
                return "\n\n".join(entries)
            else:  # csv
                lines = ["id,arxiv_id,title,authors,abstract,published,source,status"]
                for p in papers:
                    lines.append(
                        f"{p.id},{p.arxiv_id},\"{p.title}\",\"{p.authors or ''}\","
                        f"\"{p.abstract or ''}\",{p.published or ''},{p.source},{p.ingest_status}"
                    )
                return "\n".join(lines)

        else:  # survey
            from src.rag import survey as _survey
            result = _survey(topic, top_k=top_k, lang=lang)
            return result

    except Exception as e:
        logger.error("generate_survey 工具失败: %s", e)
        return f"操作失败: {e}"


# ══════════════════════════════════════════════
#  工具集合
# ══════════════════════════════════════════════

ALL_TOOLS = [
    search,
    get_paper,
    summarize_paper,
    get_citations,
    compare_papers,
    recommend_similar,
    generate_survey,
]

TOOL_BY_NAME: Dict[str, Any] = {t.name: t for t in ALL_TOOLS}


def get_tool_by_name(name: str):
    """按名称获取工具对象。"""
    return TOOL_BY_NAME.get(name)


def get_tools_openai_format(tool_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """将工具转为 OpenAI function calling 格式。

    Args:
        tool_names: 启用的工具名列表，None 表示全部

    Returns:
        [{"type": "function", "function": {"name":..., "description":..., "parameters":...}}]
    """
    tools = ALL_TOOLS
    if tool_names:
        tools = [t for t in ALL_TOOLS if t.name in tool_names]
    result = []
    for t in tools:
        schema = t.args_schema.model_json_schema() if hasattr(t, 'args_schema') and t.args_schema else {}
        result.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": schema,
            },
        })
    return result
