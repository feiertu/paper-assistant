"""Paper Assistant Streamlit UI。

启动：
    streamlit run ui/app.py --server.address 0.0.0.0 --server.port 8501
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保项目根在 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

import config
from src.db import get_dao
from src.rag import (
    answer_rag_stream,
    get_store_stats,
    ingest_parsed_dir,
    list_papers,
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
</style>
""", unsafe_allow_html=True)

# ── 侧边栏 ──

st.sidebar.title("📚 Paper Assistant")

page = st.sidebar.radio(
    "导航",
    ["💬 RAG 问答", "📝 论文摘要", "📊 综述生成", "📚 论文列表", "🕐 查询历史", "📥 数据入库", "⚙️ 系统管理"],
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
#  页面 4: 论文列表
# ══════════════════════════════════════════════

elif page == "📚 论文列表":
    st.title("📚 已入库论文")

    dao = get_dao("paper")
    db_papers = dao.find_all(limit=200)
    if not db_papers:
        st.info("暂无论文。请先到「数据入库」页面导入。")
    else:
        st.metric("总计", len(db_papers))
        for p in db_papers:
            with st.container():
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"**{p.title or p.arxiv_id}**")
                    st.caption(f"{p.arxiv_id} | {p.authors[:80] if p.authors else '未知作者'} | {p.published}")
                with col2:
                    st.caption(f"chunks: {p.chunk_count}")
                    st.caption(f"状态: {'✅' if p.ingest_status == 'ingested' else '⏳'}")
                st.divider()

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
            with st.spinner("正在从 data/parsed/ 读取并入库…"):
                result = ingest_parsed_dir()
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

    stats = get_store_stats()
    st.json(stats)

    st.divider()

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
