"""Paper Assistant UI 主题样式 — Vercel 风格，最小侵入 Streamlit 布局。"""

TOKENS = {
    "canvas": "#ffffff",
    "canvas_soft": "#fafafa",
    "canvas_soft_2": "#f5f5f5",
    "ink": "#171717",
    "body": "#4d4d4d",
    "mute": "#888888",
    "hairline": "#ebebeb",
    "hairline_strong": "#d4d4d4",
    "surface_card": "#ffffff",
    "surface_raised": "#fafafa",
    "primary": "#2563EB",
    "primary_hover": "#1d4ed8",
    "primary_light": "#dbeafe",
    "primary_text": "#1e40af",
    "link": "#2563EB",
    "success": "#059669",
    "success_soft": "#d1fae5",
    "warning": "#d97706",
    "warning_soft": "#fef3c7",
    "error": "#dc2626",
    "error_soft": "#fee2e2",
    "sidebar_bg": "#fafafa",
    "sidebar_hover": "#f0f0f0",
    "sidebar_active": "#e8e8e8",
    "overlay": "rgba(0,0,0,0.4)",
}


def _css_vars(tokens: dict) -> str:
    return "\n".join(f"    --{k.replace('_', '-')}: {v};" for k, v in tokens.items())


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ── 浏览器默认值归零 ── */
html, body {{
    margin: 0 !important;
    padding: 0 !important;
}}

:root {{
{_css_vars(TOKENS)}
    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
    --radius-sm: 6px;
    --radius-md: 8px;
    --radius-lg: 12px;
    --radius-xl: 16px;
    --radius-pill: 9999px;
    --transition-fast: 0.15s ease;
}}

/* ── 全局字体 & 背景（不碰 layout）── */

.stApp {{
    background: var(--canvas);
}}

* {{
    font-family: var(--font-sans);
}}

/* ── 隐藏 Streamlit 工具栏（不影响 layout）── */

[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDeployButton"],
#MainMenu,
footer {{
    display: none !important;
}}

/* ── 消除 Streamlit 1.58 默认留白 ── */

/* stMainBlockContainer 的 emotion 样式设了 padding-top: 6rem */
[data-testid="stMainBlockContainer"] {{
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}}

/* Sidebar 保留正常间距 */
[data-testid="stSidebar"] .block-container {{
    padding-top: 1rem !important;
}}

/* ── Header Bar ── */

[data-st-key="header"] {{
    border-bottom: 1px solid var(--hairline);
    padding: 12px 24px;
    background: var(--canvas);
}}

.header-title {{
    font-size: 16px;
    font-weight: 700;
    color: var(--ink);
    letter-spacing: -0.5px;
    margin-right: 12px;
}}

.header-subtitle {{
    font-size: 12px;
    color: var(--mute);
}}

.header-avatar {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-pill);
    background: var(--primary-light);
    color: var(--primary-text);
    font-size: 12px;
    font-weight: 600;
    margin-right: 6px;
    vertical-align: middle;
}}

.header-username {{
    font-size: 13px;
    color: var(--body);
    font-weight: 500;
    vertical-align: middle;
}}

/* ── Sidebar 用户区域 ── */

.sidebar-user {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 0;
    margin-bottom: 6px;
}}

.sidebar-avatar {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: var(--radius-pill);
    background: var(--primary-light);
    color: var(--primary-text);
    font-size: 14px;
    font-weight: 600;
    flex-shrink: 0;
}}

.sidebar-username {{
    font-size: 13px;
    font-weight: 500;
    color: var(--ink);
    line-height: 1.3;
}}

/* ── 页面标题 & 描述区分 ── */

.page-title {{
    font-size: 22px;
    font-weight: 700;
    color: var(--ink);
    margin-bottom: 6px;
    letter-spacing: -0.5px;
}}

.page-description {{
    font-size: 14px;
    color: var(--mute);
    line-height: 1.5;
    margin-bottom: 20px;
}}

/* ── Sidebar — 纯样式 ── */

[data-testid="stSidebar"] {{
    background: var(--sidebar-bg);
    border-right: 1px solid var(--hairline);
}}

[data-testid="stSidebar"] .block-container {{
    padding: 16px 12px !important;
}}

