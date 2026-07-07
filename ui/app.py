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
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st

import config
from src.cache import get_cache_stats
from src.db import get_dao
from src.rag import (
    analyze_all_papers,
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
#  性能优化：缓存 DAO 和 Store 连接，减少 sidebar 导航延迟
# ══════════════════════════════════════════════════════════════

@st.cache_resource(show_spinner=False)
def _cached_get_dao(name: str):
    """缓存 DAO 实例，避免每次 rerun 重建。"""
    return get_dao(name)


@st.cache_resource(show_spinner=False)
def _cached_get_store():
    """缓存 VectorStore 实例。"""
    from src.store import get_store
    return get_store()


@st.cache_data(ttl=30, show_spinner=False)
def _cached_list_papers(owner_id: str):
    """缓存论文列表（30 秒 TTL），减少重复查询。"""
    return list_papers(owner_id=owner_id)


@st.cache_data(ttl=30, show_spinner=False)
def _cached_store_stats():
    """缓存向量库统计。"""
    return get_store_stats()


@st.cache_data(ttl=60, show_spinner=False)
def _cached_cache_stats():
    """缓存缓存统计。"""
    return get_cache_stats()

# ══════════════════════════════════════════════════════════════
#  Session State 初始化
# ══════════════════════════════════════════════════════════════

DEFAULTS = {
    "user": None,              # 当前登录用户
    "owner_id": "",            # 会话标识（匿名 UUID 或登录后 user_id）
    "show_auth": False,        # 是否显示登录弹窗
    "auth_mode": "login",      # "login" | "register"
    "auth_error": "",          # 认证错误消息
    "auth_success_msg": "",    # 认证成功提示（绿色）
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Session 管理: 匿名用户生成 UUID，登录用户用 user_id ──
if not st.session_state.owner_id:
    st.session_state.owner_id = uuid.uuid4().hex
# Cookie 持久化（跨页面刷新保留）
st.components.v1.html(f"""
<script>
(function(){{
    var name = '{config.SESSION_COOKIE}';
    var val = '{st.session_state.owner_id}';
    var days = {config.SESSION_TTL_DAYS};
    var d = new Date();
    d.setTime(d.getTime() + days*86400000);
    document.cookie = name + '=' + val + ';path=/;expires=' + d.toUTCString();
}})();
</script>
""", height=0)

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
    ("agent",     "智能分析"),
    ("library",   "论文库"),
    ("summary",   "摘要 & 综述"),
    ("citations", "引用关系"),
    ("data",      "数据管理"),
    ("system",    "系统设置"),
    ("help",      "帮助"),
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

    # 解析 arXiv 分类
    cat_label = ""
    if p.source and p.source.startswith("arxiv:"):
        cat_label = p.source.split(":", 1)[1]

    html = f"""
    <div class="paper-card">
        <div class="title">{p.title or p.arxiv_id}</div>
        <div class="authors">{p.authors or '未知作者'}</div>
        <div class="meta">
            <span>{p.published or '未知'}</span>
            <span>{p.arxiv_id}</span>
            {f'<span class="badge badge-info">{cat_label}</span>' if cat_label else ''}
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
        owner_id = st.session_state.owner_id
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

        col_btn, col_lang, col_temp, col_mode = st.columns([1, 1.5, 1, 1.5])
        with col_btn:
            ask = st.button("搜索回答", type="primary", use_container_width=True,
                           disabled=not query.strip())
        with col_lang:
            lang_qa = st.selectbox("语言", ["zh", "en"],
                                   format_func=lambda x: "中文" if x == "zh" else "English",
                                   label_visibility="collapsed")
        with col_temp:
            qa_temperature = st.slider("温度", 0.0, 1.5, 0.3, 0.1,
                                       label_visibility="collapsed", key="qa_temp",
                                       help="越低越严谨，越高越有创造性")
        with col_mode:
            global_mode = st.checkbox("全局分析模式", value=False, key="qa_global",
                                       help="针对「所有论文的主旨」等全局问题，汇总全部论文元数据进行分析")

        if ask:
            if global_mode:
                # ── 全局分析：汇总所有论文元数据 ──
                with st.spinner("正在汇总所有论文数据…"):
                    result = analyze_all_papers(query=query, lang=lang_qa, owner_id=owner_id)
                st.markdown("### 全局分析结果")
                st.markdown(result)
            else:
                # ── 普通 RAG 检索 ──
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
                for token in answer_rag_stream(query, top_k=top_k, lang=lang_qa, temperature=qa_temperature):
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
        st.markdown('<div class="page-title">智能分析</div>', unsafe_allow_html=True)
        st.markdown('<p class="page-description">AI Agent 自主调用搜索、摘要、对比、引用等工具，多步推理处理复杂研究问题。</p>',
                    unsafe_allow_html=True)

        col_q2, col_s2 = st.columns([4, 1])
        with col_q2:
            agent_query = st.text_area(
                "描述你的研究问题…",
                placeholder="例如：找出 VLM 在机器人操作中的最新论文，总结技术路线并推荐研究方向",
                label_visibility="collapsed", height=80, key="agent_query",
            )
        with col_s2:
            agent_lang = st.selectbox("语言", ["zh", "en"],
                                      format_func=lambda x: "中文" if x == "zh" else "English",
                                      key="agent_lang")
            agent_iter = st.slider("步数", 1, 20, 10, key="agent_iter")
            agent_temp = st.slider("温度", 0.0, 1.5, 0.1, 0.1,
                                   label_visibility="visible", key="agent_temp",
                                   help="越低越严谨，越高越有创造性")

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
                for event in run_agent_stream(query=agent_query, lang=agent_lang, max_iterations=agent_iter, temperature=agent_temp):
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
        owner_id = st.session_state.owner_id
        st.markdown('<div class="page-title">论文库</div>', unsafe_allow_html=True)
        st.markdown('<p class="page-description">浏览、搜索和管理已入库的学术论文。论文需经过"抓取 → 下载 → 解析 → 入库"四步才能用于问答。</p>',
                    unsafe_allow_html=True)

        dao = get_dao("paper")

        # ── 快速操作栏 ──
        col_imp, col_path, _ = st.columns([1.5, 2, 3])
        with col_imp:
            if st.button("导入本地论文", type="secondary", use_container_width=True,
                        help="扫描 parsed/ 目录下的 JSON 文件并向量化入库"):
                with st.spinner("导入中..."):
                    result = ingest_parsed_dir(owner_id=owner_id)
                    if "error" in result:
                        st.error(result["error"])
                    else:
                        st.success(f"已导入 {result.get('papers', 0)} 篇，{result.get('chunks', 0)} 个片段")
                        st.rerun()
        with col_path:
            custom_dir = st.text_input(
                "自定义解析目录", placeholder=f"留空={config.PARSED_DIR}",
                label_visibility="collapsed", key="custom_parsed_dir",
                help="输入包含 JSON 解析文件的目录路径，留空使用默认路径",
            )
            if custom_dir.strip():
                import_dir = Path(custom_dir.strip())
                if import_dir.exists() and import_dir.is_dir():
                    if st.button("📂 从此目录导入", key="import_custom_dir", use_container_width=True):
                        with st.spinner(f"从 {import_dir} 导入中..."):
                            result = ingest_parsed_dir(parsed_dir=str(import_dir), owner_id=owner_id)
                            if "error" in result:
                                st.error(result["error"])
                            else:
                                st.success(f"已导入 {result.get('papers', 0)} 篇，{result.get('chunks', 0)} 个片段")
                                st.rerun()
                else:
                    st.caption(f"⚠️ 目录不存在: {import_dir}")

        # ── arXiv 抓取 ──
        with st.expander("📥 从 arXiv 抓取论文", expanded=False):
            _api_headers = {}
            if config.API_AUTH_ENABLED and config.API_AUTH_KEY:
                _api_headers["X-API-Key"] = config.API_AUTH_KEY
            _api_headers["X-Owner-Id"] = st.session_state.owner_id

            col_q1, col_q2, col_q3 = st.columns([3, 1, 1])
            with col_q1:
                fetch_query = st.text_input(
                    "arXiv 查询", value=config.ARXIV_QUERY,
                    placeholder="cat:cs.AI AND ti:learning",
                    help="arXiv API 搜索语法：cat:cs.CL (分类), ti:transformer (标题), au:bengio (作者)",
                    key="arxiv_query",
                )
            with col_q2:
                fetch_n = st.number_input("篇数", min_value=1, max_value=50, value=5, key="arxiv_n")
            with col_q3:
                st.write("")  # spacer
                do_fetch = st.button("⚡ 一键抓取", use_container_width=True, type="primary",
                                     key="arxiv_pipeline_btn",
                                     help="搜索 arXiv → 下载 PDF → 解析 → 入库 全自动")

            if do_fetch:
                with st.spinner("搜索 arXiv → 下载 PDF → 解析 → 入库…"):
                    try:
                        resp = requests.post(
                            f"http://127.0.0.1:{config.API_PORT}/arxiv/pipeline",
                            json={"query": fetch_query, "max_results": fetch_n, "auto_ingest": True},
                            headers=_api_headers, timeout=600,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            for s in data.get("steps", []):
                                icons = {"fetch": "🔍 搜索", "download": "📄 下载",
                                         "parse": "📝 解析", "ingest": "📦 入库"}
                                label = icons.get(s["step"], s["step"])
                                if s["step"] == "fetch":
                                    st.write(f"{label}: 找到 {s['count']} 篇")
                                elif s["step"] == "download":
                                    failed = s.get("failed", 0)
                                    extra = f", 失败 {failed} 篇" if failed else ""
                                    st.write(f"{label}: 成功 {s['success']} 篇{extra}")
                                    if failed > 0:
                                        st.warning(
                                            f"⚠️ {failed} 篇 PDF 下载失败。"
                                            f"可能原因：arXiv 限流、网络不稳定、PDF 地址失效。"
                                            f"可稍后点击「处理」按钮重试下载。"
                                        )
                                elif s["step"] == "parse":
                                    st.write(f"{label}: {s['count']} 篇")
                                elif s["step"] == "ingest":
                                    st.write(f"{label}: {s['papers']} 篇 / {s['chunks']} chunks")
                            st.success("管道完成！同名论文自动去重。")
                            st.rerun()
                        else:
                            detail = resp.json().get("detail", str(resp.status_code))
                            if "Connection" in str(detail) or "RemoteDisconnected" in str(detail):
                                st.error(
                                    f"arXiv 连接失败：{detail}\n\n"
                                    "可能原因：\n"
                                    "1. 服务器网络无法访问 arXiv API\n"
                                    "2. arXiv 临时限流\n"
                                    "3. DNS 解析异常\n\n"
                                    "建议：稍后重试，或检查服务器网络 `curl http://export.arxiv.org/api/query`"
                                )
                            else:
                                st.error(detail)
                    except requests.exceptions.ConnectionError:
                        st.error(
                            "⚠️ 无法连接到本地 API 服务。请确保后端服务正在运行。\n"
                            f"检查：`curl http://127.0.0.1:{config.API_PORT}/health`"
                        )
                    except requests.exceptions.Timeout:
                        st.error(
                            "⏱️ 请求超时（10分钟）。arXiv 下载可能因网络慢或论文太多导致。\n"
                            "建议：减少抓取篇数（如 1-2 篇），或检查服务器网络速度。"
                        )
                    except Exception as e:
                        st.error(f"抓取失败: {e}")

            # 显示当前待处理数
            pending_count = len([p for p in dao.find_all(limit=200, owner_id=owner_id) if p.ingest_status == "pending"])
            if pending_count > 0:
                st.info(f"📋 {pending_count} 篇论文仅有元数据，可点击下方按钮处理", icon="ℹ️")

        # ── 处理待处理论文 ──
        pending_count = len([p for p in dao.find_all(limit=200, owner_id=owner_id) if p.ingest_status == "pending"])
        if pending_count > 0:
            col_p1, col_p2 = st.columns([3, 1])
            with col_p1:
                st.warning(f"📋 {pending_count} 篇论文待处理（已搜索但未下载/解析/入库）", icon="⚠️")
            with col_p2:
                if st.button("🔧 处理", type="primary", key="process_pending_btn",
                            help=f"下载 PDF → 解析 → 入库 ({pending_count} 篇)"):
                    with st.spinner(f"处理 {pending_count} 篇论文…"):
                        try:
                            resp = requests.post(
                                f"http://127.0.0.1:{config.API_PORT}/arxiv/process-pending",
                                headers=_api_headers, timeout=600,
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                st.success(
                                    f"下载 {data['downloaded']} / "
                                    f"解析 {data['parsed']} / "
                                    f"入库 {data['ingested']} ({data['chunks']} chunks)"
                                )
                                st.rerun()
                            else:
                                st.error(str(resp.json()))
                        except Exception as e:
                            st.error(str(e))

        total = dao.count(owner_id=owner_id)

        col1, col2, col3, col4 = st.columns([2, 1.5, 1, 1])
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
        with col4:
            limit = st.selectbox("每页", [10, 20, 50, 100], index=1, label_visibility="collapsed")

        col_a2, col_b2, col_c2, col_d2 = st.columns([3, 1, 1, 1])
        with col_a2:
            author = st.text_input("作者", placeholder="模糊匹配", label_visibility="collapsed")
        with col_b2:
            status_filter = st.selectbox("状态", ["", "ingested", "pending", "failed"],
                                         format_func=lambda x: {"": "全部", "ingested": "入库", "pending": "待处理", "failed": "失败"}[x],
                                         label_visibility="collapsed")
        with col_c2:
            # 分页页码
            total_pages = max(1, (total + limit - 1) // limit) if not (keyword or author or year_from or year_to or status_filter) else 1
            page = st.number_input("页码", min_value=1, max_value=max(1, total_pages), value=1,
                                   label_visibility="collapsed", key="paper_page")
        with col_d2:
            st.write("")  # spacer

        offset = (page - 1) * limit

        has_filter = keyword or author or year_from or year_to or status_filter
        if has_filter:
            # 搜索时不限制 offset（搜索模式下不翻页，结果一般较少）
            papers = dao.search(
                keyword=keyword, limit=limit * 5, author=author,
                year_from=year_from, year_to=year_to,
                status=status_filter, sort_by=sort_by,
                owner_id=owner_id,
            )
            result_count = len(papers)
            papers = papers[offset:offset + limit]
        else:
            papers = dao.find_all(limit=limit, offset=offset, owner_id=owner_id)
            result_count = total

        st.caption(f"第 {page}/{max(1, total_pages)} 页，共 {result_count} 条结果（全库 {total} 篇）")

        if not papers:
            st.info("未找到匹配的论文。")
        else:
            for p in papers:
                with st.container():
                    # ── 论文标题可点击展开，浏览分块/原文 ──
                    with st.expander(f"📄 {p.title or p.arxiv_id} — {p.authors or '未知'}"):
                        tab_chunks, tab_original, tab_meta = st.tabs(["分块内容", "原文", "元数据"])

                        with tab_chunks:
                            from src.store import get_store
                            store = get_store()
                            try:
                                chunks = store.peek(limit=500)
                                paper_chunks = [
                                    c for c in chunks
                                    if (c.get("metadata") or {}).get("arxiv_id") == p.arxiv_id
                                ]
                                if paper_chunks:
                                    for ci, chunk in enumerate(paper_chunks[:20], 1):
                                        meta = chunk.get("metadata") or {}
                                        section = meta.get("section_title", "")
                                        page_num = meta.get("page", "")
                                        doc_text = (chunk.get("document") or "")[:600]
                                        st.caption(f"**Chunk {ci}** | {section} | p.{page_num}")
                                        st.text(doc_text)
                                        st.divider()
                                    if len(paper_chunks) > 20:
                                        st.caption(f"… 仅显示前 20 个分块（共 {len(paper_chunks)} 个）")
                                else:
                                    st.info("暂无分块数据，请先入库。")
                            except Exception as e:
                                st.warning(f"无法加载分块: {e}")

                        with tab_original:
                            json_path = config.PARSED_DIR / f"{p.arxiv_id}.json"
                            if json_path.exists():
                                try:
                                    data = json.loads(json_path.read_text(encoding="utf-8"))
                                    sections = data.get("sections", [])
                                    for sec in sections:
                                        title = sec.get("title", "Untitled")
                                        content = sec.get("content", "")
                                        with st.expander(f"📑 {title}", expanded=False):
                                            st.text(content[:2000] if len(content) > 2000 else content)
                                            if len(content) > 2000:
                                                st.caption(f"… 内容过长，仅显示前 2000 字符（共 {len(content)} 字符）")
                                            for sub in sec.get("subsections", []):
                                                sub_title = sub.get("title", "")
                                                sub_content = sub.get("content", "")
                                                st.caption(f"**{sub_title}**")
                                                st.text(sub_content[:1000] if len(sub_content) > 1000 else sub_content)
                                                if len(sub_content) > 1000:
                                                    st.caption("… (截断)")
                                except Exception as e:
                                    st.warning(f"无法解析原文: {e}")
                            else:
                                st.info(f"解析文件不存在: {json_path}")

                        with tab_meta:
                            st.json({
                                "arxiv_id": p.arxiv_id,
                                "title": p.title,
                                "authors": p.authors,
                                "abstract": p.abstract,
                                "published": p.published,
                                "source": p.source,
                                "status": p.ingest_status,
                                "chunks": p.chunk_count,
                                "pdf_url": p.pdf_url,
                            })

    render_library()


# ══════════════════════════════════════════════════════════════
#  页面 3: 摘要 & 综述
# ══════════════════════════════════════════════════════════════

elif page_key == "summary":
    def render_summary():
        owner_id = st.session_state.owner_id
        st.markdown('<div class="page-title">摘要 & 综述</div>', unsafe_allow_html=True)
        st.markdown('<p class="page-description">生成论文摘要、多论文综述，或基于向量相似度推荐相关研究。</p>',
                    unsafe_allow_html=True)

        tab_sum, tab_sur, tab_rec = st.tabs(["论文摘要", "综述生成", "相似推荐"])

        with tab_sum:
            st.subheader("生成单篇论文的结构化摘要")
            papers = list_papers(owner_id=owner_id)
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
                    # 使用 st.markdown 渲染 Markdown 格式，去除 * 标记显示
                    import re as _re
                    clean_result = _re.sub(r'^\s*\*\s*', '- ', result, flags=_re.MULTILINE)
                    st.markdown(clean_result)

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
                # 使用 st.markdown 渲染 Markdown，去除 * 标记显示
                import re as _re
                clean_result = _re.sub(r'^\s*\*\s*', '- ', result, flags=_re.MULTILINE)
                st.markdown(clean_result)

        with tab_rec:
            st.subheader("基于向量相似度推荐相似论文")
            papers_r = list_papers(owner_id=owner_id)
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
        owner_id = st.session_state.owner_id
        st.markdown('<div class="page-title">引用关系</div>', unsafe_allow_html=True)
        st.markdown('<p class="page-description">查看论文之间的引用关系，提取和分析引用图谱。</p>',
                    unsafe_allow_html=True)

        papers = list_papers(owner_id=owner_id)
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
        owner_id = st.session_state.owner_id
        st.markdown('<div class="page-title">数据管理</div>', unsafe_allow_html=True)
        st.markdown('<p class="page-description">论文入库、数据导出、查询历史管理。</p>',
                    unsafe_allow_html=True)

        tab_inj, tab_exp, tab_hist = st.tabs(["入库", "导出", "历史"])

        with tab_inj:
            st.subheader("论文数据入库")
            st.caption(
                "入库条件：论文的 PDF 已放在 raw/ 目录，且 parsed/ 目录已有对应 JSON 解析文件。"
                "可通过「论文库 → 一键抓取」自动完成全流程。"
            )
            stats_ing = get_store_stats()
            st.metric("当前向量库 chunks", stats_ing["count"])

            papers_existing = list_papers(owner_id=owner_id)
            if papers_existing:
                with st.expander(f"已入库论文（{len(papers_existing)} 篇）", expanded=False):
                    for p in papers_existing:
                        st.caption(f"{p['arxiv_id']}: {p['title'][:80]}")

            col_i1, col_i2 = st.columns(2)
            with col_i1:
                if st.button("执行入库", type="primary", use_container_width=True,
                            help="将 parsed/ 目录下所有 JSON 解析文件向量化入库"):
                    pb = st.progress(0, "扫描解析目录…")
                    try:
                        result = ingest_parsed_dir(owner_id=owner_id)
                        pb.progress(100, "完成")
                        if "error" in result:
                            st.error(result["error"])
                        else:
                            st.success(f"{result['papers']} 篇论文、{result['chunks']} chunks 已入库！")
                            st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with col_i2:
                if st.button("🗑️ 清空并重建", type="secondary", use_container_width=True,
                            help="删除向量库全部数据后重新导入——不可逆！"):
                    st.error("⚠️ 此操作将删除你名下全部向量数据，不可撤销！")
                    st.markdown(
                        "- 论文元数据（SQLite）不受影响\n"
                        "- 向量检索结果将暂时为空\n"
                        "- 有 parsed JSON 则可重新入库\n"
                        "- 建议先用「导出」备份"
                    )
                    if st.button("我确认，立即清空", type="primary"):
                        reset_store()
                        result = ingest_parsed_dir(owner_id=owner_id)
                        if "error" not in result:
                            st.success(f"重建完成：{result['papers']} 篇 / {result['chunks']} chunks")
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
                llm_s = cs.get("llm", {})
                embed_s = cs.get("embed", {})

                col_l1, col_l2 = st.columns(2)
                with col_l1:
                    st.metric("LLM 命中率", llm_s.get("hit_rate_pct", f"{llm_s.get('hit_rate', 0)*100:.1f}%"))
                with col_l2:
                    st.metric("Embed 命中率", embed_s.get("hit_rate_pct", f"{embed_s.get('hit_rate', 0)*100:.1f}%"))

                st.caption(f"LLM — hits: {llm_s.get('hits', 0)} / misses: {llm_s.get('misses', 0)} "
                           f"| 估算节省: {llm_s.get('estimated_tokens_saved', 0):,} tokens "
                           f"| 效率: {llm_s.get('efficiency', 'N/A')}")
                st.caption(f"Embed — hits: {embed_s.get('hits', 0)} / misses: {embed_s.get('misses', 0)} "
                           f"| 缓存数: {embed_s.get('size', 0)} / {embed_s.get('maxsize', 0)}")

                # 汇总评估数字
                total_requests = llm_s.get('total_requests', 0) + embed_s.get('total_requests', 0)
                total_saved = llm_s.get('estimated_tokens_saved', 0)
                if total_requests > 0:
                    st.metric("总请求数", total_requests)
                    st.metric("估算 Token 节省", f"{total_saved:,}")
                    # 按 $0.002/1K tokens (GPT-4o-mini) 粗略估算成本节省
                    est_cost_saved = total_saved / 1000 * 0.002
                    st.caption(f"💡 估算成本节省: ${est_cost_saved:.4f} (按 GPT-4o-mini 定价)")

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

# ── 页面 7: 帮助 ──

elif page_key == "help":
    def render_help():
        st.markdown('<div class="page-title">帮助</div>', unsafe_allow_html=True)

        with st.expander("论文是怎么从 arXiv 到你眼前的？", expanded=True):
            st.markdown("""
            每篇论文要经过 **4 个步骤** 才能用来提问：

            | 步骤 | 做什么 | 成功标志 |
            |------|--------|----------|
            | 1. 搜索 | 从 arXiv 找到论文标题、作者、摘要 | 论文出现在列表中 |
            | 2. 下载 | 下载 PDF 到 `data/raw/` | 文件存在 |
            | 3. 解析 | 把 PDF 转成结构化的 JSON | 生成 `data/parsed/*.json` |
            | 4. 入库 | 切成小片段，转成向量，存进 ChromaDB | chunk 数 > 0 |

            **如果显示 "0块"**，说明论文卡在第 2、3 或 4 步。原因可能是：
            - PDF 下载失败（网络问题、arXiv 限流）
            - PDF 格式异常（扫描版、加密、非标准排版）
            - 解析后 JSON 为空
            - Embedding API 不兼容（如 DeepSeek/MiniMax 不支持 embedding）
              → 设置 `EMBEDDING_PROVIDER=local` 使用本地模型

            **解决办法：** 点击「论文库」页面下方的 **"处理"** 按钮，系统会自动重试下载→解析→入库。
            如果多次失败，可去「数据管理」页面查看入库报错，或检查「系统设置」中的 embedding 配置。
            """)

        with st.expander("arXiv 搜索语法说明"):
            st.markdown("""
            在「论文库」的抓取框里可以用这些语法精确搜索：

            | 语法 | 含义 | 例 |
            |------|------|-----|
            | `cat:cs.AI` | 限定分类 | `cat:cs.CL` 只搜计算语言学 |
            | `ti:关键词` | 搜标题 | `ti:transformer` 标题含 transformer |
            | `au:作者` | 搜作者 | `au:bengio` Yoshua Bengio 的论文 |
            | `abs:关键词` | 搜摘要 | `abs:reinforcement learning` |
            | `AND` / `OR` | 组合条件 | `cat:cs.AI AND ti:robot` |

            **常用 arXiv 分类：**
            - `cs.AI` — 人工智能
            - `cs.CL` — 计算语言学 / NLP
            - `cs.CV` — 计算机视觉
            - `cs.LG` — 机器学习
            - `cs.RO` — 机器人学
            - `stat.ML` — 统计机器学习
            """)

        with st.expander("论文语言问题的说明"):
            st.markdown("""
            **抓到的论文是原文，没有翻译过。** 大部分 arXiv 论文是英文。

            系统的"语言"选项控制的是 **AI 用哪种语言回答你**，不是翻译论文内容：
            - 选择"中文"：AI 用中文回答，但引用的论文原文仍是英文
            - 选择"English"：AI 用英文回答

            如果你看到标题/摘要是中文的，那是原作者自己写的中文 —— arXiv 上确实有一些中文论文，特别是国内学者投稿的。
            """)

        with st.expander("智能问答 vs 智能分析 — 何时用哪个？"):
            st.markdown("""
            | | 智能问答 | 智能分析 (Agent) |
            |--|---------|-----------------|
            | 怎么工作 | 向量检索 → 一次性回答 | AI 自主调用工具，分步执行 |
            | 全局分析 | ✅ 支持（勾选"全局分析模式"） | ❌ 不适合（步数限制） |
            | 具体问题 | ✅ 最佳选择 | ✅ 也可以 |
            | 综合研究 | ⚠️ 受检索片段限制 | ✅ 最佳选择 |
            | 速度 | 快（1次 LLM 调用） | 慢（5-20 次 LLM 调用） |
            | Token 消耗 | 低 | 高 |

            **选择指南：**
            - 问「所有论文的主旨是什么」→ 智能问答 + ✅ 全局分析模式
            - 问「这篇论文的贡献」→ 智能问答
            - 说「帮我梳理 VLM 的技术路线」→ 智能分析

            **全局分析模式** 会汇总全部论文的标题和摘要交给 AI 分析，适合宏观了解论文库。
            与智能分析的区别：全局分析走一次性汇总（快），智能分析走 Agent 多步推理（深）。
            """)

        with st.expander("温度 (Temperature) 是什么？"):
            st.markdown("""
            温度控制 AI 回答的**随机性**：

            - **0 ~ 0.3（低）**：回答稳定、严谨、重复性强。适合需要准确答案的场合
            - **0.3 ~ 0.7（中）**：平衡创造性和准确性。适合一般问答
            - **0.7 ~ 1.5（高）**：回答多变、有创造性、也可能跑偏。适合头脑风暴

            默认值是 0.3（问答）和 0.1（智能分析），对学术用途来说偏低是合理的。
            """)

        with st.expander("论文库浏览与分页"):
            st.markdown("""
            **点击论文标题** 即可展开查看：
            - **分块内容**：向量化入库后的文本片段（chunks），展示每段的章节来源和页码
            - **原文**：解析后的结构化原文，按章节展示
            - **元数据**：arXiv ID、标题、作者、摘要等信息

            **分页功能**：论文超过一页时可翻页浏览（10/20/50/100 每页可选）。

            **搜索**：支持按关键词（全文搜索）、作者、年份范围、入库状态筛选。

            **导入本地论文**：可以指定自定义解析目录（JSON 文件目录），不局限于默认的 `data/parsed/`。
            """)

        with st.expander("缓存机制与 Token 节省"):
            st.markdown("""
            **两层缓存：**

            | 缓存层 | TTL | 容量 | 命中条件 |
            |--------|-----|------|----------|
            | LLM 缓存 | 30 分钟 | 200 条 | 相同的 query + context + lang + task |
            | Embedding 缓存 | 24 小时 | 2000 条 | 相同的文本 + provider |

            **摘要缓存优化：** 同一篇论文反复生成摘要时，基于论文 ID + 全文哈希做缓存 key，确保相同内容 100% 命中缓存，大幅减少 token 消耗。

            **缓存统计查看：** 系统设置 → 状态 → 缓存，可看到命中率、估算 Token 节省、成本估算。
            估算成本按 GPT-4o-mini 定价（$0.002/1K tokens）计算，仅作参考。

            **清空缓存：** 进入系统设置点击「清空缓存」即可重置所有缓存统计数据。
            """)

        with st.expander("代码块、数学公式等特殊内容"):
            st.markdown("""
            当前系统对论文正文做**纯文本处理**，对特殊内容有限制：

            | 内容类型 | 处理方式 |
            |---------|---------|
            | 普通段落文字 | 正常分块、检索、问答 |
            | 数学公式 (LaTeX) | 作为纯文本保留，可能被截断 |
            | 代码块 | 分块时保护不被裁断 |
            | 表格 | GROBID 引擎可提取为 Markdown，但暂未加入检索 |
            | 图片/图表 | 仅提取标题，图片内容不处理 |
            | 多栏排版 | 按文档顺序读取，可能打乱阅读顺序 |

            如果你研究的论文含有大量公式或代码，**问答时尽量描述概念而非直接复制公式**，检索效果更好。
            """)

        with st.expander("各页面功能速览"):
            st.markdown("""
            | 页面 | 一句话说明 |
            |------|-----------|
            | 智能问答 | 对已有论文提问（支持全局分析模式分析全部论文主旨） |
            | 智能分析 | AI 自主使用 7 种工具完成复杂研究任务 |
            | 论文库 | 搜索 arXiv、管理论文、点击标题浏览分块/原文 |
            | 摘要 & 综述 | 生成单篇摘要、多篇综述、找相似论文 |
            | 引用关系 | 查看论文之间的引用网络 |
            | 数据管理 | 入库、导出、备份数据 |
            | 系统设置 | 查看状态、清缓存、备份恢复、成本估算 |
            """)

        with st.expander("常见问题"):
            st.markdown("""
            **Q: 论文显示了但"块数"是 0？**
            A: 论文还没入库。在论文库点击"处理"按钮，系统会自动下载 PDF → 解析 → 向量化。

            **Q: 怎么看不到我刚抓的论文？**
            A: 检查页面搜索框是否清空，或确认论文状态是"已入库"而非"待处理"。可用分页翻页查找。

            **Q: 问答说"向量库为空"？**
            A: 没有论文入库过。先去论文库抓论文并点击"处理"，或去数据管理页面执行"入库"。

            **Q: 问"所有论文的主旨"答不上来？**
            A: 勾选智能问答页面的 **「全局分析模式」** 复选框，系统会汇总全部论文的标题+摘要做分析。

            **Q: Agent 回答不完整或报错？**
            A: 可能是步数不够或上下文超限。增加步数滑块值（建议 15-20），或缩短问题复杂度。
            如遇到 "Messages with role 'tool'" 错误，刷新页面重试即可（已修复上下文截断 bug）。

            **Q: 摘要结果有 * 标记不好看？**
            A: 已修复。摘要现在使用 Markdown 渲染，`*` 会正常显示为列表项。

            **Q: 同一篇论文反复摘要消耗太多 token？**
            A: 已优化。同一论文+相同内容第二次生成摘要时，会直接命中缓存，不再调用 LLM。
            可在系统设置查看缓存命中率和估算节省。

            **Q: 多个用户的数据会混在一起吗？**
            A: 不会。每个用户的数据通过 owner_id 隔离，互不可见。

            **Q: 会不会重复搜索已入库的论文？**
            A: 不会。系统自动跳过已入库论文（状态为"已入库"），只抓取新论文。待处理/失败的论文仍会重试。

            **Q: arXiv 抓取失败怎么办？**
            A: arXiv API 可能限流或网络不稳定。系统已内置断点续传和指数退避重试。可等待几分钟后重试。
            如持续失败，检查服务器网络：`curl -I http://export.arxiv.org/api/query`。

            **Q: 左侧导航切换慢？**
            A: Streamlit 的限制，每次切换会刷新整个页面。已优化缓存策略以加快加载速度。
            """)

    render_help()

# ══════════════════════════════════════════════════════════════
#  Dialog — st.dialog 渲染在页面 DOM 外部，不受页面 CSS 影响
# ══════════════════════════════════════════════════════════════

if st.session_state.get("show_auth"):
    render_auth_dialog()

