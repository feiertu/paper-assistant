"""Paper Assistant — Perplexity × Semantic Scholar 风格 UI。

启动：streamlit run ui/app.py --server.address 0.0.0.0 --server.port 8501
"""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

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
from ui.styles import CSS

# ── 页面配置 ──

st.set_page_config(page_title=config.UI_TITLE, page_icon="📑", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

# ── 侧边栏 ──

with st.sidebar:
    st.markdown("## 📑 Paper Assistant")
    st.caption("RAG 学术论文智能助手")

    page = st.radio(
        "导航",
        ["🔎 智能问答", "🤖 Agent 分析", "📚 论文库", "📝 摘要 & 综述",
         "🔗 引用网络", "📤 数据", "⚙️ 系统"],
        label_visibility="collapsed",
    )

    st.divider()

    # 状态
    try:
        s = get_store_stats()
    except Exception:
        s = {"count": 0}
    col_a, col_b = st.columns(2)
    col_a.metric("📄 Chunks", s["count"])
    col_b.metric("🤖 Model", config.LLM_MODEL[:14] + "…" if len(config.LLM_MODEL) > 14 else config.LLM_MODEL)

    # 公网安全提示
    if not config.API_AUTH_ENABLED:
        st.divider()
        st.warning("⚠️ API 鉴权未启用，公网部署下任何人可操作数据，建议在 `.env` 中设置 `API_AUTH_ENABLED=true`", icon="🔓")


# ══════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════

def render_paper_card(p, show_abstract=True):
    """Semantic Scholar 风格论文卡片。"""
    status_badge = {
        "ingested": ('badge badge-success', '✅ 已入库'),
        "pending": ('badge badge-warning', '⏳ 待处理'),
        "failed": ('badge badge-muted', '❌ 失败'),
    }.get(p.ingest_status, ('badge badge-muted', p.ingest_status))

    html = f"""
    <div class="paper-card">
        <div class="title">{p.title or p.arxiv_id}</div>
        <div class="authors">{p.authors or '未知作者'}</div>
        <div class="meta">
            <span>📅 {p.published or '未知'}</span>
            <span>📎 {p.arxiv_id}</span>
            <span>🧩 {p.chunk_count} chunks</span>
            <span class="{status_badge[0]}">{status_badge[1]}</span>
        </div>
    """
    if show_abstract and p.abstract:
        html += f'<div class="abstract">{p.abstract[:400]}{"…" if len(p.abstract) > 400 else ""}</div>'
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_source_card(hit, idx):
    """Perplexity 风格的引用来源卡片。"""
    meta = hit.get("metadata", {})
    doc = (hit.get("document") or "")[:250]
    html = f"""
    <div class="source-card">
        <div class="source-title">[{idx}] {meta.get('section_title','') or meta.get('title','') or meta.get('arxiv_id','?')}</div>
        <div class="source-excerpt">{doc}{'…' if len(hit.get('document','')) > 250 else ''}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  页面 0: 智能问答（主页） — Perplexity 风格
# ══════════════════════════════════════════════════════════════

if page == "🔎 智能问答":
    # ── Hero 区域 ──
    st.markdown("""
    <div class="hero-search">
        <h1>用 AI 读懂每一篇论文</h1>
        <p>基于 RAG 的学术论文智能问答 — 搜索、理解、对比，像和专家对话一样</p>
    </div>
    """, unsafe_allow_html=True)

    col_q, col_s = st.columns([5, 1])
    with col_q:
        query = st.text_area(
            "提问",
            placeholder="试试问：SpatialClaw 的核心创新是什么？哪些论文使用了类似的 VLM 方法？",
            label_visibility="collapsed",
            height=68,
            key="qa_query",
        )
    with col_s:
        top_k = st.selectbox("精度", [3, 5, 10, 20], index=1, label_visibility="collapsed", key="qa_topk")

    col_btn, col_lang = st.columns([1, 4])
    with col_btn:
        ask = st.button("🔎 搜索回答", type="primary", use_container_width=True, disabled=not query.strip())
    with col_lang:
        lang_qa = st.selectbox("语言", ["zh", "en"], format_func=lambda x: "中文" if x == "zh" else "English",
                               label_visibility="collapsed")

    if ask:
        # ── 检索结果（折叠） ──
        with st.status(f"📚 检索相关知识…", expanded=False) as status:
            result = retrieve(query, top_k=top_k)
            hits = result.get("hits", [])
            status.update(label=f"找到 {len(hits)} 个相关片段", state="complete")

        if hits:
            with st.expander(f"📎 引用的论文片段（{len(hits)} 条）", expanded=False):
                for i, hit in enumerate(hits, 1):
                    render_source_card(hit, i)

        # ── 流式回答 ──
        st.markdown("### 💡 回答")
        answer_box = st.empty()
        full = ""
        for token in answer_rag_stream(query, top_k=top_k, lang=lang_qa):
            full += token
            answer_box.markdown(f"""
            <div class="chat-container">
                <div class="chat-bubble assistant">{full}</div>
            </div>
            """, unsafe_allow_html=True)

        if not full.strip():
            st.warning("未找到相关信息，请尝试修改问题或先导入更多论文。")

    # ── 没有提问时展示快捷入口 ──
    if not ask:
        st.divider()
        st.caption("💡 试试这些问题")
        examples = [
            "总结 RLBench 相关论文的核心方法",
            "对比 SpatialClaw 和传统 VLM 方法的异同",
            "哪些论文引用了 2606.13673v1？",
            "推荐与这篇论文相似的研究",
        ]
        cols = st.columns(4)
        for i, ex in enumerate(examples):
            with cols[i]:
                st.button(ex, key=f"ex_{i}", use_container_width=True,
                          on_click=lambda e=ex: st.session_state.update({"qa_query": e}))


# ══════════════════════════════════════════════════════════════
#  页面 1: Agent 分析
# ══════════════════════════════════════════════════════════════

elif page == "🤖 Agent 分析":
    st.title("🤖 Agent 智能分析")

    st.markdown("""
    <div style="background:#F0F9FF; border:1px solid #BAE6FD; border-radius:12px; padding:1rem 1.25rem; margin-bottom:1rem;">
        <strong>🧠 多步推理</strong> &nbsp; Agent 可自主调用搜索、摘要、对比、引用分析等工具，处理复杂研究问题。
    </div>
    """, unsafe_allow_html=True)

    col_q2, col_s2 = st.columns([4, 1])
    with col_q2:
        agent_query = st.text_area(
            "描述你的研究问题…",
            placeholder="例如：找出关于 VLM 在机器人操作中的最新论文，总结它们的技术路线并推荐最相关的研究",
            label_visibility="collapsed",
            height=80,
            key="agent_query",
        )
    with col_s2:
        agent_lang = st.selectbox("语言", ["zh", "en"], format_func=lambda x: "中文" if x == "zh" else "English",
                                  key="agent_lang")
        agent_iter = st.slider("最多步数", 1, 20, 10, key="agent_iter")

    if st.button("🤖 开始推理", type="primary", disabled=not agent_query.strip()):
        from src.agent.openai_agent import run_agent_stream

        steps_container = st.container()
        answer_container = st.empty()
        step_count = 0
        final_answer = ""

        with steps_container:
            st.markdown('<div class="thinking-indicator">'
                        '<div class="dot"></div><div class="dot"></div><div class="dot"></div>'
                        '分析中…</div>', unsafe_allow_html=True)

        try:
            for event in run_agent_stream(query=agent_query, lang=agent_lang, max_iterations=agent_iter):
                e = event

                if e.type == "thinking":
                    with steps_container:
                        st.caption(f"💭 {e.content}")

                elif e.type == "tool_call":
                    step_count += 1
                    with steps_container:
                        st.markdown(f"""
                        <div class="step-card">
                            <div class="step-header">🔧 Step {step_count}: {e.tool}</div>
                        </div>
                        """, unsafe_allow_html=True)

                elif e.type == "tool_result":
                    with steps_container:
                        txt = (e.result or "")[:600]
                        st.caption(f"✅ {e.tool}: {txt}{'…' if len(e.result or '') > 600 else ''}")

                elif e.type == "error":
                    with steps_container:
                        st.warning(f"⚠️ {e.tool}: {e.message}")

                elif e.type == "answer_chunk":
                    final_answer += e.content
                    answer_container.markdown(f"""
                    <div class="chat-container">
                        <div class="chat-bubble assistant">{final_answer}</div>
                    </div>
                    """, unsafe_allow_html=True)

                elif e.type == "usage":
                    st.caption(f"📊 Token: {e.total_tokens} | 工具调用: {e.steps} | 耗时: {e.duration_ms}ms")

        except Exception as ex:
            st.error(f"Agent 执行失败: {ex}")

        if not final_answer.strip():
            answer_container.warning("Agent 未能生成有效答案。")


# ══════════════════════════════════════════════════════════════
#  页面 2: 论文库 — Semantic Scholar 风格
# ══════════════════════════════════════════════════════════════

elif page == "📚 论文库":
    st.title("📚 论文库")

    dao = get_dao("paper")
    total = dao.count()

    # ── 搜索栏 ──
    col1, col2, col3 = st.columns([3, 2, 1])
    with col1:
        keyword = st.text_input("🔍 搜索论文", placeholder="标题 / 摘要 / 作者…", label_visibility="collapsed")
    with col2:
        col_a, col_b = st.columns(2)
        with col_a:
            year_from = st.text_input("年份从", placeholder="2020", label_visibility="collapsed")
        with col_b:
            year_to = st.text_input("年至", placeholder="2025", label_visibility="collapsed")
    with col3:
        sort_by = st.selectbox("排序", ["created_at", "title", "published"],
                               format_func=lambda x: {"created_at": "📥 入库", "title": "🔤 标题", "published": "📅 日期"}[x],
                               label_visibility="collapsed")

    # ── 过滤器行 ──
    col_a2, col_b2, col_c2, col_d2 = st.columns([2, 2, 1, 1])
    with col_a2:
        author = st.text_input("作者", placeholder="模糊匹配", label_visibility="collapsed")
    with col_b2:
        source = st.selectbox("来源", ["", "arxiv", "grobid", "pymupdf", "manual"],
                              format_func=lambda x: x or "全部来源", label_visibility="collapsed")
    with col_c2:
        status_filter = st.selectbox("状态", ["", "ingested", "pending", "failed"],
                                     format_func=lambda x: {"": "全部", "ingested": "✅ 入库", "pending": "⏳ 待处理", "failed": "❌ 失败"}[x],
                                     label_visibility="collapsed")
    with col_d2:
        limit = st.selectbox("条数", [20, 50, 100, 200], index=1, label_visibility="collapsed")

    # ── 结果 ──
    if keyword or author or year_from or year_to or source or status_filter:
        papers = dao.search(
            keyword=keyword, limit=limit, author=author,
            year_from=year_from, year_to=year_to,
            source=source, status=status_filter, sort_by=sort_by,
        )
    else:
        papers = dao.find_all(limit=limit)

    st.caption(f"共 {len(papers)} 条结果 （全库 {total} 篇）")

    if not papers:
        st.info("📭 未找到匹配的论文，试试不同的搜索词或先导入数据。")
    else:
        for p in papers:
            with st.container():
                render_paper_card(p)

    # ── PDF 预览（侧边） ──
    st.divider()
    st.subheader("📄 快速预览")
    arxiv_lookup = st.text_input("输入 arXiv ID 预览 PDF", placeholder="例如 2606.13673v1", label_visibility="collapsed")
    if arxiv_lookup.strip():
        pdf_path = config.RAW_PDF_DIR / f"{arxiv_lookup.strip()}.pdf"
        if pdf_path.exists():
            with open(pdf_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            st.markdown(f"""
            <iframe src="data:application/pdf;base64,{b64}"
                    width="100%" height="700px" style="border:1px solid #E5E7EB; border-radius:12px;">
            </iframe>
            """, unsafe_allow_html=True)
        else:
            st.warning(f"PDF 不存在: {pdf_path}")


# ══════════════════════════════════════════════════════════════
#  页面 3: 摘要 & 综述
# ══════════════════════════════════════════════════════════════

elif page == "📝 摘要 & 综述":
    tab_sum, tab_sur, tab_rec = st.tabs(["📝 论文摘要", "📊 综述生成", "🔗 相似推荐"])

    # ── 摘要 ──
    with tab_sum:
        st.subheader("生成单篇论文的结构化摘要")

        papers = list_papers()
        if not papers:
            st.info("📭 暂无论文，请先导入数据。")
        else:
            paper_opts = {f"{p['arxiv_id']} — {p['title'][:60]}": p["arxiv_id"] for p in papers}
            sel = st.selectbox("选择论文", list(paper_opts.keys()), key="sum_sel", label_visibility="collapsed")
            lang_s = st.selectbox("语言", ["zh", "en"], format_func=lambda x: "中文" if x == "zh" else "English", key="sum_lang")

            if st.button("📝 生成摘要", type="primary", key="sum_btn"):
                with st.spinner("分析中…"):
                    result = summarize_paper(paper_opts[sel], lang=lang_s)
                st.markdown(f"""
                <div class="chat-container">
                    <div class="chat-bubble assistant">{result}</div>
                </div>
                """, unsafe_allow_html=True)

    # ── 综述 ──
    with tab_sur:
        st.subheader("多论文主题综述")

        col_sq, col_sk = st.columns([3, 1])
        with col_sq:
            topic = st.text_input("搜索主题", placeholder="例如：spatial reasoning, VLM, robotic manipulation",
                                  key="sur_topic", label_visibility="collapsed")
        with col_sk:
            top_k_s = st.selectbox("检索数", [10, 15, 20, 30, 50], index=1, key="sur_topk")
        lang_sv = st.selectbox("语言", ["zh", "en"], format_func=lambda x: "中文" if x == "zh" else "English", key="sur_lang")

        if st.button("📊 生成综述", type="primary", disabled=not topic.strip(), key="sur_btn"):
            with st.spinner("检索文献并生成综述…"):
                result = survey(topic, top_k=top_k_s, lang=lang_sv)
            st.markdown(f"""
            <div class="chat-container">
                <div class="chat-bubble assistant">{result}</div>
            </div>
            """, unsafe_allow_html=True)

    # ── 推荐 ──
    with tab_rec:
        st.subheader("基于向量相似度推荐相似论文")

        papers_r = list_papers()
        if not papers_r:
            st.info("📭 暂无论文，无法推荐。")
        else:
            opts_r = {f"{p['arxiv_id']} — {p['title'][:60]}": p["arxiv_id"] for p in papers_r}
            sel_r = st.selectbox("选择论文", list(opts_r.keys()), key="rec_sel", label_visibility="collapsed")
            top_k_r = st.slider("推荐数量", 2, 15, 5, key="rec_topk")

            if st.button("🔍 查找相似论文", type="primary", key="rec_btn"):
                with st.spinner("向量检索中…"):
                    try:
                        results = recommend_similar(opts_r[sel_r], top_k=top_k_r)
                    except Exception as e:
                        st.error(str(e))
                        results = []

                if results:
                    for i, r in enumerate(results, 1):
                        st.markdown(f"""
                        <div class="paper-card">
                            <div class="title">[{i}] {r['title']}</div>
                            <div class="meta">
                                <span>📎 {r['arxiv_id']}</span>
                                <span>🎯 相似度 {r['score']:.4f}</span>
                                <span>🧩 {r['shared_chunks']} 共同片段</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.warning("未找到相似论文。")


# ══════════════════════════════════════════════════════════════
#  页面 4: 引用网络
# ══════════════════════════════════════════════════════════════

elif page == "🔗 引用网络":
    st.title("🔗 引用网络")

    papers = list_papers()
    if not papers:
        st.info("📭 暂无论文。")
    else:
        paper_opts = {f"{p['arxiv_id']} — {p['title'][:60]}": p["arxiv_id"] for p in papers}
        sel = st.selectbox("选择论文", list(paper_opts.keys()), key="cite_sel", label_visibility="collapsed")
        arxiv_id = paper_opts[sel]

        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            view_btn = st.button("🔗 查看引用关系", type="primary", use_container_width=True)
        with col2:
            extract_btn = st.button("🔄 提取全部引用", type="secondary", use_container_width=True)

        if extract_btn:
            from src.parse.citations import batch_extract_citations
            with st.spinner("提取中…"):
                res = batch_extract_citations()
            st.success(f"处理 {res['processed']} 篇, 新增 {res['citations']} 条引用")

        if view_btn or True:  # 默认展示
            dao = get_dao("citation")
            graph = dao.get_graph(arxiv_id)
            total_cit = dao.count()

            col_metrics = st.columns(3)
            col_metrics[0].metric("📤 引用了他文", len(graph['cites']))
            col_metrics[1].metric("📥 被他文引用", len(graph['cited_by']))
            col_metrics[2].metric("🔢 全库引用数", total_cit)

            tab_out, tab_in = st.tabs([f"📤 引用了 ({len(graph['cites'])})",
                                        f"📥 被引用 ({len(graph['cited_by'])})"])

            with tab_out:
                if graph["cites"]:
                    for i, c in enumerate(graph["cites"], 1):
                        badge = "✅" if c["in_db"] else "🌐"
                        st.markdown(f"""
                        <div class="paper-card">
                            <div class="title">{badge} {c.get('cited_title') or c['cited_arxiv_id']}</div>
                            <div class="meta"><span>📎 {c['cited_arxiv_id']}</span></div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info("未找到引用记录。")

            with tab_in:
                if graph["cited_by"]:
                    for i, c in enumerate(graph["cited_by"], 1):
                        badge = "✅" if c["in_db"] else "🌐"
                        st.markdown(f"""
                        <div class="paper-card">
                            <div class="title">{badge} {c.get('citing_title') or c['citing_arxiv_id']}</div>
                            <div class="meta"><span>📎 {c['citing_arxiv_id']}</span></div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info("暂无其他论文引用此篇。")


# ══════════════════════════════════════════════════════════════
#  页面 5: 数据管理（入库 + 导出 + 查询历史）
# ══════════════════════════════════════════════════════════════

elif page == "📤 数据":
    tab_inj, tab_exp, tab_hist = st.tabs(["📥 入库", "📤 导出", "🕐 历史"])

    with tab_inj:
        st.subheader("论文数据入库")
        stats_ing = get_store_stats()
        st.metric("当前向量库 chunks", stats_ing["count"])

        papers_existing = list_papers()
        if papers_existing:
            with st.expander(f"📋 已入库论文（{len(papers_existing)} 篇）", expanded=False):
                for p in papers_existing:
                    st.caption(f"• {p['arxiv_id']}: {p['title'][:80]}")

        col_i1, col_i2 = st.columns(2)
        with col_i1:
            if st.button("🔄 执行入库", type="primary", use_container_width=True):
                pb = st.progress(0, "扫描解析目录…")
                try:
                    result = ingest_parsed_dir()
                    pb.progress(100, "✅ 完成")
                    if "error" in result:
                        st.error(result["error"])
                    else:
                        st.success(f"✅ {result['papers']} 篇论文、{result['chunks']} chunks 已入库！")
                        st.rerun()
                except Exception as e:
                    st.error(str(e))
        with col_i2:
            if st.button("🗑️ 清空并重建", type="secondary", use_container_width=True):
                st.warning("⚠️ 此操作将删除全部向量数据！")
                if st.button("确认清空", type="primary"):
                    reset_store()
                    result = ingest_parsed_dir()
                    if "error" not in result:
                        st.success(f"✅ 重建：{result['papers']} 篇/{result['chunks']} chunks")
                        st.rerun()

    with tab_exp:
        st.subheader("导出数据")

        exp_fmt = st.selectbox("格式", ["json", "csv", "bibtex"], key="exp_fmt")
        exp_limit = st.slider("数量", 10, 500, 100, key="exp_limit")
        exp_type = st.radio("类型", ["论文", "查询历史"], horizontal=True, key="exp_type")

        if st.button("📥 导出", type="primary"):
            if exp_type == "论文":
                dao = get_dao("paper")
                papers = dao.find_all(limit=exp_limit)
                if exp_fmt == "json":
                    data = json.dumps([p.to_dict() for p in papers], ensure_ascii=False, indent=2)
                    st.download_button("⬇ 下载", data, "papers.json", "application/json")
                elif exp_fmt == "csv":
                    buf = io.StringIO()
                    import csv
                    w = csv.writer(buf)
                    w.writerow(["id", "arxiv_id", "title", "authors", "abstract", "published", "source", "status", "chunks"])
                    for p in papers:
                        w.writerow([p.id, p.arxiv_id, p.title, p.authors, p.abstract,
                                    p.published, p.source, p.ingest_status, p.chunk_count])
                    st.download_button("⬇ 下载", buf.getvalue(), "papers.csv", "text/csv")
                else:
                    entries = []
                    for p in papers:
                        a = (p.authors or "Unknown").split(",")[0].strip().split()[-1] if p.authors else "Unknown"
                        entries.append(
                            f"@article{{{a}{p.published[:4] if p.published else ''},\n"
                            f"  title = {{{{{p.title}}}}},\n  author = {{{{{p.authors or 'Unknown'}}}}},\n"
                            f"  year = {{{{{p.published[:4] if p.published else '????'}}}}},\n"
                            f"  eprint = {{{{{p.arxiv_id}}}}},\n}}"
                        )
                    st.download_button("⬇ 下载", "\n\n".join(entries), "papers.bib", "text/plain")
                st.success(f"已导出 {len(papers)} 条记录")
            else:
                dao = get_dao("query")
                recs = dao.find_recent(limit=exp_limit)
                if exp_fmt == "json":
                    data = json.dumps([{"id": r.id, "query": r.query_text, "answer": r.answer_text,
                                        "lang": r.lang, "hits": r.hit_count, "time": r.created_at}
                                       for r in recs], ensure_ascii=False, indent=2)
                    st.download_button("⬇ 下载", data, "queries.json", "application/json")
                else:
                    buf = io.StringIO()
                    import csv
                    w = csv.writer(buf)
                    w.writerow(["id", "query", "answer", "lang", "hits", "created_at"])
                    for r in recs:
                        w.writerow([r.id, r.query_text, r.answer_text, r.lang, r.hit_count, r.created_at])
                    st.download_button("⬇ 下载", buf.getvalue(), "queries.csv", "text/csv")
                st.success(f"已导出 {len(recs)} 条记录")

    with tab_hist:
        st.subheader("查询历史")
        dao_q = get_dao("query")
        records = dao_q.find_recent(limit=30)
        if not records:
            st.info("暂无查询记录。")
        else:
            if st.button("🗑️ 清空历史", type="secondary"):
                dao_q.clear()
                st.rerun()
            for r in records:
                with st.expander(f"🔍 {r.query_text[:60]}… — {r.created_at}"):
                    st.caption(f"语言: {r.lang} | 命中: {r.hit_count}")
                    st.markdown(r.answer_text[:500])


# ══════════════════════════════════════════════════════════════
#  页面 6: 系统管理
# ══════════════════════════════════════════════════════════════

elif page == "⚙️ 系统":
    st.title("⚙️ 系统管理")

    tab_s1, tab_s2, tab_s3 = st.tabs(["📊 状态", "💾 备份", "⚙️ 配置"])

    with tab_s1:
        col_sa, col_sb = st.columns(2)
        with col_sa:
            st.subheader("向量库")
            st.json(get_store_stats())
        with col_sb:
            st.subheader("缓存")
            cs = get_cache_stats()
            st.metric("LLM 命中率", f"{cs['llm']['hit_rate']*100:.1f}%")
            st.caption(f"hits: {cs['llm']['hits']} / misses: {cs['llm']['misses']}")
            st.metric("Embed 命中率", f"{cs['embed']['hit_rate']*100:.1f}%")
            st.caption(f"hits: {cs['embed']['hits']} / misses: {cs['embed']['misses']}")
            if st.button("🗑️ 清空缓存", type="secondary"):
                from src.cache import get_llm_cache, get_embed_cache
                get_llm_cache().clear()
                get_embed_cache().clear()
                st.success("已清空")
                st.rerun()

    with tab_s2:
        st.subheader("向量库备份")
        col_ba, col_bb = st.columns(2)
        with col_ba:
            if st.button("💾 立即备份", type="primary", use_container_width=True):
                import shutil
                from datetime import datetime
                d = config.DATA_DIR / "chroma_backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copytree(str(config.CHROMA_DIR), str(d))
                st.success(f"✅ 已备份到 {d.name}")
                st.rerun()

        backup_root = config.DATA_DIR / "chroma_backup"
        if backup_root.exists():
            backups = sorted(backup_root.iterdir(), key=lambda x: x.name, reverse=True)
            for b in backups:
                if b.is_dir():
                    sz = sum(f.stat().st_size for f in b.rglob("*") if f.is_file())
                    col_n, col_s, col_r = st.columns([3, 1, 1])
                    with col_n:
                        st.text(f"📁 {b.name}")
                    with col_s:
                        st.caption(f"{sz/1024/1024:.1f} MB")
                    with col_r:
                        if st.button("🔄 恢复", key=f"rst_{b.name}"):
                            import shutil
                            if config.CHROMA_DIR.exists():
                                shutil.rmtree(str(config.CHROMA_DIR))
                            shutil.copytree(str(b), str(config.CHROMA_DIR))
                            st.success(f"已从 {b.name} 恢复")
                            st.rerun()

    with tab_s3:
        st.subheader("运行配置")
        st.json(config.summary())
        st.divider()
        if st.button("🗑️ 清空向量库", type="secondary"):
            st.warning("⚠️ 不可逆！")
            if st.button("确认清空", type="primary"):
                result = reset_store()
                if "error" not in result:
                    st.success("已清空")
                    st.rerun()
