# Paper Assistant

基于 RAG 的学术论文问答系统。

## 进度
- [x] Day 1: arXiv API 元数据抓取
- [x] Day 2: PDF 批量下载（带限速保护）
- [ ] Day 3-7: RAG 检索 + 单文档摘要
- [ ] Day 8-10: 综述生成
- [ ] Day 11-14: 工程化 + 评测 + 投递

## 运行
pip install -r requirements.txt
python src/fetch/arxiv.py
python src/fetch/download_pdf.py