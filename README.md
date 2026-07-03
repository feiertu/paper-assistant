# Paper Assistant

基于 RAG 的学术论文问答系统。

## 功能

- **论文抓取**: arXiv API 元数据获取 + PDF 断点续传下载
- **PDF 解析**: PyMuPDF 快速解析 + GROBID ML 精确结构化
- **RAG 管线**: 文本分块 → Embedding (OpenAI/Voyage) → Chroma 向量存储 → LLM 问答
- **论文管理**: 论文列表/搜索/推荐/引用关系图/收藏夹
- **数据导出**: CSV / JSON / BibTeX
- **Web 服务**: FastAPI REST API + Streamlit 交互式 UI
- **Docker 部署**: 一键容器化，含 Nginx HTTPS 反代

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.lock

# 2. 配置
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 等

# 3. 抓取论文
python src/fetch/arxiv.py
python src/fetch/download_pdf.py

# 4. 解析 PDF
python src/parse/pdf.py           # 快速解析
# 或
python src/parse/grob.py          # GROBID 精确解析（需 Docker 运行 grobid）

# 5. 启动服务
python src/api/main.py            # FastAPI :8000
streamlit run ui/app.py           # Streamlit UI :8501
```

## Docker 部署

```bash
docker compose up -d
# API: http://localhost:8000
# UI:  http://localhost:8501
```

## 配置项

完整配置见 `.env.example`，关键项：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | OpenAI API 密钥（必填） | - |
| `OPENAI_BASE_URL` | 兼容 API 地址 | `https://api.openai.com/v1` |
| `LLM_MODEL` | 默认 LLM 模型 | `qwen-2.5-72b-instruct` |
| `LLM_QA_MODEL` | RAG 问答模型 | 回退 LLM_MODEL |
| `LLM_SUMMARY_MODEL` | 摘要模型 | 回退 LLM_MODEL |
| `LLM_SURVEY_MODEL` | 综述模型 | 回退 LLM_MODEL |
| `EMBEDDING_PROVIDER` | openai / voyage / openai,voyage | `openai,voyage` |
| `API_AUTH_ENABLED` | 启用 API 鉴权 | `false` |
| `API_RATE_LIMIT` | 全局限流 | `30/minute` |
| `PAPER_ASSISTANT_GROBID_URL` | GROBID 地址 | `http://localhost:8070` |

## 测试

```bash
pytest tests/ -v --cov=src
```

## 项目结构

```
├── config.py              # 全局配置
├── src/
│   ├── fetch/             # arXiv 抓取 + PDF 下载
│   ├── parse/             # PDF 解析 (pymupdf + GROBID) + 语言检测 + 引用提取
│   ├── embed/             # 文本分块 + Embedding (OpenAI/Voyage)
│   ├── store/             # Chroma 向量库
│   ├── llm/               # LLM 客户端 + Prompt 模板
│   ├── db/                # SQLite ORM + DAO
│   ├── rag/               # RAG 编排层
│   ├── api/               # FastAPI REST
│   ├── cache.py           # 查询缓存
│   ├── logging_config.py  # 日志配置
├── ui/                    # Streamlit UI
├── tests/                 # 测试
├── migrations/            # Alembic 数据库迁移
└── nginx/                 # Nginx 反代配置
```
