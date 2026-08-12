#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据迁移脚本：旧 Python 数据目录 → 新 Java (Spring Boot / PostgreSQL) 后端。

旧 Python 后端把数据存在仓库根目录 ``data/``：

  - ``data/paper_assistant.db``        SQLite（papers / queries / query_papers /
                                       collections / collection_papers / citations /
                                       fetch_history）
  - ``data/users.json``                用户表。Java 后端 AuthService 仍然直接读取
                                       这个 JSON 文件（不落 PG），脚本只确认其存在并报告
  - ``data/chroma_db/chroma.sqlite3``  ChromaDB 向量库。尽力读取已有向量写回
                                       papers.embedding；读不到则跳过——重新入库时
                                       EmbedService 会自动重建 embedding

新 Java 后端把结构化数据存入 PostgreSQL（pgvector），本脚本把 SQLite 各表按列名
逐一导入（ON CONFLICT DO NOTHING 防重），迁移后把 PG serial 序列推进到已迁移的
最大 id，避免后续新增主键冲突。

用法（在 paper-assistant-java/scripts/ 下执行）：

    pip install psycopg2-binary
    DATABASE_URL=postgresql://paper:paper@localhost:5432/paper_assistant \
        python migrate_data.py

可选参数：
    --sqlite PATH     SQLite 文件路径（默认 ../data/paper_assistant.db）
    --chroma PATH     ChromaDB chroma.sqlite3 路径（默认 ../data/chroma_db/chroma.sqlite3）
    --data-dir PATH   旧数据目录（默认 ../data，读取 users.json）
    --database-url URL PostgreSQL 连接串（默认读环境变量 DATABASE_URL）
    --dry-run         只打印计划，不写入数据库
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

try:
    import psycopg2
except ImportError:  # pragma: no cover
    print("错误：缺少依赖 psycopg2。请先安装：pip install psycopg2-binary",
          file=sys.stderr)
    sys.exit(1)

DEFAULT_SQLITE = "../data/paper_assistant.db"
DEFAULT_CHROMA = "../data/chroma_db/chroma.sqlite3"
DEFAULT_DATA_DIR = "../data"
DEFAULT_DATABASE_URL = "postgresql://paper:paper@localhost:5432/paper_assistant"

# SQLite → Postgres 直接按列名迁移的表（顺序即依赖顺序：父表先于关联表）。
# 列定义与 V1__initial_schema.sql 完全一致。
TABLES = [
    "papers",
    "queries",
    "query_papers",
    "collections",
    "collection_papers",
    "citations",
    "fetch_history",
]

# 带自增主键的表：迁移后需把 PG serial 序列推进到已迁移的最大 id。
# （query_papers / collection_papers 为复合主键关联表，无独立 id。）
SERIAL_TABLES = ["papers", "queries", "collections", "citations", "fetch_history"]


def migrate_sqlite_tables(sqlite_path: str, pg_url: str, dry_run: bool = False) -> None:
    """把 SQLite 各表整表导入 PostgreSQL。"""
    sqlite_path = Path(sqlite_path)
    if not sqlite_path.is_file():
        print(f"! SQLite 数据库不存在: {sqlite_path}（跳过表迁移）")
        return

    print(f"== 迁移 SQLite -> PostgreSQL: {sqlite_path} ==")
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row
    try:
        pg_conn = psycopg2.connect(pg_url)
    except psycopg2.OperationalError as e:
        print(f"! 无法连接 PostgreSQL: {e}", file=sys.stderr)
        sqlite_conn.close()
        sys.exit(1)

    try:
        for table in TABLES:
            rows = sqlite_conn.execute(f'SELECT * FROM "{table}"').fetchall()
            if not rows:
                print(f"  {table}: 0 行")
                continue
            columns = list(rows[0].keys())
            placeholders = ", ".join(["%s"] * len(columns))
            cols = ", ".join(f'"{c}"' for c in columns)
            sql = (f'INSERT INTO "{table}" ({cols}) VALUES ({placeholders}) '
                   "ON CONFLICT DO NOTHING")
            cur = pg_conn.cursor()
            if dry_run:
                print(f"  {table}: {len(rows)} 行（dry-run，未写入）")
            else:
                cur.executemany(sql, [tuple(r) for r in rows])
                pg_conn.commit()
                print(f"  {table}: {len(rows)} 行迁移完成")
            cur.close()

        if not dry_run:
            advance_sequences(pg_conn)
    finally:
        sqlite_conn.close()
        pg_conn.close()


def advance_sequences(pg_conn) -> None:
    """把 PG serial 序列推进到已迁移数据的最大 id，避免后续插入主键冲突。"""
    cur = pg_conn.cursor()
    try:
        for table in SERIAL_TABLES:
            cur.execute(f'SELECT MAX(id) FROM "{table}"')
            max_id = cur.fetchone()[0]
            if max_id is None:
                continue
            cur.execute(
                "SELECT setval(pg_get_serial_sequence(%s, 'id'), %s)",
                (table, max_id),
            )
            print(f"  序列推进: {table} -> {max_id}")
        pg_conn.commit()
    finally:
        cur.close()


def migrate_users(data_dir: str, dry_run: bool = False) -> int:
    """users.json：Java 后端 AuthService 仍从数据目录读取该 JSON 文件。

    源与目标默认同一目录（../data），故只需确认文件存在并报告用户数。
    """
    src = Path(data_dir) / "users.json"
    if not src.is_file():
        print("! users.json 不存在，跳过（Java 后端首次启动会自动创建 demo 账号）")
        return 0
    try:
        users = json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"! users.json 读取失败: {e}", file=sys.stderr)
        return 0
    names = sorted(users.keys())
    action = "确认" if dry_run else "已确认"
    print(f"== users.json {action}：{len(users)} 个用户 {names}（Java 后端继续从 {src} 读取）")
    return len(users)


