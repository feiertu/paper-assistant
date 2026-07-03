"""Paper Assistant Streamlit UI。

启动：
    streamlit run ui/app.py --server.address 0.0.0.0 --server.port 8501
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保项目根在 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

import config
from src.cache import get_cache_stats
from src.db import get_dao
from src.rag import (
    answer_rag_stream,
    get_store_stats,
    ingest_parsed_dir,
    list_papers,
    recommend_similar,
    reset_store,
    retrieve,
    summarize_paper,
    survey,
)

# ── 页面配置 ──

st.set_page_config(
    page_title=config.UI_TITLE,
    page_icon="📚",
    layout="wide",
)

# ── 样式 ──

st.markdown("""
<style>
.block-container {padding-top: 2rem;}
.sidebar .sidebar-content {padding-top: 2rem;}
.citation {color: #888; font-size: 0.85em;}
.progress-text {font-size: 0.9em; color: #666;}
</style>
""", unsafe_allow_html=True)

# ── 侧边栏 ──

st.sidebar.title("📚 Paper Assistant")

page = st.sidebar.radio(
    "导航",
    ["🤖 Agent 助手", "💬 RAG 问答", "📝 论文摘要", "📊 综述生成",
     "📚 论文列表", "🔗 引用关系", "🔍 论文推荐", "📄 PDF 预览",
     "📥 数据入库", "📤 数据导出", "🕐 查询历史", "⚙️ 系统管理"],
)

st.sidebar.divider()

# 状态栏
try:
    stats = get_store_stats()
    st.sidebar.metric("论文 chunks", stats["count"])
except Exception:
    st.sidebar.warning("向量库未连接")

st.sidebar.caption(f"LLM: {config.LLM_MODEL}")
st.sidebar.caption(f"Embedding: {config.EMBEDDING_PROVIDER}")

# ══════════════════════════════════════════════
#  页面 0: Agent 助手
# ══════════════════════════════════════════════

if page == "🤖 Agent 助手":
    st.title("🤖 Agent 智能助手")

    st.markdown("""
    Agent 能够自主使用工具（搜索/摘要/对比/引用分析），进行**多步推理**，
    处理复杂的研究问题。例如：
    > "找出关于 RLBench 的论文，比较它们的核心方法，推荐相似的研究"
    """)

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_area(
            "输入你的研究问题",
            placeholder="例如：找出引用 SpatialClaw 的论文，对比它们在 RLBench 上的表现",
            height=80,
        )
    with col2:
        lang = st.selectbox("语言", ["zh", "en"], format_func=lambda x: "中文" if x == "zh" else "English")
        max_iter = st.slider("最大推理步数", 1, 20, 10)

    if st.button("🤖 开始分析", type="primary", disabled=not query.strip()):
        from src.agent.openai_agent import run_agent_stream

        # 容器
        reasoning_container = st.container()
        answer_placeholder = st.empty()

        step_count = 0
        final_answer = ""

        try:
            for event in run_agent_stream(
                query=query, lang=lang, max_iterations=max_iter,
            ):
                e = event if hasattr(event, 'model_dump') else event

                if e.type == "thinking":
                    with reasoning_container:
                        st.caption(f"💭 {e.content}")

                elif e.type == "tool_call":
                    step_count += 1
                    with reasoning_container:
                        with st.expander(
                            f"🔧 Step {step_count}: {e.tool}",
                            expanded=True,
                        ):
                            if e.args:
                                st.caption(f"参数: {json.dumps(e.args, ensure_ascii=False)}")
                            st.info("执行中…")

                elif e.type == "tool_result":
                    with reasoning_container:
                        result_text = e.result or ""
                        if len(result_text) > 800:
                            result_text = result_text[:800] + "…"
                        st.caption(f"✅ {e.tool} 完成")
                        st.text(result_text)

                elif e.type == "error":
                    with reasoning_container:
                        st.warning(f"⚠️ {e.tool}: {e.message}")

                elif e.type == "answer_chunk":
                    final_answer += e.content
                    answer_placeholder.markdown(final_answer)

                elif e.type == "usage":
                    st.caption(
                        f"📊 Token: {e.total_tokens} | "
                        f"工具调用: {e.steps} | "
                        f"耗时: {e.duration_ms}ms"
                    )

                elif e.type == "done":
                    pass  # 流结束

        except Exception as ex:
            st.error(f"Agent 执行错误: {ex}")

        if final_answer.strip():
            answer_placeholder.markdown(final_answer)
        else:
            st.warning("Agent 未能生成有效答案，请检查查询或论文数据。")

# ══════════════════════════════════════════════
#  页面 1: RAG 问答
# ══════════════════════════════════════════════

if page == "💬 RAG 问答":
    st.title("💬 RAG 论文问答")

    col1, col2 = st.columns([2, 1])
    with col1:
        query = st.text_area("输入你的问题", placeholder="例如：SpatialClaw 方法的核心创新是什么？", height=80)
    with col2:
        top_k = st.number_input("检索条数", min_value=1, max_value=20, value=config.RAG_TOP_K)
        lang = st.selectbox("语言", ["zh", "en"], format_func=lambda x: "中文" if x == "zh" else "English")

    if st.button("🔍 提问", type="primary", disabled=not query.strip()):
        # 先显示命中文档
        with st.status("检索中…", expanded=False) as status:
            result = retrieve(query, top_k=top_k)
            hits = result.get("hits", [])
            status.update(label=f"检索到 {len(hits)} 条相关片段", state="complete")

        if hits:
            with st.expander(f"📎 检索命中 ({len(hits)} 条)", expanded=False):
                for i, hit in enumerate(hits, 1):
                    meta = hit.get("metadata") or {}
                    st.markdown(f"**[{i}] {meta.get('section_title', '')}** — p.{meta.get('page', '?')}")
                    st.caption(hit.get("document", "")[:300] + "…")
                    st.divider()

        # 流式输出回答
        st.subheader("🤖 回答")
        placeholder = st.empty()
        full_answer = ""
        for token in answer_rag_stream(query, top_k=top_k, lang=lang):
            full_answer += token
            placeholder.markdown(full_answer)

# ══════════════════════════════════════════════
#  页面 2: 论文摘要
# ══════════════════════════════════════════════

elif page == "📝 论文摘要":
    st.title("📝 单论文摘要")

    papers = list_papers()
    if not papers:
        st.info("向量库中暂无论文。请先到「数据入库」页面导入论文。")
    else:
        paper_options = {f"{p['arxiv_id']} — {p['title'][:60]}" : p["arxiv_id"] for p in papers}
        selected = st.selectbox("选择论文", list(paper_options.keys()))
        lang = st.selectbox("摘要语言", ["zh", "en"], format_func=lambda x: "中文" if x == "zh" else "English")

        if st.button("📝 生成摘要", type="primary"):
            with st.spinner("生成中…"):
                arxiv_id = paper_options[selected]
                result = summarize_paper(arxiv_id, lang=lang)
            st.subheader("📄 摘要")
            st.markdown(result)

# ══════════════════════════════════════════════
#  页面 3: 综述生成
# ══════════════════════════════════════════════

elif page == "📊 综述生成":
    st.title("📊 多论文综述")

    query = st.text_input("搜索主题", placeholder="例如：spatial reasoning, VLM, agent")
    col1, col2 = st.columns(2)
    with col1:
        top_k = st.number_input("检索条数", min_value=5, max_value=50, value=15)
    with col2:
        lang = st.selectbox("语言", ["zh", "en"], format_func=lambda x: "中文" if x == "zh" else "English")

    if st.button("📊 生成综述", type="primary", disabled=not query.strip()):
        with st.spinner("检索并生成综述…"):
            result = survey(query, top_k=top_k, lang=lang)
        st.subheader("📋 综述")
        st.markdown(result)

# ══════════════════════════════════════════════
#  页面 4: 论文列表（支持搜索/过滤）
# ══════════════════════════════════════════════

elif page == "📚 论文列表":
    st.title("📚 论文搜索")

    dao = get_dao("paper")

    # ── 搜索栏 ──
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        keyword = st.text_input("🔍 关键词搜索", placeholder="输入关键词搜索标题/摘要/作者…")
    with col2:
        author = st.text_input("👤 作者", placeholder="模糊匹配")
    with col3:
        sort_by = st.selectbox("排序", ["created_at", "title", "published"],
                               format_func=lambda x: {"created_at": "入库时间", "title": "标题", "published": "发布日期"}[x])

    col4, col5, col6, col7 = st.columns(4)
    with col4:
        year_from = st.text_input("年份从", placeholder="2020")
    with col5:
        year_to = st.text_input("年至", placeholder="2025")
    with col6:
        source = st.selectbox("来源", ["", "arxiv", "grobid", "pymupdf", "manual"],
                              format_func=lambda x: x or "全部")
    with col7:
        status = st.selectbox("状态", ["", "ingested", "pending", "failed"],
                              format_func=lambda x: {"": "全部", "ingested": "✅ 已入库", "pending": "⏳ 待处理", "failed": "❌ 失败"}[x])

    limit = st.slider("显示条数", 10, 200, 50)

    if st.button("🔍 搜索", type="primary"):
        db_papers = dao.search(
            keyword=keyword, limit=limit, author=author,
            year_from=year_from, year_to=year_to,
            source=source, status=status, sort_by=sort_by,
        )
    else:
        db_papers = dao.find_all(limit=limit)

    if not db_papers:
        st.info("未找到匹配的论文。")
    else:
        st.metric("结果", len(db_papers))
        for p in db_papers:
            with st.container():
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"**{p.title or p.arxiv_id}**")
                    st.caption(f"{p.arxiv_id} | {p.authors[:80] if p.authors else '未知作者'} | {p.published}")
                    if p.abstract:
                        with st.expander("📄 摘要"):
                            st.caption(p.abstract[:500])
                with col2:
                    st.caption(f"chunks: {p.chunk_count}")
                    st.caption(f"状态: {'✅' if p.ingest_status == 'ingested' else '⏳'}")
                st.divider()

# ══════════════════════════════════════════════
#  页面 4b: 引用关系
# ══════════════════════════════════════════════

elif page == "🔗 引用关系":
    st.title("🔗 引用关系图")

    papers = list_papers()
    if not papers:
        st.info("暂无论文。请先导入数据。")
    else:
        paper_options = {f"{p['arxiv_id']} — {p['title'][:60]}" : p["arxiv_id"] for p in papers}
        selected = st.selectbox("选择论文", list(paper_options.keys()))

        arxiv_id = paper_options[selected]

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔗 查看引用关系", type="primary"):
                pass  # 被下面的 st.spinner 处理
        with col2:
            if st.button("🔄 提取全部引用", type="secondary"):
                from src.parse.citations import batch_extract_citations
                with st.spinner("提取中…"):
                    result = batch_extract_citations()
                st.success(f"处理 {result['processed']} 篇论文, 新增 {result['citations']} 条引用")

        # 显示引用图
        dao = get_dao("citation")
        graph = dao.get_graph(arxiv_id)

        tab1, tab2 = st.tabs([f"📤 引用了他文 ({len(graph['cites'])})",
                               f"📥 被他文引用 ({len(graph['cited_by'])})"])

        with tab1:
            if graph["cites"]:
                for i, cite in enumerate(graph["cites"], 1):
                    with st.container():
                        badge = "✅" if cite["in_db"] else "🌐"
                        st.markdown(f"**[{i}] {badge} {cite['cited_title'] or cite['cited_arxiv_id']}**")
                        st.caption(f"arXiv: {cite['cited_arxiv_id']}")
                        if cite["context"]:
                            with st.expander("引用上下文"):
                                st.caption(cite["context"][:300])
                        st.divider()
            else:
                st.info("未找到引用记录。点「提取全部引用」自动分析。")

        with tab2:
            if graph["cited_by"]:
                for i, cite in enumerate(graph["cited_by"], 1):
                    with st.container():
                        badge = "✅" if cite["in_db"] else "🌐"
                        st.markdown(f"**[{i}] {badge} {cite['citing_title'] or cite['citing_arxiv_id']}**")
                        st.caption(f"arXiv: {cite['citing_arxiv_id']}")
                        if cite["context"]:
                            with st.expander("引用上下文"):
                                st.caption(cite["context"][:300])
                        st.divider()
            else:
                st.info("暂无其他论文引用此篇。")

        # 统计
        st.divider()
        cit_stats = dao.count()
        st.metric("全库引用关系总数", cit_stats)

# ══════════════════════════════════════════════
#  页面 4c: 论文推荐
# ══════════════════════════════════════════════

elif page == "🔍 论文推荐":
    st.title("🔍 论文推荐")

    papers = list_papers()
    if not papers:
        st.info("向量库中暂无论文，无法推荐。")
    else:
        paper_options = {f"{p['arxiv_id']} — {p['title'][:60]}" : p["arxiv_id"] for p in papers}
        selected = st.selectbox("选择一篇论文，查看相似推荐", list(paper_options.keys()))

        top_k = st.slider("推荐数量", min_value=2, max_value=15, value=5)

        if st.button("🔍 查找相似论文", type="primary"):
            arxiv_id = paper_options[selected]
            with st.spinner("搜索中…"):
                try:
                    result = recommend_similar(arxiv_id, top_k=top_k)
                except Exception as e:
                    st.error(f"推荐失败: {e}")
                    result = []

            if result:
                st.subheader(f"与 {arxiv_id} 相似的论文")
                for i, r in enumerate(result, 1):
                    with st.container():
                        st.markdown(f"**[{i}] {r['title']}**")
                        st.caption(f"arxiv: {r['arxiv_id']} | "
                                   f"相似度: {r['score']:.4f} | "
                                   f"共同片段: {r['shared_chunks']}")
                        st.divider()
            else:
                st.warning("未找到相似论文")

# ══════════════════════════════════════════════
#  页面 4c: PDF 预览
# ══════════════════════════════════════════════

elif page == "📄 PDF 预览":
    st.title("📄 PDF 在线预览")

    papers = list_papers()
    if not papers:
        st.info("暂无论文。请先导入数据。")
    else:
        paper_options = {f"{p['arxiv_id']} — {p['title'][:60]}" : p["arxiv_id"] for p in papers}
        selected = st.selectbox("选择论文", list(paper_options.keys()))
        arxiv_id = paper_options[selected]

        # 显示论文信息
        dao = get_dao("paper")
        paper = dao.find_by_arxiv_id(arxiv_id)
        if paper:
            st.markdown(f"**{paper.title}**")
            st.caption(f"作者: {paper.authors or '未知'} | 发布: {paper.published or '未知'}")

        # 嵌入 PDF
        pdf_url = f"/api/papers/{arxiv_id}/pdf"
        pdf_path = config.RAW_PDF_DIR / f"{arxiv_id}.pdf"
        if pdf_path.exists():
            import base64
            with open(pdf_path, "rb") as f:
                base64_pdf = base64.b64encode(f.read()).decode("utf-8")
            pdf_display = f"""
            <iframe src="data:application/pdf;base64,{base64_pdf}"
                    width="100%" height="800px" type="application/pdf"
                    style="border: 1px solid #ddd; border-radius: 8px;">
            </iframe>
            """
            st.markdown(pdf_display, unsafe_allow_html=True)
        else:
            st.warning(f"PDF 文件不存在: {pdf_path}")

# ══════════════════════════════════════════════
#  页面 4d: 数据导出
# ══════════════════════════════════════════════

elif page == "📤 数据导出":
    st.title("📤 数据导出")

    tab1, tab2 = st.tabs(["📄 论文导出", "🕐 查询导出"])

    with tab1:
        st.subheader("导出论文数据")
        fmt = st.selectbox("导出格式", ["json", "csv", "bibtex"], key="paper_fmt")
        limit = st.number_input("导出数量", min_value=10, max_value=1000, value=200, key="paper_limit")

        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("📥 导出论文", type="primary"):
                dao = get_dao("paper")
                papers = dao.find_all(limit=limit)

                if fmt == "json":
                    import json as _json
                    data = _json.dumps([p.to_dict() for p in papers], ensure_ascii=False, indent=2)
                    st.download_button("⬇ 下载 papers.json", data, "papers.json", "application/json")
                    st.success(f"已准备 {len(papers)} 条记录")

                elif fmt == "csv":
                    import io, csv as _csv
                    output = io.StringIO()
                    writer = _csv.writer(output)
                    writer.writerow(["id", "arxiv_id", "title", "authors", "abstract",
                                     "published", "source", "ingest_status", "chunk_count"])
                    for p in papers:
                        writer.writerow([p.id, p.arxiv_id, p.title, p.authors, p.abstract,
                                         p.published, p.source, p.ingest_status, p.chunk_count])
                    st.download_button("⬇ 下载 papers.csv", output.getvalue(), "papers.csv", "text/csv")
                    st.success(f"已准备 {len(papers)} 条记录")

                elif fmt == "bibtex":
                    entries = []
                    for p in papers:
                        author_first = p.authors.split(",")[0].strip().split()[-1] if p.authors else "Unknown"
                        key = f"{author_first}{p.published[:4] if p.published else '0000'}"
                        entries.append(
                            f"@article{{{key},\n"
                            f"  title = {{{{{p.title}}}}},\n"
                            f"  author = {{{{{p.authors}}}}},\n"
                            f"  year = {{{{{p.published[:4] if p.published else '????'}}}}},\n"
                            f"  eprint = {{{{{p.arxiv_id}}}}},\n"
                            f"}}"
                        )
                    bib_content = "\n\n".join(entries)
                    st.download_button("⬇ 下载 papers.bib", bib_content, "papers.bib", "text/plain")
                    st.success(f"已准备 {len(papers)} 条记录")

    with tab2:
        st.subheader("导出查询历史")
        fmt2 = st.selectbox("导出格式", ["json", "csv"], key="query_fmt")
        limit2 = st.number_input("导出数量", min_value=10, max_value=1000, value=100, key="query_limit")

        if st.button("📥 导出查询", type="primary"):
            dao = get_dao("query")
            records = dao.find_recent(limit=limit2)

            if fmt2 == "json":
                import json as _json
                data = _json.dumps([
                    {"id": r.id, "query": r.query_text, "answer": r.answer_text,
                     "lang": r.lang, "hits": r.hit_count, "time": r.created_at}
                    for r in records
                ], ensure_ascii=False, indent=2)
                st.download_button("⬇ 下载 queries.json", data, "queries.json", "application/json")
                st.success(f"已准备 {len(records)} 条记录")

            elif fmt2 == "csv":
                import io, csv as _csv
                output = io.StringIO()
                writer = _csv.writer(output)
                writer.writerow(["id", "query_text", "answer_text", "lang", "hit_count", "created_at"])
                for r in records:
                    writer.writerow([r.id, r.query_text, r.answer_text, r.lang, r.hit_count, r.created_at])
                st.download_button("⬇ 下载 queries.csv", output.getvalue(), "queries.csv", "text/csv")
                st.success(f"已准备 {len(records)} 条记录")

# ══════════════════════════════════════════════
#  页面 5: 查询历史
# ══════════════════════════════════════════════

elif page == "🕐 查询历史":
    st.title("🕐 查询历史")

    dao = get_dao("query")
    records = dao.find_recent(limit=50)
    if not records:
        st.info("暂无查询记录。")
    else:
        st.metric("总计", len(records))
        if st.button("🗑️ 清空历史", type="secondary"):
            dao.clear()
            st.rerun()

        for r in records:
            with st.expander(f"🔍 {r.query_text[:60]}… — {r.created_at}", expanded=False):
                st.caption(f"语言: {r.lang} | 命中: {r.hit_count} 条")
                st.markdown(r.answer_text[:500] + ("…" if len(r.answer_text) > 500 else ""))

# ══════════════════════════════════════════════
#  页面 6: 数据入库
# ══════════════════════════════════════════════

elif page == "📥 数据入库":
    st.title("📥 数据入库")

    # 当前状态
    stats = get_store_stats()
    st.metric("向量库 chunks", stats["count"])
    st.caption(f"Collection: {stats['collection_name']}")

    papers = list_papers()
    if papers:
        st.subheader(f"已入库论文 ({len(papers)} 篇)")
        for p in papers:
            st.text(f"• {p['arxiv_id']}: {p['title'][:80]}")

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🔄 入库论文", type="primary", use_container_width=True):
            progress_bar = st.progress(0, text="准备入库…")
            status_text = st.empty()

            # 导入 logging 用于进度捕获
            from src.logging_config import get_logger
            _log = get_logger("ui.ingest")

            status_text.caption("📂 扫描解析目录…")
            progress_bar.progress(10, text="扫描解析目录…")

            try:
                result = ingest_parsed_dir()
            except Exception as e:
                progress_bar.progress(100, text="❌ 入库失败")
                st.error(str(e))
            else:
                progress_bar.progress(70, text="写入数据库…")
                progress_bar.progress(100, text="✅ 入库完成")
                status_text.empty()
                if "error" in result:
                    st.error(result["error"])
                else:
                    st.success(f"✅ {result['papers']} 篇论文，{result['chunks']} 个 chunks 已入库！")
                    st.rerun()

    with col2:
        if st.button("🗑️ 清空重建", type="secondary", use_container_width=True):
            if st.warning("确认清空全部向量数据？"):
                col_confirm, _ = st.columns([1, 3])
                with col_confirm:
                    if st.button("⚠️ 确认清空", type="primary"):
                        reset_store()
                        with st.spinner("重建中…"):
                            result = ingest_parsed_dir()
                        if "error" in result:
                            st.error(result["error"])
                        else:
                            st.success(f"✅ 重建完成：{result['papers']} 篇论文，{result['chunks']} chunks")
                            st.rerun()

# ══════════════════════════════════════════════
#  页面 7: 系统管理
# ══════════════════════════════════════════════

elif page == "⚙️ 系统管理":
    st.title("⚙️ 系统管理")

    # ── 分标签页 ──
    tab1, tab2, tab3 = st.tabs(["📊 状态", "💾 备份", "⚙️ 配置"])

    with tab1:
        st.subheader("向量库")
        stats = get_store_stats()
        st.json(stats)

        st.subheader("缓存")
        cache_stats = get_cache_stats()
        col1, col2 = st.columns(2)
        with col1:
            st.metric("LLM 命中率", f"{cache_stats['llm']['hit_rate']*100:.1f}%")
            st.caption(f"hits: {cache_stats['llm']['hits']} | misses: {cache_stats['llm']['misses']}")
        with col2:
            st.metric("Embed 命中率", f"{cache_stats['embed']['hit_rate']*100:.1f}%")
            st.caption(f"hits: {cache_stats['embed']['hits']} | misses: {cache_stats['embed']['misses']}")

        if st.button("🗑️ 清空缓存", type="secondary"):
            from src.cache import get_llm_cache as _lc, get_embed_cache as _ec
            _lc().clear()
            _ec().clear()
            st.success("缓存已清空")
            st.rerun()

    with tab2:
        st.subheader("向量库备份")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 创建备份", type="primary", use_container_width=True):
                import shutil
                from datetime import datetime
                backup_dir = config.DATA_DIR / "chroma_backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
                if config.CHROMA_DIR.exists():
                    with st.spinner("备份中…"):
                        shutil.copytree(str(config.CHROMA_DIR), str(backup_dir))
                    st.success(f"备份完成: {backup_dir.name}")
                else:
                    st.error("Chroma 目录不存在")

        # 列出现有备份
        backup_root = config.DATA_DIR / "chroma_backup"
        if backup_root.exists():
            backups = sorted(backup_root.iterdir(), key=lambda p: p.name, reverse=True)
            st.subheader(f"现有备份 ({len(backups)})")
            for b in backups:
                if b.is_dir():
                    size = sum(f.stat().st_size for f in b.rglob("*") if f.is_file())
                    col1, col2, col3 = st.columns([3, 1, 1])
                    with col1:
                        st.text(f"📁 {b.name}")
                    with col2:
                        st.caption(f"{size/1024/1024:.1f} MB")
                    with col3:
                        if st.button("🔄 恢复", key=f"restore_{b.name}"):
                            import shutil
                            if config.CHROMA_DIR.exists():
                                shutil.rmtree(str(config.CHROMA_DIR))
                            shutil.copytree(str(b), str(config.CHROMA_DIR))
                            st.success(f"已从 {b.name} 恢复")
                            st.rerun()

    with tab3:
        st.subheader("配置")
        st.json(config.summary())

        st.divider()

        if st.button("🗑️ 清空向量库", type="secondary"):
            st.warning("确认清空？此操作不可逆！")
            if st.button("⚠️ 确认清空全部数据", type="primary"):
                result = reset_store()
                if "error" in result:
                    st.error(result["error"])
                else:
                    st.success("向量库已清空")
                    st.rerun()
