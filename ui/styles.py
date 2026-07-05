"""Paper Assistant UI 主题样式。

Perplexity AI + Semantic Scholar 风格：
- 学术蓝主色调，干净的白底灰卡
- 论文卡片、对话气泡、流式输出动画
"""

from __future__ import annotations

# ── 调色板 ──

PRIMARY = "#2563EB"       # 学术蓝
PRIMARY_LIGHT = "#DBEAFE"  # 浅蓝背景
PRIMARY_DARK = "#1E40AF"   # 深蓝（hover）
ACCENT = "#7C3AED"         # 紫色强调
SUCCESS = "#059669"
WARNING = "#D97706"
DANGER = "#DC2626"
BG = "#FAFAFA"             # 页面背景
CARD_BG = "#FFFFFF"        # 卡片背景
TEXT_PRIMARY = "#111827"
TEXT_SECONDARY = "#6B7280"
TEXT_MUTED = "#9CA3AF"
BORDER = "#E5E7EB"
BORDER_LIGHT = "#F3F4F6"

# ── CSS 注入 ──

CSS = """
<style>
/* ═══════════════════════════════════════════
   全局重置
   ═══════════════════════════════════════════ */

@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

* {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.stApp {
    background: #FAFAFA;
}

/* 去除默认 padding */
.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 2rem !important;
    max-width: 1100px !important;
}

/* ═══════════════════════════════════════════
   侧边栏
   ═══════════════════════════════════════════ */

[data-testid="stSidebar"] {
    background: #FFFFFF;
    border-right: 1px solid #E5E7EB;
}

[data-testid="stSidebar"] .block-container {
    padding: 1.5rem 1rem;
}

[data-testid="stSidebar"] [data-testid="stMarkdown"] h1 {
    font-size: 1.25rem;
    font-weight: 700;
    color: #111827;
    margin-bottom: 0.25rem;
}

[data-testid="stSidebar"] hr {
    margin: 1rem 0;
    border-color: #E5E7EB;
}

/* 侧边栏导航 */
[data-testid="stSidebar"] .stRadio > div {
    gap: 0.25rem;
}

[data-testid="stSidebar"] .stRadio label {
    padding: 0.5rem 0.75rem;
    border-radius: 8px;
    transition: all 0.15s ease;
    font-size: 0.9rem;
    color: #374151;
}

[data-testid="stSidebar"] .stRadio label:hover {
    background: #F3F4F6;
}

[data-testid="stSidebar"] .stRadio label[data-selected="true"] {
    background: #DBEAFE;
    color: #1E40AF;
    font-weight: 500;
}

/* ═══════════════════════════════════════════
   搜索栏 — Perplexity 风格
   ═══════════════════════════════════════════ */

.hero-search {
    text-align: center;
    padding: 3rem 1rem 2rem;
}

.hero-search h1 {
    font-size: 2rem;
    font-weight: 700;
    color: #111827;
    margin-bottom: 0.5rem;
}

.hero-search p {
    font-size: 1rem;
    color: #6B7280;
    margin-bottom: 2rem;
}

.hero-search .stTextArea textarea,
.hero-search .stTextInput input {
    border: 2px solid #E5E7EB;
    border-radius: 16px;
    padding: 1rem 1.25rem;
    font-size: 1.05rem;
    transition: all 0.2s ease;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    background: #FFFFFF;
}

.hero-search .stTextArea textarea:focus,
.hero-search .stTextInput input:focus {
    border-color: #2563EB;
    box-shadow: 0 0 0 4px rgba(37,99,235,0.1);
    outline: none;
}

/* ═══════════════════════════════════════════
   论文卡片 — Semantic Scholar 风格
   ═══════════════════════════════════════════ */

.paper-card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 0.75rem;
    transition: all 0.15s ease;
    cursor: pointer;
}

.paper-card:hover {
    border-color: #2563EB;
    box-shadow: 0 4px 12px rgba(37,99,235,0.08);
    transform: translateY(-1px);
}

.paper-card .title {
    font-size: 1.1rem;
    font-weight: 600;
    color: #1E40AF;
    margin-bottom: 0.35rem;
    line-height: 1.4;
}

.paper-card .authors {
    font-size: 0.85rem;
    color: #6B7280;
    margin-bottom: 0.35rem;
}

.paper-card .meta {
    display: flex;
    gap: 1rem;
    font-size: 0.8rem;
    color: #9CA3AF;
    margin-bottom: 0.5rem;
}

.paper-card .meta span {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
}

.paper-card .abstract {
    font-size: 0.875rem;
    color: #4B5563;
    line-height: 1.55;
}

/* badge */
.badge {
    display: inline-flex;
    align-items: center;
    padding: 0.15rem 0.6rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 500;
    gap: 0.25rem;
}

.badge-success { background: #D1FAE5; color: #065F46; }
.badge-warning { background: #FEF3C7; color: #92400E; }
.badge-info    { background: #DBEAFE; color: #1E40AF; }
.badge-muted   { background: #F3F4F6; color: #6B7280; }

/* ═══════════════════════════════════════════
   对话/问答气泡
   ═══════════════════════════════════════════ */

.chat-container {
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.chat-bubble {
    padding: 1rem 1.25rem;
    border-radius: 16px;
    max-width: 90%;
    line-height: 1.6;
    font-size: 0.95rem;
    animation: fadeInUp 0.3s ease;
}

.chat-bubble.user {
    align-self: flex-end;
    background: #DBEAFE;
    color: #1E40AF;
    border-bottom-right-radius: 6px;
}

.chat-bubble.assistant {
    align-self: flex-start;
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    color: #111827;
    border-bottom-left-radius: 6px;
}

.chat-bubble .citation {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 4px;
    background: #DBEAFE;
    color: #2563EB;
    font-size: 0.7rem;
    font-weight: 600;
    margin: 0 2px;
    cursor: pointer;
    vertical-align: super;
}

/* source card */
.source-card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 0.75rem 1rem;
    margin: 0.5rem 0;
    font-size: 0.85rem;
}

.source-card .source-title {
    font-weight: 600;
    color: #1E40AF;
    font-size: 0.9rem;
}

.source-card .source-excerpt {
    color: #6B7280;
    font-size: 0.8rem;
    margin-top: 0.25rem;
    line-height: 1.45;
}

/* ═══════════════════════════════════════════
   Agent 推理步骤
   ═══════════════════════════════════════════ */

.thinking-indicator {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    color: #6B7280;
    font-size: 0.88rem;
}

.thinking-indicator .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #2563EB;
    animation: pulse 1.4s infinite ease-in-out;
}

.thinking-indicator .dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-indicator .dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes pulse {
    0%, 80%, 100% { opacity: 0.4; transform: scale(0.8); }
    40% { opacity: 1; transform: scale(1); }
}

@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}

.step-card {
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 0.75rem 1rem;
    margin: 0.5rem 0;
    font-size: 0.85rem;
    animation: fadeInUp 0.3s ease;
}

.step-card .step-header {
    font-weight: 600;
    color: #2563EB;
    margin-bottom: 0.25rem;
}

.step-card .step-body {
    color: #4B5563;
    font-size: 0.82rem;
    line-height: 1.5;
}

/* ═══════════════════════════════════════════
   按钮
   ═══════════════════════════════════════════ */

.stButton > button {
    border-radius: 10px;
    font-weight: 500;
    font-size: 0.9rem;
    padding: 0.55rem 1.5rem;
    transition: all 0.15s ease;
    border: none;
}

.stButton > button[kind="primary"] {
    background: #2563EB;
    color: white;
}

.stButton > button[kind="primary"]:hover {
    background: #1D4ED8;
    box-shadow: 0 4px 12px rgba(37,99,235,0.3);
}

.stButton > button[kind="secondary"] {
    background: #FFFFFF;
    color: #374151;
    border: 1px solid #D1D5DB;
}

.stButton > button[kind="secondary"]:hover {
    background: #F9FAFB;
    border-color: #9CA3AF;
}

/* ═══════════════════════════════════════════
   Metric / Stats
   ═══════════════════════════════════════════ */

[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 0.75rem 1rem;
}

[data-testid="stMetric"] label {
    font-size: 0.8rem;
    color: #6B7280;
    font-weight: 500;
}

[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-size: 1.5rem;
    font-weight: 700;
    color: #111827;
}

/* ═══════════════════════════════════════════
   Expander / Tabs
   ═══════════════════════════════════════════ */

[data-testid="stExpander"] {
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    background: #FFFFFF;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 0.5rem;
    background: transparent;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 0.5rem 1rem;
    font-size: 0.88rem;
    font-weight: 500;
    color: #6B7280;
}

.stTabs [aria-selected="true"] {
    background: #DBEAFE;
    color: #1E40AF;
}

/* ═══════════════════════════════════════════
   进度条和 Spinner
   ═══════════════════════════════════════════ */

[data-testid="stProgress"] > div {
    background: #DBEAFE;
}

[data-testid="stProgress"] > div > div {
    background: linear-gradient(90deg, #2563EB, #7C3AED);
}

/* ═══════════════════════════════════════════
   输入框
   ═══════════════════════════════════════════ */

.stTextInput input, .stTextArea textarea, .stSelectbox select {
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    transition: all 0.15s ease;
}

.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: #2563EB;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.1);
}

/* ═══════════════════════════════════════════
   Divider
   ═══════════════════════════════════════════ */

hr {
    border-color: #F3F4F6;
    margin: 1.25rem 0;
}

/* ═══════════════════════════════════════════
   Toast / Alert
   ═══════════════════════════════════════════ */

[data-testid="stAlert"] {
    border-radius: 10px;
    border: none;
    font-size: 0.9rem;
}

[data-testid="stAlert"][data-kind="success"] { background: #D1FAE5; color: #065F46; }
[data-testid="stAlert"][data-kind="warning"] { background: #FEF3C7; color: #92400E; }
[data-testid="stAlert"][data-kind="error"]   { background: #FEE2E2; color: #991B1B; }
[data-testid="stAlert"][data-kind="info"]    { background: #DBEAFE; color: #1E40AF; }
</style>
"""