def migrate_chroma_embeddings(chroma_path: str, pg_url: str, dry_run: bool = False) -> None:
    """尽力从 ChromaDB chroma.sqlite3 读取已有向量，写回 papers.embedding。

    ChromaDB 默认把向量本体存放在 HNSW 索引二进制文件中，SQLite 里通常只有引用
    （embeddings / embedding_metadata / embeddings_queue 表）。因此这里尽力读取
    能拿到的向量；拿不到就提示跳过，重新入库时 EmbedService 会自动重建。
    """
    chroma_path = Path(chroma_path)
    if not chroma_path.is_file():
        print("! ChromaDB 不存在，跳过 embedding 迁移")
        return

    print(f"== 尝试读取 ChromaDB 向量: {chroma_path} ==")
    conn = sqlite3.connect(str(chroma_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT embedding_id FROM embeddings")
        ids = [r["embedding_id"] for r in cur.fetchall()]
        if not ids:
            print("  ChromaDB 无 embedding 记录（向量已压缩到 HNSW 索引文件），"
                  "跳过；重新入库时自动重建")
            return

        # embeddings_queue（WAL）中的向量为 JSON 编码
        vec_by_id: dict[str, list[float]] = {}
        try:
            qcur = conn.execute("SELECT id, vector FROM embeddings_queue")
            for r in qcur.fetchall():
                if r["vector"]:
                    vec_by_id[r["id"]] = json.loads(r["vector"])
        except sqlite3.Error as e:
            print(f"  ! 读取 embeddings_queue 失败: {e}")

        if not vec_by_id:
            print("  ChromaDB SQLite 中未找到可用向量（HNSW 索引以二进制存储），"
                  "跳过；重新入库时自动重建")
            return

        # embedding_id -> arxiv_id：优先取 embedding_metadata 的 arxiv_id，
        # 否则从 embedding_id 的 "_idx" 前缀推断（旧 orchestrator 生成形如
        # "{arxiv_id}_{idx}" 的 id）
        meta_arxiv: dict[str, str] = {}
        try:
            mcur = conn.execute(
                "SELECT id, string_value FROM embedding_metadata "
                "WHERE key = 'arxiv_id' AND string_value IS NOT NULL")
            for r in mcur.fetchall():
                meta_arxiv[r["id"]] = r["string_value"]
        except sqlite3.Error:
            pass

        # 每篇论文的所有 chunk 向量取平均 -> 一条 vector(1024)
        arxiv_to_vecs: dict[str, list[list[float]]] = {}
        for emb_id, vec in vec_by_id.items():
            arxiv_id = meta_arxiv.get(emb_id) or str(emb_id).split("_")[0]
            arxiv_to_vecs.setdefault(arxiv_id, []).append(vec)

        pg_conn = psycopg2.connect(pg_url)
        cur = pg_conn.cursor()
        try:
            written = 0
            for arxiv_id, vecs in arxiv_to_vecs.items():
                dims = len(vecs[0])
                avg = [sum(v[i] for v in vecs) / len(vecs) for i in range(dims)]
                vec_literal = "[" + ",".join(str(round(float(x), 6)) for x in avg) + "]"
                if dry_run:
                    print(f"  [dry-run] {arxiv_id}: {len(vecs)} 个 chunk 平均 -> {dims} 维")
                    continue
                cur.execute(
                    "UPDATE papers SET embedding = %s::vector WHERE arxiv_id = %s",
                    (vec_literal, arxiv_id),
                )
                if cur.rowcount:
                    written += 1
            pg_conn.commit()
            print(f"  已写回 {written} 篇论文的 embedding")
        finally:
            cur.close()
            pg_conn.close()
    finally:
        conn.close()


def main() -> None:
    # Windows GBK 控制台下强制 UTF-8 输出，避免中文打印抛 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        description="迁移旧 Python 数据目录到新 Java (PostgreSQL) 后端")
    parser.add_argument("--sqlite", default=DEFAULT_SQLITE,
                        help="旧 SQLite 数据库路径")
    parser.add_argument("--chroma", default=DEFAULT_CHROMA,
                        help="旧 ChromaDB chroma.sqlite3 路径")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                        help="旧数据目录（读取 users.json）")
    parser.add_argument("--database-url", default=os.getenv(
        "DATABASE_URL", DEFAULT_DATABASE_URL), help="PostgreSQL 连接串")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印计划，不写入数据库")
    args = parser.parse_args()

    # 连接串可能含密码，打印时隐藏凭据
    host_part = args.database_url.split("@")[-1] if "@" in args.database_url \
        else args.database_url
    print(f"目标数据库: {host_part}")

    migrate_sqlite_tables(args.sqlite, args.database_url, args.dry_run)
    migrate_users(args.data_dir, args.dry_run)
    migrate_chroma_embeddings(args.chroma, args.database_url, args.dry_run)

    if args.dry_run:
        print("\n[dry-run] 未写入任何数据。")
    else:
        print("\n迁移完成。若未迁移 embedding，重新入库 papers 会自动重建。"
              "启动后端：cd paper-assistant-java && docker compose up -d --build")


if __name__ == "__main__":
    main()