[data-testid="stSidebar"] [data-testid="stMarkdown"] h2 {{
    font-size: 18px !important;
    font-weight: 700 !important;
    color: var(--ink) !important;
    margin-bottom: 4px !important;
    letter-spacing: -0.5px !important;
}}

[data-testid="stSidebar"] [data-testid="stCaption"] {{
    font-size: 12px !important;
    color: var(--mute) !important;
}}

[data-testid="stSidebar"] .stRadio > div {{
    gap: 2px;
}}

[data-testid="stSidebar"] .stRadio [role="radiogroup"] {{
    gap: 2px;
    display: flex;
    flex-direction: column;
}}

[data-testid="stSidebar"] .stRadio label {{
    padding: 8px 12px !important;
    border-radius: var(--radius-md) !important;
    font-size: 13.5px !important;
    color: var(--body) !important;
    font-weight: 500 !important;
    cursor: pointer !important;
    transition: background var(--transition-fast);
}}

[data-testid="stSidebar"] .stRadio label:hover {{
    background: var(--sidebar-hover) !important;
    color: var(--ink) !important;
}}

[data-testid="stSidebar"] .stRadio label[data-selected="true"] {{
    background: var(--sidebar-active) !important;
    color: var(--ink) !important;
    font-weight: 600 !important;
}}

[data-testid="stSidebar"] hr {{
    margin: 12px 0 !important;
    border-color: var(--hairline) !important;
}}

/* ── Buttons ── */

.stButton > button {{
    border-radius: var(--radius-md) !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    padding: 8px 16px !important;
    min-height: 36px !important;
    line-height: 1 !important;
    transition: all var(--transition-fast) !important;
    border: none !important;
}}

.stButton > button[kind="primary"] {{
    background: var(--primary) !important;
    color: #ffffff !important;
}}

.stButton > button[kind="primary"]:hover {{
    background: var(--primary-hover) !important;
}}

.stButton > button[kind="secondary"] {{
    background: var(--canvas) !important;
    color: var(--ink) !important;
    border: 1px solid var(--hairline-strong) !important;
}}

.stButton > button[kind="secondary"]:hover {{
    background: var(--canvas-soft) !important;
}}

/* ── Inputs ── */

.stTextInput input, .stTextArea textarea {{
    border: 1px solid var(--hairline-strong) !important;
    border-radius: var(--radius-md) !important;
    background: var(--canvas) !important;
    color: var(--ink) !important;
    font-size: 14px !important;
}}

.stTextInput input:focus, .stTextArea textarea:focus {{
    border-color: var(--primary) !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.1) !important;
    outline: none !important;
}}

/* ── st.dialog 原生弹窗样式（Vercel 风格）── */
/*    st.dialog 渲染在主内容容器外部，不受页面 CSS 层叠上下文影响 */

/* 遮罩层 — 毛玻璃效果 */
[data-testid="stDialog"] > div:first-child {{
    background: rgba(0,0,0,0.35) !important;
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
}}

/* 隐藏 Streamlit 自带的右上角 X 关闭按钮 */
[data-testid="stDialog"] button[aria-label="Close"] {{
    display: none !important;
    visibility: hidden !important;
    width: 0 !important;
    height: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    opacity: 0 !important;
    pointer-events: none !important;
}}

/* 弹窗面板 */
[data-testid="stDialog"] [data-testid="stDialog"] > div:first-child > div:first-child {{
    border-radius: var(--radius-xl) !important;
    border: 1px solid var(--hairline) !important;
    box-shadow: 0 20px 60px rgba(0,0,0,0.2) !important;
    background: var(--canvas) !important;
    padding: 28px 28px 20px 28px !important;
}}

/* 弹窗内标题 — 居中 */
[data-testid="stDialog"] h2 {{
    font-size: 20px !important;
    font-weight: 700 !important;
    color: var(--ink) !important;
    margin: 0 0 8px 0 !important;
    padding: 0 !important;
    text-align: center !important;
}}

[data-testid="stDialog"] h3 {{
    font-size: 20px !important;
    font-weight: 700 !important;
    color: var(--ink) !important;
    margin: 0 0 4px 0 !important;
    padding: 0 !important;
    text-align: center !important;
}}

