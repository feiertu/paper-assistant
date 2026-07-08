"""最小 RAG 烟测脚本。

流程：
  1) 用 src.embed.chunk 解析已有的 data/parsed/*.json
  2) Embedder 向量化（OpenAI / Voyage / 双路）
  3) VectorStore 写入 Chroma
  4) 单路或 RRF 双路检索

依赖 OPENAI_API_KEY（和可选的 VOYAGE_API_KEY）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from src.embed import get_embedder, split_doc, rrf_rerank  # noqa: E402
from src.embed.chunk import iter_doc_files, find_parsed_dir  # noqa: E402
from src.store import VectorStore  # noqa: E402


def main() -> None:
    parsed_dir = find_parsed_dir()
    print(f"[1] parsed dir = {parsed_dir}")

    docs = list(iter_doc_files(parsed_dir))
    if not docs:
        print(f"[ERROR] 在 {parsed_dir} 没找到任何 JSON。先跑 pdf.py 或 grob.py 的 batch。")
        return
    print(f"[2] found {len(docs)} parsed docs")

    all_chunks = []
    for fp, doc in docs:
        chunks = split_doc(doc)
        print(f"   - {fp.name}: {len(chunks)} chunks")
        all_chunks.extend(chunks)
    print(f"[3] total chunks = {len(all_chunks)}")

    if not all_chunks:
        print("[ERROR] 分块结果为空。")
        return

    embedder = get_embedder()
    print(f"[4] embedding providers = {embedder.providers}")
    print(f"    model = {config.EMBEDDING_MODEL}, dim = {embedder.dim}")

    store = VectorStore()
    store.reset()

    # 对每个 provider 分别入库（不强制，合并也行，这里用第一个 provider）
    if embedder.is_dual:
        # 双路：每个 provider 独立写一份 embedding（实际场景可共用 collection）
        print("[5] dual-provider: embedding with primary provider for storage...")
        primary = embedder.providers[0]
        texts = [c["text"] for c in all_chunks]
        embs = embedder.embed(texts)
    else:
        primary = embedder.providers[0]
        texts = [c["text"] for c in all_chunks]
        embs = embedder.embed(texts)

    print(f"    embeddings shape = {embs.shape}")
    print(f"    before add: count = {store.count()}")

    ids = [f"smoke_{i}" for i in range(len(all_chunks))]
    metas = [
        {
            "title": c.get("title") or "",
            "section_title": c.get("section_title") or "",
            "page": int(c.get("page") or 0),
            "source": c.get("source") or "",
        }
        for c in all_chunks
    ]
    store.add(ids=ids, documents=texts, embeddings=embs, metadatas=metas)
    print(f"    after add : count = {store.count()}")

    # 检索测试
    query = "What is the main contribution of this paper?"
    print(f"\n[Q] {query}")

    if embedder.is_dual:
        print("    using RRF dual-provider rerank...")
        hits = rrf_rerank(query, top_k=3)
    else:
        q_emb = embedder.embed_query(query)
        hits = store.query(q_emb, top_k=3)["hits"]

    for i, hit in enumerate(hits, 1):
        doc = hit["document"].replace("\n", " ")[:120]
        score = hit.get("rrf_score") or hit.get("distance", "")
        label = f"rrf={score:.4f}" if hit.get("rrf_score") else f"dist={score:.4f}"
        print(f"  {i}. ({label}) [{hit['metadata'].get('section_title','')}] {doc}…")

    print("\nsmoke test done.")


if __name__ == "__main__":
    main()
