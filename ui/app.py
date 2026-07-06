"""Paper Assistant — Vercel 风格 SPA UI。

启动：streamlit run ui/app.py --server.address 0.0.0.0 --server.port 8501

设计灵感：Vercel DESIGN.md
- 白色画布
- 固定左侧导航栏 (SPA 风格)
- 右上角登录按钮 → 弹窗登录/注册
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path

import requests

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

# ══════════════════════════════════════════════════════════════
#  页面配置
# ══════════════════════════════════════════════════════════════

st.set_page_config(page_title="Paper Assistant", page_icon="👑", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
#  Session State 初始化
# ══════════════════════════════════════════════════════════════

DEFAULTS = {
    "user": None,              # 当前登录用户
    "show_auth": False,        # 是否显示登录弹窗
    "auth_mode": "login",      # "login" | "register"
    "auth_error": "",          # 认证错误消息
    "auth_success_msg": "",    # 认证成功提示（绿色）
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════
#  用户持久化存储 — JSON 文件 + SHA-256 哈希
# ══════════════════════════════════════════════════════════════

_USERS_FILE = config.DATA_DIR / "users.json"
_RATE_FILE = config.DATA_DIR / "reg_rate_limit.json"

# ── 密码哈希 ──

def _hash_pw(password: str, salt: str | None = None) -> tuple[str, str]:
    """SHA-256(password + salt)，返回 (hash_hex, salt)。"""
    if salt is None:
        salt = hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:16]
    h = hashlib.sha256((password + salt).encode()).hexdigest()
    return h, salt

# ── 用户加载 / 保存 ──

def _load_users() -> dict[str, dict]:
    if _USERS_FILE.exists():
        try:
            return json.loads(_USERS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    # 首次启动：创建 demo 账号
    h, s = _hash_pw("demo123")
    users = {"demo": {"hash": h, "salt": s, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}}
    _USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
    return users

def _save_users(users: dict) -> None:
    _USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")

if "users_db" not in st.session_state:
    st.session_state.users_db = _load_users()

# ── 验证规则 ──

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")
_CJK_RE = re.compile(r"[一-鿿㐀-䶿぀-ゟ゠-ヿ가-힯]")

def validate_username(u: str) -> str | None:
    """校验用户名：3-20 位，仅英文/数字/下划线。返回 None 表示通过。"""
    if not u or not u.strip():
        return "用户名不能为空"
    if not _USERNAME_RE.match(u):
        return "用户名需 3-20 位，只能包含英文字母、数字和下划线"
    return None

def validate_password(pw: str) -> str | None:
    """校验密码强度。返回 None 表示通过。"""
    if not pw:
        return "密码不能为空"
    if len(pw) < 8:
        return "密码至少需要 8 个字符"
    if not re.search(r"[a-zA-Z]", pw):
        return "密码必须包含至少一个英文字母"
    if not re.search(r"\d", pw):
        return "密码必须包含至少一个数字"
    if _CJK_RE.search(pw):
        return "密码不能包含中文/日文/韩文字符"
    if not all(32 <= ord(c) <= 126 for c in pw):
        return "密码只能使用 ASCII 可打印字符（英文、数字、常见符号）"
    return None

# ── 注册限流（文件持久化，跨 session 生效）──

_REG_MINUTE_MAX = 3    # 每分钟最多 3 次
_REG_HOUR_MAX = 10     # 每小时最多 10 次
_REG_COOLDOWN = 10     # 两次注册最少间隔 10 秒

def _check_rate_limit() -> str | None:
    now = time.time()
    timestamps: list[float] = []
    if _RATE_FILE.exists():
        try:
            timestamps = json.loads(_RATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    recent_min = [t for t in timestamps if now - t < 60]
    recent_hr  = [t for t in timestamps if now - t < 3600]
    if len(recent_min) >= _REG_MINUTE_MAX:
        return f"注册过于频繁，每分钟最多 {_REG_MINUTE_MAX} 次，请稍后再试"
    if len(recent_hr) >= _REG_HOUR_MAX:
        return f"注册过于频繁，每小时最多 {_REG_HOUR_MAX} 次，请稍后再试"
    if timestamps and now - timestamps[-1] < _REG_COOLDOWN:
        return f"请等待 {int(_REG_COOLDOWN - (now - timestamps[-1]))} 秒后再注册"
    return None

def _record_registration() -> None:
    now = time.time()
    timestamps: list[float] = []
    if _RATE_FILE.exists():
        try:
            timestamps = json.loads(_RATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    timestamps.append(now)
    timestamps = [t for t in timestamps if now - t < 7200]
    _RATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RATE_FILE.write_text(json.dumps(timestamps))

# ── 认证函数 ──

def do_login(username: str, password: str) -> bool:
    username = username.strip()
    users: dict = st.session_state.users_db
    entry = users.get(username)
    if entry and isinstance(entry, dict):
        h, _ = _hash_pw(password, entry.get("salt", ""))
        if h == entry.get("hash", ""):
            st.session_state.user = username
            st.session_state.auth_error = ""
            st.session_state.auth_success_msg = ""
            st.session_state.show_auth = False
            return True
    st.session_state.auth_error = "用户名或密码错误"
    return False

def do_register(username: str, password: str, confirm: str) -> bool:
    username = username.strip()

    # 1. 限流
    err = _check_rate_limit()
    if err:
        st.session_state.auth_error = err
        return False

    # 2. 用户名
    err = validate_username(username)
    if err:
        st.session_state.auth_error = err
        return False

    # 3. 密码一致性
    if password != confirm:
        st.session_state.auth_error = "两次密码不一致"
        return False

    # 4. 密码强度
    err = validate_password(password)
    if err:
        st.session_state.auth_error = err
        return False

    # 5. 是否已存在
    if username in st.session_state.users_db:
        st.session_state.auth_error = "用户名已存在"
        return False

    # 6. 注册 — 哈希存储，不自动登录
    h, s = _hash_pw(password)
    st.session_state.users_db[username] = {
        "hash": h,
        "salt": s,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_users(st.session_state.users_db)
    _record_registration()

    # 切换到登录页，提示注册成功
    st.session_state.auth_mode = "login"
    st.session_state.auth_error = ""
    st.session_state.auth_success_msg = "✅ 注册成功！请使用新账号登录"
    return True

def do_logout():
    st.session_state.user = None
    st.session_state.show_auth = False


def on_login_submit():
    do_login(
        st.session_state.get("auth_username", ""),
        st.session_state.get("auth_password", ""),
    )


def on_register_submit():
    do_register(
        st.session_state.get("auth_username", ""),
        st.session_state.get("auth_password", ""),
        st.session_state.get("auth_confirm", ""),
    )


# ══════════════════════════════════════════════════════════════
#  Header Bar
# ══════════════════════════════════════════════════════════════

def render_header():
    with st.container(key="header"):
        st.markdown(
            '<span class="header-title">Paper Assistant</span>'
            '<span class="header-subtitle">RAG 学术论文智能助手</span>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════
#  Auth Dialog — 使用 Streamlit 原生 st.dialog（渲染在页面 DOM 之外）
#  自带 backdrop 遮罩 + 毛玻璃效果，不会被页面 CSS 层叠上下文影响
# ══════════════════════════════════════════════════════════════

@st.dialog("Paper Assistant", width="small")
def render_auth_dialog():
    """原生弹窗 — Streamlit 将其渲染在主内容容器外部，自带正确的遮罩层。"""
    # 注入样式移除 dialog 自带的右上角 X 按钮（dialog DOM 动态创建，在这里注入确保时序）
    st.markdown(
        "<style>button[aria-label='Close']{display:none!important;visibility:hidden!important;"
        "width:0!important;height:0!important;padding:0!important;margin:0!important;"
        "opacity:0!important;pointer-events:none!important}</style>",
        unsafe_allow_html=True,
    )

    is_login = st.session_state.auth_mode == "login"

    st.markdown(f"### {'登录' if is_login else '注册账号'}")
    st.caption("欢迎使用 Paper Assistant — RAG 学术论文智能助手")

    st.text_input(
        "用户名", placeholder="输入用户名（3-20位英文/数字/下划线）",
        key="auth_username", label_visibility="collapsed",
    )
    if not is_login:
        st.caption("⚠️ 用户名注册后无法修改，请谨慎选择")

    st.text_input(
        "密码", placeholder="输入密码（至少8位，需包含英文字母和数字）",
        type="password", key="auth_password", label_visibility="collapsed",
    )
    if not is_login:
        st.caption("密码要求：≥8 位，必须含英文字母 + 数字，不含中文")

    if not is_login:
        st.text_input(
            "确认密码", placeholder="再次输入密码", type="password",
            key="auth_confirm", label_visibility="collapsed",
        )

    if st.session_state.auth_error:
        st.error(st.session_state.auth_error)
    if st.session_state.get("auth_success_msg"):
        st.success(st.session_state.auth_success_msg)
        st.session_state.auth_success_msg = ""  # 只显示一次

    col_btn1, col_btn2 = st.columns([1, 1])
    with col_btn1:
        if is_login:
            if st.button("登录", type="primary", key="auth_submit",
                         use_container_width=True):
                on_login_submit()
                st.rerun()
        else:
            if st.button("注册", type="primary", key="auth_submit",
                         use_container_width=True):
                on_register_submit()
                st.rerun()
    with col_btn2:
        if st.button("✕ 关闭", key="modal_close", use_container_width=True):
            st.session_state.show_auth = False
            st.session_state.auth_error = ""
            st.rerun()

    if is_login:
        if st.button("还没有账号？注册账号", key="switch_to_register",
                     use_container_width=True):
            st.session_state.auth_mode = "register"
            st.session_state.auth_error = ""
            st.rerun()
    else:
        if st.button("已有账号？返回登录", key="switch_to_login",
                     use_container_width=True):
            st.session_state.auth_mode = "login"
            st.session_state.auth_error = ""
            st.rerun()


# ══════════════════════════════════════════════════════════════
#  导航 Sidebar — SPA 风格
# ══════════════════════════════════════════════════════════════

NAV_ITEMS = [
    ("qa",        "智能问答"),
    ("agent",     "Agent 分析"),
    ("library",   "论文库"),
    ("summary",   "摘要 & 综述"),
    ("citations", "引用关系"),
    ("data",      "数据管理"),
    ("system",    "系统设置"),
]

NAV_KEY_TO_LABEL = {k: v for k, v in NAV_ITEMS}
NAV_LABEL_TO_KEY = {v: k for k, v in NAV_ITEMS}

if "nav_page" not in st.session_state:
    st.session_state.nav_page = "qa"


def render_sidebar():
    with st.sidebar:
        st.markdown("## Paper Assistant")
        st.caption("RAG 学术论文智能助手")

        st.divider()

        labels = [label for _, label in NAV_ITEMS]
        current_label = NAV_KEY_TO_LABEL.get(st.session_state.nav_page, "智能问答")
        try:
            default_idx = labels.index(current_label)
        except ValueError:
            default_idx = 0

        selected_label = st.radio(
            "导航", labels, index=default_idx,
            label_visibility="collapsed", key="sidebar_nav",
        )

        new_key = NAV_LABEL_TO_KEY.get(selected_label, "qa")
        if new_key != st.session_state.nav_page:
            st.session_state.nav_page = new_key
            st.rerun()

        st.divider()

        try:
            s = get_store_stats()
        except Exception:
            s = {"count": 0}
        col_a, col_b = st.columns(2)
        col_a.metric("Chunks", s["count"])
        model_short = config.LLM_MODEL[:12] + "…" if len(config.LLM_MODEL) > 12 else config.LLM_MODEL
        col_b.metric("Model", model_short)

        # ── 用户区域（sidebar 底部）──
        st.divider()
        user = st.session_state.user
        if user:
            st.markdown(
                f'<div class="sidebar-user">'
                f'<span class="sidebar-avatar">{user[0].upper()}</span>'
                f'<span class="sidebar-username">{user}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button("退出登录", key="sidebar_logout", use_container_width=True):
                do_logout()
                st.rerun()
        else:
            if st.button("登录", key="sidebar_login", use_container_width=True):
                st.session_state.show_auth = True
                st.session_state.auth_mode = "login"
                st.session_state.auth_error = ""
                st.session_state.auth_success_msg = ""
                st.rerun()

        if not config.API_AUTH_ENABLED:
            st.divider()
            st.warning("API 鉴权未启用，公网部署存在风险", icon="🔓")


# ══════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════

def render_paper_card(p, show_abstract=True):
    status_badge = {
        "ingested": ('badge badge-success', '已入库'),
        "pending":  ('badge badge-warning', '待处理'),
        "failed":   ('badge badge-muted', '失败'),
    }.get(p.ingest_status, ('badge badge-muted', p.ingest_status))

    html = f"""
    <div class="paper-card">
        <div class="title">{p.title or p.arxiv_id}</div>
        <div class="authors">{p.authors or '未知作者'}</div>
        <div class="meta">
            <span>{p.published or '未知'}</span>
            <span>{p.arxiv_id}</span>
            <span>{p.chunk_count} chunks</span>
            <span class="{status_badge[0]}">{status_badge[1]}</span>
        </div>
    """
    if show_abstract and p.abstract:
        html += f'<div class="abstract">{p.abstract[:400]}{"…" if len(p.abstract) > 400 else ""}</div>'
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_source_card(hit, idx):
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
#  页面渲染
# ══════════════════════════════════════════════════════════════

render_header()
render_sidebar()

page_key = st.session_state.nav_page


# ══════════════════════════════════════════════════════════════
#  页面 0: 智能问答
# ══════════════════════════════════════════════════════════════

if page_key == "qa":
    def render_qa():
        st.markdown("""
        <div class="hero-search">
            <h1>用 AI 读懂每一篇论文</h1>
            <p>基于 RAG 的学术论文智能问答 — 搜索、理解、对比，像和专家对话一样</p>
        </div>
        """, unsafe_allow_html=True)

        col_q, col_s = st.columns([5, 1])
        with col_q:
            query = st.text_area(
                "提问", placeholder="试试问：SpatialClaw 的核心创新是什么？",
                label_visibility="collapsed", height=68, key="qa_query",
            )
        with col_s:
            top_k = st.selectbox("精度", [3, 5, 10, 20], index=1,
                                 label_visibility="collapsed", key="qa_topk")

        col_btn, col_lang = st.columns([1, 4])
        with col_btn:
            ask = st.button("搜索回答", type="primary", use_container_width=True,
                           disabled=not query.strip())
        with col_lang:
            lang_qa = st.selectbox("语言", ["zh", "en"],
                                   format_func=lambda x: "中文" if x == "zh" else "English",
                                   label_visibility="collapsed")

        if ask:
            with st.status("检索相关知识…", expanded=False) as status:
                result = retrieve(query, top_k=top_k)
                hits = result.get("hits", [])
                status.update(label=f"找到 {len(hits)} 个相关片段", state="complete")

            if hits:
                with st.expander(f"引用论文片段（{len(hits)} 条）", expanded=False):
                    for i, hit in enumerate(hits, 1):
                        render_source_card(hit, i)

            st.markdown("### 回答")
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
                st.warning("未找到相关信息。")

        if not ask:
            st.divider()
            st.caption("试试这些问题")
            examples = [
                "总结 RLBench 相关论文的核心方法",
                "对比 SpatialClaw 和传统 VLM 方法",
                "哪些论文引用了 2606.13673v1？",
                "推荐与这篇论文相似的研究",
            ]
            cols = st.columns(4)
            for i, ex in enumerate(examples):
                with cols[i]:
                    st.button(ex, key=f"ex_{i}", use_container_width=True,
                              on_click=lambda e=ex: st.session_state.update({"qa_query": e}))

    render_qa()


# ══════════════════════════════════════════════════════════════
#  页面 1: Agent 分析
# ══════════════════════════════════════════════════════════════

elif page_key == "agent":
    def render_agent():
        st.markdown('<div class="page-title">Agent 智能分析</div>', unsafe_allow_html=True)
        st.markdown('<p class="page-description">Agent 可自主调用搜索、摘要、对比、引用分析等工具，处理复杂研究问题。</p>',
                    unsafe_allow_html=True)

        col_q2, col_s2 = st.columns([4, 1])
        with col_q2:
            agent_query = st.text_area(
                "描述你的研究问题…",
                placeholder="例如：找出 VLM 在机器人操作中的最新论文，总结技术路线并推荐研究",
                label_visibility="collapsed", height=80, key="agent_query",
            )
        with col_s2:
            agent_lang = st.selectbox("语言", ["zh", "en"],
                                      format_func=lambda x: "中文" if x == "zh" else "English",
                                      key="agent_lang")
            agent_iter = st.slider("步数", 1, 20, 10, key="agent_iter")

        if st.button("开始推理", type="primary", disabled=not agent_query.strip()):
            from src.agent.openai_agent import run_agent_stream

            steps_container = st.container()
            answer_container = st.empty()
            final_answer = ""

            with steps_container:
                st.markdown('<div class="thinking-indicator">'
                            '<div class="dot"></div><div class="dot"></div><div class="dot"></div>'
                            '分析中…</div>', unsafe_allow_html=True)

            try:
                for event in run_agent_stream(query=agent_query, lang=agent_lang, max_iterations=agent_iter):
                    if event.type == "thinking":
                        with steps_container:
                            st.caption(f"{event.content}")
                    elif event.type == "tool_call":
                        with steps_container:
                            st.markdown(f"""
                            <div class="step-card">
                                <div class="step-header">Step: {event.tool}</div>
                            </div>
                            """, unsafe_allow_html=True)
                    elif event.type == "tool_result":
                        with steps_container:
                            txt = (event.result or "")[:600]
                            st.caption(f"{event.tool}: {txt}{'…' if len(event.result or '') > 600 else ''}")
                    elif event.type == "error":
                        with steps_container:
                            st.warning(f"{event.tool}: {event.message}")
                    elif event.type == "answer_chunk":
                        final_answer += event.content
                        answer_container.markdown(f"""
                        <div class="chat-container">
                            <div class="chat-bubble assistant">{final_answer}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    elif event.type == "usage":
                        st.caption(f"Token: {event.total_tokens} | 工具调用: {event.steps} | 耗时: {event.duration_ms}ms")
            except Exception as ex:
                st.error(f"Agent 执行失败: {ex}")

            if not final_answer.strip():
                answer_container.warning("Agent 未能生成有效答案。")

    render_agent()


