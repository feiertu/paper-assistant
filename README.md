# Paper Assistant

基于 RAG 的学术论文智能助手 — 论文抓取、解析、检索、问答、分析与对比，一站式工作台。

[![CI](https://github.com/feiertu/paper-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/feiertu/paper-assistant/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11|3.12-blue)
![Vue](https://img.shields.io/badge/Vue-3.5-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 架构概览

```
┌──────────────┐     ┌──────────────┐
│  Vue 3 前端   │────▶│  FastAPI      │
│  (:5173)      │     │  API (:8000)  │
└──────────────┘     └──────┬───────┘
                             │
    ┌────────────────────────┼────────────────────────┐
    │                        │                        │
    ▼                        ▼                        ▼
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ arXiv API│   │ ChromaDB │   │  SQLite  │   │ LLM API  │
│(元数据+PDF)│   │ (向量存储) │   │(元数据/历史)│   │(OpenAI兼容)│
└──────────┘   └──────────┘   └──────────┘   └──────────┘
```

## 快速开始

### 环境要求
- Python 3.11+
- Node.js 20+（前端构建）

### 1. 后端

```bash
# 安装依赖
pip install -r requirements.lock

# 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入 OPENAI_API_KEY

# 抓取论文
python src/fetch/arxiv.py
python src/fetch/download_pdf.py

# 解析 PDF（三选一）
python src/parse/pdf.py              # PyMuPDF 快速解析
python src/parse/docling_parser.py    # Docling Markdown 解析（推荐）
# python src/parse/grob.py            # GROBID 精确解析（需 Docker 运行 grobid）

# 启动 API 服务
uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

### 2. 前端

```bash
cd frontend

# 安装依赖
npm install

# 开发模式（:5173，自动代理 /api → :8000）
npm run dev

# 生产构建
npm run build
# 产物在 frontend/dist/，由 FastAPI 静态服务
```

### 3. 访问
- 前端开发：`http://localhost:5173`
- API 文档：`http://localhost:8000/api/docs`（Swagger）/ `http://localhost:8000/api/redoc`（ReDoc）
- 健康检查：`http://localhost:8000/health`

## 功能矩阵

### 论文获取
| 功能 | 说明 |
|------|------|
| arXiv 批量抓取 | 关键词/分类搜索，自动去重入库 |
| PDF 断点续传 | HTTP Range 续传 + 多层重试 + 下载延迟控制 |
| 一键管线 | 搜索 → 下载 → 解析 → 入库，全自动流转 |

### PDF 解析（三后端可选）
| 后端 | 特点 | 适用场景 |
|------|------|----------|
| **Docling** (IBM) | Markdown 精准转换、表格/公式保留、阅读顺序正确 | 🌟 推荐 |
| **PyMuPDF** | 字号启发式、无需额外依赖 | 快速预览 |
| **GROBID** | ML 精确结构化（章节/表格/图片）、需 Docker | 学术出版级 |

### RAG 检索管线（混合检索 v3）
```
稠密检索 (OpenAI/Voyage/Local)  ──┐
                                    ├── RRF 融合 ──▶ Cross-Encoder 精排 ──▶ Top-K
BM25 稀疏检索 (关键词精确匹配)  ────┘
```
- **双路 Embedding**：支持 OpenAI + Voyage 双 provider，RRF 融合提升召回
- **BM25 稀疏检索**：纯 Python 实现，CJK 二元分词，关键词精确匹配
- **Cross-Encoder 精排**：BAAI/bge-reranker-v2-m3，对候选结果二次打分
- **HNSW 索引优化**：可配置 M / ef_construction / ef_search 参数

### 智能问答
| 模式 | 说明 |
|------|------|
| **标准 RAG** | 检索相关段落 → LLM 上下文回答（SSE 流式输出 + 来源引用） |
| **全局分析** | 聚合全部论文元数据 → LLM 广度分析（不依赖检索命中） |
| **Agent 多步推理** | ReAct 循环 + 7 个工具（搜索/获取/摘要/引用/对比/推荐/综述），流式展示推理步骤 |

### Agent 工具集（7 个）
| 工具 | 能力 |
|------|------|
| `search` | 三维搜索：FTS 全文 / 语义向量 / 列表浏览 |
| `get_paper` | 按 arXiv ID 获取论文完整元数据 |
| `summarize_paper` | 单篇论文结构化摘要（问题/方法/发现） |
| `get_citations` | 引用关系图查询（出引用 + 入引用） |
| `compare_papers` | 两篇论文对比分析（问题/方法/结果/意义） |
| `recommend_similar` | 向量相似度推荐 |
| `generate_survey` | 多论文综述生成，支持 JSON/CSV/BibTeX 导出 |

### 论文管理
- 论文库浏览（分页、关键词/作者/年份/状态筛选）
- 引用关系图（SVG 可视化 + 在库标记）
- 收藏夹管理
- 数据导出（JSON / CSV / BibTeX）

### 系统特性
- **多用户隔离**：Owner-based 数据隔离，Cookie 会话持久化
- **双层缓存**：LLM 响应缓存（30min TTL）+ Embedding 缓存（24h TTL），支持命中率统计和费用估算
- **API 鉴权**：可选的 API Key 鉴权 + 滑动窗口限流
- **健康检查**：浅层 `/health` + 深度 `/health/deep`（DB/Chroma/LLM 全链路）
- **日志系统**：10MB 自动轮转 + 第三方库噪音抑制

## 配置项

完整配置见 `.env.example`，按模块分组：

### LLM
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | OpenAI 兼容 API 密钥 | **必填** |
| `OPENAI_BASE_URL` | 兼容 API 地址 | `https://api.openai.com/v1` |
| `LLM_MODEL` | 默认模型 | `qwen-2.5-72b-instruct` |
| `LLM_TEMPERATURE` | 生成温度 | `0.2` |
| `LLM_MAX_TOKENS` | 最大输出 token | `1024` |
| `LLM_QA_MODEL` | RAG 问答专用模型 | 回退 `LLM_MODEL` |
| `LLM_SUMMARY_MODEL` | 摘要专用模型 | 回退 `LLM_MODEL` |
| `LLM_SURVEY_MODEL` | 综述专用模型 | 回退 `LLM_MODEL` |

### Embedding
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `EMBEDDING_PROVIDER` | 后端：`openai` / `voyage` / `local` / `openai,voyage` | `openai,voyage` |
| `EMBEDDING_MODEL` | 模型名 | `text-embedding-3-large` |
| `EMBEDDING_DIM` | 向量维度 | `1024` |
| `EMBEDDING_BATCH_SIZE` | 批处理大小 | `32` |
| `VOYAGE_API_KEY` | Voyage AI 密钥 | - |
| `EMBEDDING_API_KEY` | 独立 Embedding API 密钥 | 回退 `OPENAI_API_KEY` |
| `EMBEDDING_BASE_URL` | 独立 Embedding API 地址 | 回退 `OPENAI_BASE_URL` |

### 混合检索 v3
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `HYBRID_RETRIEVAL` | 启用混合检索 | `true` |
| `BM25_ENABLED` | 启用 BM25 稀疏检索 | `true` |
| `RERANKER_ENABLED` | 启用 Cross-Encoder 精排 | `true` |
| `BM25_WEIGHT` | BM25 在 RRF 中的权重 (0-1) | `0.3` |
| `RRF_TOP_N` | 每路检索取 Top-N | `20` |
| `RRF_K` | RRF 平滑常数 | `60` |
| `RAG_TOP_K` | 最终返回结果数 | `5` |

### HNSW 索引
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `HNSW_M` | 连接数（更多=更快搜索+更多内存） | `32` |
| `HNSW_EF_CONSTRUCTION` | 构建时搜索深度 | `200` |
| `HNSW_EF_SEARCH` | 查询时搜索深度 | `100` |

### Agent
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_AGENT_MODEL` | Agent 专用模型（需支持 function calling） | 回退 `LLM_MODEL` |
| `AGENT_MAX_ITERATIONS` | 最大推理步数 | `10` |
| `AGENT_TEMPERATURE` | 温度（建议 0.1 确保工具调用稳定） | `0.1` |
| `AGENT_MAX_CONTEXT_TOKENS` | 上下文窗口上限 | `8000` |
| `AGENT_TOOL_RETRY` | 工具失败重试次数 | `2` |

### 缓存
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CACHE_ENABLED` | 启用缓存 | `true` |
| `CACHE_LLM_TTL` | LLM 缓存 TTL（秒） | `1800` (30min) |
| `CACHE_EMBED_TTL` | Embedding 缓存 TTL（秒） | `86400` (24h) |
| `CACHE_LLM_MAXSIZE` | LLM 缓存容量 | `200` |
| `CACHE_EMBED_MAXSIZE` | Embedding 缓存容量 | `2000` |

### 安全
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `API_AUTH_ENABLED` | 启用 API 鉴权（本地使用可关闭） | `false` |
| `API_AUTH_KEY` | API 密钥 | - |
| `API_RATE_LIMIT` | 全局限流 | `30/minute` |
| `API_HOST` / `API_PORT` | 绑定地址 / 端口 | `127.0.0.1` / `8000` |

### 其他
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PDF_PARSER` | 解析后端：`pymupdf` / `docling` / `grobid` | `pymupdf` |
| `ARXIV_QUERY` | arXiv 搜索语句 | `cat:cs.AI AND ti:learning` |
| `ARXIV_MAX_RESULTS` | 每次抓取最大结果数 | `5` |
| `PDF_DOWNLOAD_DELAY` | 下载间隔（秒） | `3.0` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 分块大小 / 重叠 | `1000` / `200` |
| `PAPER_ASSISTANT_LOG_LEVEL` | 日志级别 | `INFO` |

## 数据管线

```
arXiv API                 PDF 下载                解析
   │                        │                     │
   ▼                        ▼                     ▼
[元数据 JSON]  ──▶  [PDF 文件]  ──▶  [结构化 JSON]  ──▶  分块
   │                        │         │                    │
   │                        │         │                    ▼
   └────────────────────────┴─────────┴──────────▶  SQLite ◀──┐
                                                    │         │
                                           ┌───────┘         │
                                           ▼                 │
                                      Embedding              │
                                           │                 │
                                           ▼                 │
                                      ChromaDB              │
                                           │                 │
                                           ▼                 │
                              稠密向量 ──┬── BM25 ──┐        │
                                        │          │        │
                                        ▼          ▼        │
                                      RRF 融合               │
                                        │                    │
                                        ▼                    │
                                 Cross-Encoder 精排          │
                                        │                    │
                                        ▼                    │
                                   LLM 生成回答 ─────────────┘
                                        │              (记录问答历史)
                                        ▼
                                   用户界面
```

## 项目结构

```
paper-assistant/
├── config.py                  # 全局配置中心
├── src/
│   ├── fetch/                 # arXiv 抓取 + PDF 断点续传下载
│   │   ├── arxiv.py
│   │   └── download_pdf.py
│   ├── parse/                 # PDF 解析（pymupdf / docling / grobid）
│   │   ├── schemas.py         #   统一数据结构 ParsedPaper
│   │   ├── pdf.py             #   PyMuPDF 快速解析
│   │   ├── docling_parser.py  #   IBM Docling Markdown 解析
│   │   ├── grob.py            #   GROBID ML 解析
│   │   ├── language.py        #   语言检测（CJK 启发式）
│   │   └── citations.py       #   引用关系提取
│   ├── embed/                 # 文本分块 + Embedding + 混合检索
│   │   ├── chunk.py           #   结构感知分块（breadcrumb 注入）
│   │   ├── embedding.py       #   多后端 Embedder + hybrid_retrieve
│   │   ├── bm25.py            #   纯 Python BM25 稀疏检索
│   │   └── reranker.py        #   Cross-Encoder 精排
│   ├── store/                 # ChromaDB 向量库封装
│   ├── llm/                   # LLM 客户端 + Prompt 模板
│   │   ├── client.py          #   OpenAI 兼容客户端（流式 + 缓存）
│   │   └── prompts.py         #   中英文 Prompt 模板库
│   ├── db/                    # SQLite ORM + DAO
│   │   ├── schema.py          #   表结构 + FTS5 全文索引
│   │   └── dao.py             #   数据访问层（Paper/Query/Collection/Citation）
│   ├── rag/                   # RAG 编排层
│   │   └── orchestrator.py    #   入库/检索/问答/摘要/综述/推荐/全局分析
│   ├── agent/                 # Agent 系统
│   │   ├── base.py            #   抽象基类
│   │   ├── openai_agent.py    #   OpenAI Functions Agent（ReAct 循环）
│   │   ├── tools.py           #   7 个 Agent 工具
│   │   ├── guardrails.py      #   护栏（重复调用/环路检测/迭代上限）
│   │   ├── retry.py           #   工具重试（错误分类 + 指数退避）
│   │   ├── memory.py          #   对话记忆（上下文窗口管理）
│   │   ├── observability.py   #   追踪记录
│   │   ├── compare.py         #   论文对比
│   │   └── schemas.py         #   Pydantic 请求/响应模型
│   ├── api/                   # FastAPI REST 服务
│   │   ├── main.py            #   50+ 端点（认证/健康/RAG/Agent/管线/导出等）
│   │   └── middleware.py      #   鉴权/限流/多用户隔离中间件
│   ├── cache.py               # TTL+LRU 缓存层（LLM + Embedding 双层）
│   └── logging_config.py      # 结构化日志（轮转文件 + 控制台）
├── frontend/                  # Vue 3 + TypeScript 前端
│   ├── src/
│   │   ├── api/               #   HTTP 客户端 + 类型定义
│   │   ├── components/
│   │   │   ├── layout/        #   布局（AppShell / Header / Sidebar / AuthDialog）
│   │   │   ├── common/        #   通用组件（PaperCard/ChatBubble/Pagination等 12 个）
│   │   │   └── pages/         #   8 个页面（QA/Agent/Library/Summary/Citations/Data/System/Help）
│   │   ├── composables/       #   组合式函数（useStreaming / useTheme）
│   │   ├── stores/            #   Pinia 状态管理（auth / ui / toast）
│   │   ├── router/            #   Vue Router 路由
│   │   └── utils/             #   格式化工具
│   └── vite.config.ts         #   Vite 配置（:5173 → :8000 代理）
├── ui/                        # Streamlit 备选 UI（遗留）
├── tests/                     # 测试（pytest + 9 个测试文件）
├── migrations/                # Alembic 数据库迁移
├── scripts/                   # 运维脚本（冒烟测试/部署/修复）
├── docker-compose.yml         # [可选] Docker 部署
├── Dockerfile                 # [可选] Docker 镜像
├── nginx/                     # [可选] 线上反代 + SSL
├── requirements.txt           # Python 依赖
└── .github/workflows/ci.yml   # CI（pytest + mypy + ruff + docker build）
```

## API 端点速览

| 类别 | 端点 | 方法 |
|------|------|------|
| 认证 | `/api/auth/login`, `/api/auth/register` | POST |
| 健康 | `/api/health`, `/api/health/deep` | GET |
| 检索 | `/api/rag/retrieve` | POST |
| 问答 | `/api/rag/query`, `/api/rag/query/stream` (SSE) | POST |
| Agent | `/api/agent/query`, `/api/agent/query/stream` (SSE) | POST |
| 摘要 | `/api/summary/summarize`, `/api/summary/survey` | POST |
| 推荐 | `/api/papers/{arxiv_id}/recommend` | GET |
| 分析 | `/api/papers/analyze` | POST |
| 论文 | `/api/papers` (列表/搜索/CRUD) | GET/POST/DELETE |
| 引用 | `/api/citations/{arxiv_id}`, `/api/citations/extract` | GET/POST |
| 管线 | `/api/arxiv/pipeline`, `/api/arxiv/process-pending` | POST |
| 导出 | `/api/export/papers`, `/api/export/queries` | GET |
| 向量库 | `/api/store/stats`, `/api/store/backup`, `/api/store/restore` | GET/POST |
| 缓存 | `/api/cache/stats`, `/api/cache/clear` | GET/POST |
| 配置 | `/api/config` | GET |
| 收藏夹 | `/api/collections` (CRUD) | GET/POST/DELETE |

完整 API 文档：启动服务后访问 `http://localhost:8000/api/docs`

## 测试

```bash
# 全部测试 + 覆盖率
pytest tests/ -v --cov=src

# 仅单元测试
pytest tests/ -v -m unit

# LLM 模块冒烟测试（离线，不调 API）
python scripts/smoke_test_llm.py

# RAG 端到端冒烟测试（需 API Key）
python scripts/smoke_test_rag.py
```

## 技术栈

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI + Uvicorn |
| 前端框架 | Vue 3 + TypeScript + Vite + Tailwind CSS v4 |
| 状态管理 | Pinia |
| 向量数据库 | ChromaDB (PersistentClient + HNSW) |
| 关系数据库 | SQLite (FTS5 全文搜索) |
| LLM | OpenAI 兼容 API（支持 Qwen / DeepSeek / MiniMax 等） |
| Embedding | OpenAI / Voyage AI / sentence-transformers (Local) |
| PDF 解析 | PyMuPDF / IBM Docling / GROBID |
| 精排模型 | BAAI/bge-reranker-v2-m3 (sentence-transformers) |
| 数据库迁移 | Alembic |
| 测试 | pytest + pytest-cov + mypy + ruff |
| CI/CD | GitHub Actions |


