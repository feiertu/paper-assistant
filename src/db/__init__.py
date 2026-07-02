"""数据库子包 — 传统关系型数据库（SQLite）。

遵循第 19 章的设计模式：
  - ER 模型：实体 → 表，关系 → 外键/中间表
  - DAO 模式：接口封装数据访问，上层不感知底层实现
  - ORM 映射：dataclass → 表行
"""

from .schema import init_db, get_connection, Paper, QueryRecord, Collection
from .dao import PaperDAO, QueryDAO, CollectionDAO, get_dao

__all__ = [
    "init_db",
    "get_connection",
    "Paper",
    "QueryRecord",
    "Collection",
    "PaperDAO",
    "QueryDAO",
    "CollectionDAO",
    "get_dao",
]