# ══════════════════════════════════════════════════════════════
#  页面 2: 论文库
# ══════════════════════════════════════════════════════════════

elif page_key == "library":
    def render_library():
        st.markdown('<div class="page-title">论文库</div>', unsafe_allow_html=True)
        st.markdown('<p class="page-description">浏览、搜索和管理已入库的学术论文。</p>',
                    unsafe_allow_html=True)

        # ── arXiv 抓取 ──
        with st.expander("📥 从 arXiv 抓取论文", expanded=False):
            # 内部 API 鉴权
            _api_headers = {}
            if config.API_AUTH_ENABLED and config.API_AUTH_KEY:
                _api_headers["X-API-Key"] = config.API_AUTH_KEY

            col_q1, col_q2, col_q3 = st.columns([3, 1, 1])
            with col_q1:
                fetch_query = st.text_input(
                    "arXiv 查询", value=config.ARXIV_QUERY,
                    placeholder="例如: cat:cs.AI AND ti:learning",
                    help="arXiv API 搜索语法：cat:cs.CL (分类), ti:transformer (标题), au:bengio (作者)",
                    key="arxiv_query",
                )
            with col_q2:
                fetch_n = st.number_input("篇数", min_value=1, max_value=50, value=5, key="arxiv_n")
            with col_q3:
                fetch_auto = st.checkbox("自动入库", value=True, key="arxiv_auto",
                                         help="下载+解析后自动向量化入库")

            col_b1, col_b2, col_b3 = st.columns([2, 2, 2])
            with col_b1:
                if st.button("🔍 搜索元数据", use_container_width=True, key="arxiv_search_btn",
                             help="仅从 arXiv 搜索论文信息，不下载 PDF"):
                    with st.spinner("搜索 arXiv…"):
                        try:
                            resp = requests.post(
                                f"http://127.0.0.1:{config.API_PORT}/arxiv/fetch",
                                json={"query": fetch_query, "max_results": fetch_n},
                                headers=_api_headers, timeout=120,
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                st.success(f"找到 {data['count']} 篇论文")
                                for p in data.get("papers", []):
                                    st.caption(f"📄 {p['arxiv_id']}: {p['title']}")
                                st.info("点击「一键抓取」下载 PDF 并入库")
                            else:
                                st.error(resp.json().get("detail", str(resp.status_code)))
                        except Exception as e:
                            st.error(str(e))

            with col_b2:
                if st.button("📄 下载 PDF", use_container_width=True, key="arxiv_dl_btn",
                             help="下载已搜索到的论文 PDF（需先搜索）"):
                    with st.spinner("下载中…"):
                        try:
                            resp = requests.post(
                                f"http://127.0.0.1:{config.API_PORT}/arxiv/download",
                                json={"query": fetch_query, "max_results": fetch_n},
                                headers=_api_headers, timeout=300,
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                st.success(f"下载 {data['downloaded']} 篇, 失败 {data.get('failed', 0)} 篇")
                            else:
                                st.error(resp.json().get("detail", str(resp.status_code)))
                        except Exception as e:
                            st.error(str(e))

            with col_b3:
                if st.button("⚡ 一键抓取", use_container_width=True, type="primary", key="arxiv_pipeline_btn",
                             help="搜索 → 下载 → 解析 → 入库 全自动"):
                    with st.spinner("全自动管道运行中…"):
                        try:
                            resp = requests.post(
                                f"http://127.0.0.1:{config.API_PORT}/arxiv/pipeline",
                                json={"query": fetch_query, "max_results": fetch_n,
                                      "auto_ingest": fetch_auto},
                                headers=_api_headers, timeout=600,
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                for s in data.get("steps", []):
                                    step_name = {"fetch": "搜索", "download": "下载",
                                                 "parse": "解析", "ingest": "入库"}.get(s["step"], s["step"])
                                    if s["step"] == "fetch":
                                        st.write(f"🔍 {step_name}: 找到 {s['count']} 篇")
                                    elif s["step"] == "download":
                                        st.write(f"📄 {step_name}: 成功 {s['success']} 篇" +
                                                 (f", 失败 {s['failed']} 篇" if s.get("failed") else ""))
                                    elif s["step"] == "parse":
                                        st.write(f"📝 {step_name}: {s['count']} 篇")
                                    elif s["step"] == "ingest":
                                        st.write(f"📦 {step_name}: {s['papers']} 篇/{s['chunks']} chunks")
                                st.success("管道完成！刷新页面查看新论文。")
                                st.rerun()
                            else:
                                st.error(resp.json().get("detail", str(resp.status_code)))
                        except Exception as e:
                            st.error(str(e))

        dao = get_dao("paper")
        total = dao.count()

        col1, col2, col3 = st.columns([3, 2, 1])
        with col1:
            keyword = st.text_input("搜索论文", placeholder="标题 / 摘要 / 作者…", label_visibility="collapsed")
        with col2:
            col_a, col_b = st.columns(2)
            with col_a:
                year_from = st.text_input("年份从", placeholder="2020", label_visibility="collapsed")
            with col_b:
                year_to = st.text_input("年至", placeholder="2025", label_visibility="collapsed")
        with col3:
            sort_by = st.selectbox("排序", ["created_at", "title", "published"],
                                   format_func=lambda x: {"created_at": "入库", "title": "标题", "published": "日期"}[x],
                                   label_visibility="collapsed")

        col_a2, col_b2, col_c2, col_d2 = st.columns([2, 2, 1, 1])
        with col_a2:
            author = st.text_input("作者", placeholder="模糊匹配", label_visibility="collapsed")
        with col_b2:
            source = st.selectbox("来源", ["", "arxiv", "grobid", "pymupdf", "manual"],
                                  format_func=lambda x: x or "全部来源", label_visibility="collapsed")
        with col_c2:
            status_filter = st.selectbox("状态", ["", "ingested", "pending", "failed"],
                                         format_func=lambda x: {"": "全部", "ingested": "入库", "pending": "待处理", "failed": "失败"}[x],
                                         label_visibility="collapsed")
        with col_d2:
            limit = st.selectbox("条数", [20, 50, 100, 200], index=1, label_visibility="collapsed")

        if keyword or author or year_from or year_to or source or status_filter:
            papers = dao.search(
                keyword=keyword, limit=limit, author=author,
                year_from=year_from, year_to=year_to,
                source=source, status=status_filter, sort_by=sort_by,
            )
        else:
            papers = dao.find_all(limit=limit)

        st.caption(f"共 {len(papers)} 条结果（全库 {total} 篇）")

        if not papers:
            st.info("未找到匹配的论文。")
        else:
            for p in papers:
                with st.container():
                    render_paper_card(p)

        st.divider()
        st.subheader("快速预览")
        arxiv_lookup = st.text_input("输入 arXiv ID 预览 PDF", placeholder="例如 2606.13673v1",
                                     label_visibility="collapsed")
        if arxiv_lookup.strip():
            pdf_path = config.RAW_PDF_DIR / f"{arxiv_lookup.strip()}.pdf"
            if pdf_path.exists():
                with open(pdf_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                st.markdown(f"""
                <iframe src="data:application/pdf;base64,{b64}"
                        width="100%" height="700px"
                        style="border:1px solid var(--hairline); border-radius:12px;">
                </iframe>
                """, unsafe_allow_html=True)
            else:
                st.warning(f"PDF 不存在: {pdf_path}")

    render_library()


# ══════════════════════════════════════════════════════════════
#  页面 3: 摘要 & 综述
# ══════════════════════════════════════════════════════════════

elif page_key == "summary":
    def render_summary():
        st.markdown('<div class="page-title">摘要 & 综述</div>', unsafe_allow_html=True)
        st.markdown('<p class="page-description">生成论文摘要、多论文综述，或基于向量相似度推荐相关研究。</p>',
                    unsafe_allow_html=True)

        tab_sum, tab_sur, tab_rec = st.tabs(["论文摘要", "综述生成", "相似推荐"])

        with tab_sum:
            st.subheader("生成单篇论文的结构化摘要")
            papers = list_papers()
            if not papers:
                st.info("暂无论文，请先导入数据。")
            else:
                paper_opts = {f"{p['arxiv_id']} — {p['title'][:60]}": p["arxiv_id"] for p in papers}
                sel = st.selectbox("选择论文", list(paper_opts.keys()), key="sum_sel", label_visibility="collapsed")
                lang_s = st.selectbox("语言", ["zh", "en"],
                                      format_func=lambda x: "中文" if x == "zh" else "English", key="sum_lang")
                if st.button("生成摘要", type="primary", key="sum_btn"):
                    with st.spinner("分析中…"):
                        result = summarize_paper(paper_opts[sel], lang=lang_s)
                    st.markdown(f"""
                    <div class="chat-container">
                        <div class="chat-bubble assistant">{result}</div>
                    </div>
                    """, unsafe_allow_html=True)

        with tab_sur:
            st.subheader("多论文主题综述")
            col_sq, col_sk = st.columns([3, 1])
            with col_sq:
                topic = st.text_input("搜索主题", placeholder="例如：spatial reasoning, VLM, robotic manipulation",
                                      key="sur_topic", label_visibility="collapsed")
            with col_sk:
                top_k_s = st.selectbox("检索数", [10, 15, 20, 30, 50], index=1, key="sur_topk")
            lang_sv = st.selectbox("语言", ["zh", "en"],
                                   format_func=lambda x: "中文" if x == "zh" else "English", key="sur_lang")
            if st.button("生成综述", type="primary", disabled=not topic.strip(), key="sur_btn"):
                with st.spinner("检索文献并生成综述…"):
                    result = survey(topic, top_k=top_k_s, lang=lang_sv)
                st.markdown(f"""
                <div class="chat-container">
                    <div class="chat-bubble assistant">{result}</div>
                </div>
                """, unsafe_allow_html=True)

        with tab_rec:
            st.subheader("基于向量相似度推荐相似论文")
            papers_r = list_papers()
            if not papers_r:
                st.info("暂无论文，无法推荐。")
            else:
                opts_r = {f"{p['arxiv_id']} — {p['title'][:60]}": p["arxiv_id"] for p in papers_r}
                sel_r = st.selectbox("选择论文", list(opts_r.keys()), key="rec_sel", label_visibility="collapsed")
                top_k_r = st.slider("推荐数量", 2, 15, 5, key="rec_topk")
                if st.button("查找相似论文", type="primary", key="rec_btn"):
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
                                    <span>{r['arxiv_id']}</span>
                                    <span>相似度 {r['score']:.4f}</span>
                                    <span>{r['shared_chunks']} 共同片段</span>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.warning("未找到相似论文。")

    render_summary()


# ══════════════════════════════════════════════════════════════
#  页面 4: 引用关系
# ══════════════════════════════════════════════════════════════

elif page_key == "citations":
    def render_citations():
        st.markdown('<div class="page-title">引用关系</div>', unsafe_allow_html=True)
        st.markdown('<p class="page-description">查看论文之间的引用关系，提取和分析引用图谱。</p>',
                    unsafe_allow_html=True)

        papers = list_papers()
        if not papers:
            st.info("暂无论文。")
        else:
            paper_opts = {f"{p['arxiv_id']} — {p['title'][:60]}": p["arxiv_id"] for p in papers}
            sel = st.selectbox("选择论文", list(paper_opts.keys()), key="cite_sel", label_visibility="collapsed")
            arxiv_id = paper_opts[sel]

            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                view_btn = st.button("查看引用关系", type="primary", use_container_width=True)
            with col2:
                extract_btn = st.button("提取全部引用", type="secondary", use_container_width=True)

            if extract_btn:
                from src.parse.citations import batch_extract_citations
                with st.spinner("提取中…"):
                    res = batch_extract_citations()
                st.success(f"处理 {res['processed']} 篇, 新增 {res['citations']} 条引用")

            # 始终显示引用关系图谱
            dao = get_dao("citation")
            graph = dao.get_graph(arxiv_id)
            total_cit = dao.count()

            col_metrics = st.columns(3)
            col_metrics[0].metric("引用了他文", len(graph['cites']))
            col_metrics[1].metric("被他文引用", len(graph['cited_by']))
            col_metrics[2].metric("全库引用数", total_cit)

            tab_out, tab_in = st.tabs([f"引用了 ({len(graph['cites'])})",
                                        f"被引用 ({len(graph['cited_by'])})"])
            with tab_out:
                if graph["cites"]:
                    for c in graph["cites"]:
                        badge = "DB" if c["in_db"] else "WEB"
                        st.markdown(f"""
                        <div class="paper-card">
                            <div class="title">{badge} {c.get('cited_title') or c['cited_arxiv_id']}</div>
                            <div class="meta"><span>{c['cited_arxiv_id']}</span></div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info("未找到引用记录。")
            with tab_in:
                if graph["cited_by"]:
                    for c in graph["cited_by"]:
                        badge = "DB" if c["in_db"] else "WEB"
                        st.markdown(f"""
                        <div class="paper-card">
                            <div class="title">{badge} {c.get('citing_title') or c['citing_arxiv_id']}</div>
                            <div class="meta"><span>{c['citing_arxiv_id']}</span></div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info("暂无其他论文引用此篇。")

    render_citations()


# ══════════════════════════════════════════════════════════════
#  页面 5: 数据管理
# ══════════════════════════════════════════════════════════════

elif page_key == "data":
    def render_data():
        st.markdown('<div class="page-title">数据管理</div>', unsafe_allow_html=True)
        st.markdown('<p class="page-description">论文入库、数据导出、查询历史管理。</p>',
                    unsafe_allow_html=True)

        tab_inj, tab_exp, tab_hist = st.tabs(["入库", "导出", "历史"])

        with tab_inj:
            st.subheader("论文数据入库")
            stats_ing = get_store_stats()
            st.metric("当前向量库 chunks", stats_ing["count"])

            papers_existing = list_papers()
            if papers_existing:
                with st.expander(f"已入库论文（{len(papers_existing)} 篇）", expanded=False):
                    for p in papers_existing:
                        st.caption(f"{p['arxiv_id']}: {p['title'][:80]}")

            col_i1, col_i2 = st.columns(2)
            with col_i1:
                if st.button("执行入库", type="primary", use_container_width=True):
                    pb = st.progress(0, "扫描解析目录…")
                    try:
                        result = ingest_parsed_dir()
                        pb.progress(100, "完成")
                        if "error" in result:
                            st.error(result["error"])
                        else:
                            st.success(f"{result['papers']} 篇论文、{result['chunks']} chunks 已入库！")
                            st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with col_i2:
                if st.button("清空并重建", type="secondary", use_container_width=True):
                    st.warning("此操作将删除全部向量数据！")
                    if st.button("确认清空", type="primary"):
                        reset_store()
                        result = ingest_parsed_dir()
                        if "error" not in result:
                            st.success(f"重建：{result['papers']} 篇/{result['chunks']} chunks")
                            st.rerun()

        with tab_exp:
            st.subheader("导出数据")
            exp_fmt = st.selectbox("格式", ["json", "csv", "bibtex"], key="exp_fmt")
            exp_limit = st.slider("数量", 10, 500, 100, key="exp_limit")
            exp_type = st.radio("类型", ["论文", "查询历史"], horizontal=True, key="exp_type")

            if st.button("导出", type="primary"):
                if exp_type == "论文":
                    dao = get_dao("paper")
                    papers = dao.find_all(limit=exp_limit)
                    if exp_fmt == "json":
                        data = json.dumps([p.to_dict() for p in papers], ensure_ascii=False, indent=2)
                        st.download_button("下载 JSON", data, "papers.json", "application/json")
                    elif exp_fmt == "csv":
                        buf = io.StringIO()
                        import csv
                        w = csv.writer(buf)
                        w.writerow(["id", "arxiv_id", "title", "authors", "abstract", "published", "source", "status", "chunks"])
                        for p in papers:
                            w.writerow([p.id, p.arxiv_id, p.title, p.authors, p.abstract,
                                        p.published, p.source, p.ingest_status, p.chunk_count])
                        st.download_button("下载 CSV", buf.getvalue(), "papers.csv", "text/csv")
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
                        st.download_button("下载 BibTeX", "\n\n".join(entries), "papers.bib", "text/plain")
                    st.success(f"已导出 {len(papers)} 条记录")
                else:
                    dao = get_dao("query")
                    recs = dao.find_recent(limit=exp_limit)
                    if exp_fmt == "json":
                        data = json.dumps([{"id": r.id, "query": r.query_text, "answer": r.answer_text,
                                            "lang": r.lang, "hits": r.hit_count, "time": r.created_at}
                                           for r in recs], ensure_ascii=False, indent=2)
                        st.download_button("下载 JSON", data, "queries.json", "application/json")
                    else:
                        buf = io.StringIO()
                        import csv
                        w = csv.writer(buf)
                        w.writerow(["id", "query", "answer", "lang", "hits", "created_at"])
                        for r in recs:
                            w.writerow([r.id, r.query_text, r.answer_text, r.lang, r.hit_count, r.created_at])
                        st.download_button("下载 CSV", buf.getvalue(), "queries.csv", "text/csv")
                    st.success(f"已导出 {len(recs)} 条记录")

        with tab_hist:
            st.subheader("查询历史")
            dao_q = get_dao("query")
            records = dao_q.find_recent(limit=30)
            if not records:
                st.info("暂无查询记录。")
            else:
                if st.button("清空历史", type="secondary"):
                    dao_q.clear()
                    st.rerun()
                for r in records:
                    with st.expander(f"{r.query_text[:60]}… — {r.created_at}"):
                        st.caption(f"语言: {r.lang} | 命中: {r.hit_count}")
                        st.markdown(r.answer_text[:500])

    render_data()


# ══════════════════════════════════════════════════════════════
#  页面 6: 系统设置
# ══════════════════════════════════════════════════════════════

elif page_key == "system":
    def render_system():
        st.markdown('<div class="page-title">系统设置</div>', unsafe_allow_html=True)
        st.markdown('<p class="page-description">向量库状态、备份恢复、运行配置。</p>',
                    unsafe_allow_html=True)

        tab_s1, tab_s2, tab_s3 = st.tabs(["状态", "备份", "配置"])

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
                if st.button("清空缓存", type="secondary"):
                    from src.cache import get_llm_cache, get_embed_cache
                    get_llm_cache().clear()
                    get_embed_cache().clear()
                    st.success("已清空")
                    st.rerun()

        with tab_s2:
            st.subheader("向量库备份")
            col_ba, col_bb = st.columns(2)
            with col_ba:
                if st.button("立即备份", type="primary", use_container_width=True):
                    import shutil
                    from datetime import datetime
                    d = config.DATA_DIR / "chroma_backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
                    shutil.copytree(str(config.CHROMA_DIR), str(d))
                    st.success(f"已备份到 {d.name}")
                    st.rerun()

            backup_root = config.DATA_DIR / "chroma_backup"
            if backup_root.exists():
                backups = sorted(backup_root.iterdir(), key=lambda x: x.name, reverse=True)
                for b in backups:
                    if b.is_dir():
                        sz = sum(f.stat().st_size for f in b.rglob("*") if f.is_file())
                        col_n, col_s, col_r = st.columns([3, 1, 1])
                        with col_n:
                            st.text(f"{b.name}")
                        with col_s:
                            st.caption(f"{sz/1024/1024:.1f} MB")
                        with col_r:
                            if st.button("恢复", key=f"rst_{b.name}"):
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
            if st.button("清空向量库", type="secondary"):
                st.warning("不可逆！")
                if st.button("确认清空", type="primary"):
                    result = reset_store()
                    if "error" not in result:
                        st.success("已清空")
                        st.rerun()

    render_system()

# ══════════════════════════════════════════════════════════════
#  Dialog — st.dialog 渲染在页面 DOM 外部，不受页面 CSS 影响
# ══════════════════════════════════════════════════════════════

if st.session_state.get("show_auth"):
    render_auth_dialog()