/* 弹窗内副标题 — 居中 */
[data-testid="stDialog"] [data-testid="stCaptionContainer"] {{
    text-align: center !important;
}}

/* ── Paper Card ── */

.paper-card {{
    background: var(--surface-card);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-lg);
    padding: 20px 24px;
    margin-bottom: 8px;
    transition: border-color var(--transition-fast);
}}

.paper-card:hover {{
    border-color: var(--hairline-strong);
}}

.paper-card .title {{
    font-size: 16px;
    font-weight: 600;
    color: var(--ink);
    margin-bottom: 4px;
    line-height: 1.4;
}}

.paper-card .authors {{
    font-size: 13px;
    color: var(--body);
    margin-bottom: 6px;
}}

.paper-card .meta {{
    display: flex;
    gap: 12px;
    font-size: 12px;
    color: var(--mute);
    margin-bottom: 6px;
    flex-wrap: wrap;
}}

.paper-card .abstract {{
    font-size: 13.5px;
    color: var(--body);
    line-height: 1.55;
}}

/* ── Badges ── */

.badge {{
    display: inline-flex;
    align-items: center;
    padding: 2px 10px;
    border-radius: var(--radius-pill);
    font-size: 11.5px;
    font-weight: 500;
}}

.badge-success {{ background: var(--success-soft); color: var(--success); }}
.badge-warning {{ background: var(--warning-soft); color: var(--warning); }}
.badge-info    {{ background: var(--primary-light); color: var(--primary-text); }}
.badge-muted   {{ background: var(--canvas-soft-2); color: var(--mute); }}

/* ── Chat ── */

.chat-bubble {{
    padding: 16px 20px;
    border-radius: var(--radius-lg);
    line-height: 1.6;
    font-size: 14.5px;
}}

.chat-bubble.assistant {{
    background: var(--canvas-soft);
    color: var(--ink);
    border: 1px solid var(--hairline);
}}

.source-card {{
    background: var(--surface-card);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-md);
    padding: 12px 16px;
    margin: 6px 0;
    font-size: 13px;
}}

.source-card .source-title {{
    font-weight: 600;
    color: var(--primary-text);
    font-size: 13.5px;
}}

.source-card .source-excerpt {{
    color: var(--body);
    font-size: 12.5px;
    margin-top: 4px;
    line-height: 1.5;
}}

/* ── Hero Search ── */

.hero-search {{
    text-align: center;
    padding: 20px 16px 24px;
}}

.hero-search h1 {{
    font-size: 28px;
    font-weight: 700;
    color: var(--ink);
    margin-bottom: 8px;
    letter-spacing: -0.8px;
}}

.hero-search p {{
    font-size: 15px;
    color: var(--body);
    margin-bottom: 24px;
}}

/* ── Agent steps ── */

.step-card {{
    background: var(--canvas-soft);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-md);
    padding: 12px 16px;
    margin: 6px 0;
    font-size: 13.5px;
}}

.step-card .step-header {{
    font-weight: 600;
    color: var(--primary-text);
    margin-bottom: 4px;
}}

/* ── Misc components (不碰 layout) ── */

[data-testid="stMetric"] {{
    background: var(--surface-card);
    border: 1px solid var(--hairline);
    border-radius: var(--radius-md);
    padding: 12px 16px;
}}

[data-testid="stExpander"] {{
    border: 1px solid var(--hairline) !important;
    border-radius: var(--radius-md) !important;
    background: var(--surface-card) !important;
}}

[data-testid="stProgress"] > div {{
    background: var(--canvas-soft-2);
    border-radius: var(--radius-pill);
}}

[data-testid="stProgress"] > div > div {{
    background: var(--primary);
    border-radius: var(--radius-pill);
}}

[data-testid="stAlert"] {{
    border-radius: var(--radius-md) !important;
    border: none !important;
    font-size: 14px !important;
}}

hr {{
    border-color: var(--hairline) !important;
    margin: 20px 0 !important;
}}

/* ── Responsive ── */

@media (max-width: 768px) {{
    .header-subtitle {{ display: none; }}
    .header-title {{ font-size: 14px; }}
.hero-search h1 {{ font-size: 22px; }}
    [data-st-key="modal_card"] {{
        width: 90vw;
        padding: 24px !important;
    }}
}}
</style>
"""
