"""
映记 — 记忆持久化层
SQLite（元数据/关系）+ ChromaDB（向量检索）双引擎
"""

import json
import sqlite3
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import (
    SQLITE_PATH, CHROMA_PERSIST_DIR, COLLECTION_NAME,
    OLLAMA_BASE_URL, EMBED_MODEL,
    IMPORTANCE_THRESHOLD_LOW, IMPORTANCE_THRESHOLD_MED, IMPORTANCE_THRESHOLD_HIGH,
    FORGET_HOT_DAYS, FORGET_WARM_DAYS, FORGET_COLD_DAYS,
    MEMORY_TYPES,
)

import requests

# ══════════════════════════════════════════════════════════════════
# 嵌入工具
# ══════════════════════════════════════════════════════════════════

def _embed(text: str) -> list[float]:
    """调用 Ollama 获取文本嵌入向量"""
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


# ══════════════════════════════════════════════════════════════════
# SQLite 层
# ══════════════════════════════════════════════════════════════════

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def init_db():
    """初始化数据库表"""
    conn = _get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            client TEXT NOT NULL DEFAULT 'unknown',
            title TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            turn_count INTEGER DEFAULT 0,
            token_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            token_estimate INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            message_id TEXT,
            memory_type TEXT NOT NULL DEFAULT 'fact',
            content TEXT NOT NULL,
            importance REAL DEFAULT 0.3,
            access_count INTEGER DEFAULT 0,
            first_accessed_at TEXT,
            last_accessed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS memory_tiers (
            memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
            tier TEXT NOT NULL DEFAULT 'hot',
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
        CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);
        CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
        CREATE INDEX IF NOT EXISTS idx_memories_accessed ON memories(last_accessed_at);
        CREATE INDEX IF NOT EXISTS idx_memory_tiers_tier ON memory_tiers(tier);
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
    """)

    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════════
# Conversation CRUD
# ══════════════════════════════════════════════════════════════════

def create_conversation(client: str, title: Optional[str] = None) -> str:
    """创建对话，返回 ID"""
    cid = str(uuid.uuid4())
    now = _now()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO conversations (id, client, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (cid, client, title or f"对话 {now[:10]}", now, now),
    )
    conn.commit()
    conn.close()
    return cid


def save_messages(conversation_id: str, messages: list[dict]) -> list[str]:
    """批量保存消息，返回消息 ID 列表"""
    conn = _get_conn()
    now = _now()
    msg_ids = []
    for msg in messages:
        mid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, created_at, token_estimate) VALUES (?, ?, ?, ?, ?, ?)",
            (mid, conversation_id, msg.get("role", "user"), msg.get("content", ""), now, len(msg.get("content", "")) // 2),
        )
        msg_ids.append(mid)

    # 更新对话信息
    conn.execute(
        "UPDATE conversations SET turn_count = turn_count + ?, updated_at = ? WHERE id = ?",
        (len(messages), now, conversation_id),
    )
    conn.commit()
    conn.close()
    return msg_ids


def get_conversation(conversation_id: str) -> Optional[dict]:
    """获取对话信息"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_conversation_messages(conversation_id: str, limit: int = 100) -> list[dict]:
    """获取对话消息"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_conversations(limit: int = 10) -> list[dict]:
    """获取最近对话列表"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════
# Memory CRUD
# ══════════════════════════════════════════════════════════════════

def _row_to_memory(row: sqlite3.Row) -> dict:
    mem = dict(row)
    if mem.get("metadata"):
        try:
            mem["metadata"] = json.loads(mem["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
    return mem


def create_memory(
    content: str,
    memory_type: str = "fact",
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    importance: float = 0.3,
    metadata: Optional[dict] = None,
) -> str:
    """创建一条记忆，同时写入 SQLite + ChromaDB"""
    mid = str(uuid.uuid4())
    now = _now()
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)

    conn = _get_conn()
    conn.execute(
        """INSERT INTO memories
           (id, conversation_id, message_id, memory_type, content, importance,
            created_at, updated_at, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (mid, conversation_id, message_id, memory_type, content, importance,
         now, now, meta_json),
    )
    # 默认热存储
    conn.execute(
        "INSERT OR REPLACE INTO memory_tiers (memory_id, tier, updated_at) VALUES (?, 'hot', ?)",
        (mid, now),
    )
    conn.commit()
    conn.close()

    # 写入 ChromaDB
    try:
        _upsert_vector(mid, content, {"memory_type": memory_type, "importance": str(importance)})
    except Exception as e:
        print(f"[映记] 向量写入失败 (非致命): {e}")

    return mid


def get_memory(memory_id: str) -> Optional[dict]:
    """获取单条记忆"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    conn.close()
    return _row_to_memory(row) if row else None


def search_memories(
    query: Optional[str] = None,
    memory_type: Optional[str] = None,
    min_importance: float = 0.0,
    limit: int = 20,
) -> list[dict]:
    """搜索记忆：优先语义检索，回退关键词"""
    conn = _get_conn()

    # 如果有 query，走语义检索
    if query and query.strip():
        try:
            vector_ids = _search_vector(query, limit)
            if vector_ids:
                placeholders = ",".join("?" * len(vector_ids))
                sql = f"SELECT * FROM memories WHERE id IN ({placeholders})"
                params = list(vector_ids)
                if memory_type:
                    sql += " AND memory_type = ?"
                    params.append(memory_type)
                if min_importance > 0:
                    sql += " AND importance >= ?"
                    params.append(min_importance)
                rows = conn.execute(sql, params).fetchall()
                conn.close()
                return [_row_to_memory(r) for r in rows]
        except Exception:
            pass  # 向量检索失败，回退

    # 回退到 SQL 模糊搜索
    sql = "SELECT * FROM memories WHERE 1=1"
    params = []
    if query and query.strip():
        sql += " AND content LIKE ?"
        params.append(f"%{query}%")
    if memory_type:
        sql += " AND memory_type = ?"
        params.append(memory_type)
    if min_importance > 0:
        sql += " AND importance >= ?"
        params.append(min_importance)
    sql += " ORDER BY importance DESC, created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_row_to_memory(r) for r in rows]


def recall_memories(query: str, top_k: int = 5, memory_type: Optional[str] = None) -> list[dict]:
    """智能召回：检索 + 排序 + 更新访问统计"""
    results = search_memories(query=query, memory_type=memory_type, limit=top_k)

    # 更新访问统计
    if results:
        now = _now()
        conn = _get_conn()
        ids = [r["id"] for r in results]
        for mid in ids:
            conn.execute(
                """UPDATE memories SET access_count = access_count + 1,
                   last_accessed_at = ?
                   WHERE id = ?""",
                (now, mid),
            )
        conn.commit()
        conn.close()

    return results


def delete_memory(memory_id: str) -> bool:
    """删除记忆"""
    conn = _get_conn()
    c = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()

    if deleted:
        try:
            _delete_vector(memory_id)
        except Exception:
            pass
    return deleted


# ══════════════════════════════════════════════════════════════════
# 记忆层级管理
# ══════════════════════════════════════════════════════════════════

def get_memory_tier(memory_id: str) -> str:
    """获取记忆层级"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT tier FROM memory_tiers WHERE memory_id = ?", (memory_id,)
    ).fetchone()
    conn.close()
    return row["tier"] if row else "hot"


def update_tier(memory_id: str, tier: str):
    """更新记忆层级"""
    now = _now()
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO memory_tiers (memory_id, tier, updated_at) VALUES (?, ?, ?)",
        (memory_id, tier, now),
    )
    conn.commit()
    conn.close()


def get_tier_stats() -> dict:
    """获取各层级记忆数量"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT tier, COUNT(*) as cnt FROM memory_tiers GROUP BY tier"
    ).fetchall()
    conn.close()
    return {r["tier"]: r["cnt"] for r in rows}


# ══════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════

def get_stats() -> dict:
    """获取系统统计"""
    conn = _get_conn()
    mem_count = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
    conv_count = conn.execute("SELECT COUNT(*) as c FROM conversations").fetchone()["c"]

    by_type = {}
    rows = conn.execute("SELECT memory_type, COUNT(*) as c FROM memories GROUP BY memory_type").fetchall()
    for r in rows:
        by_type[r["memory_type"]] = r["c"]

    by_tier = get_tier_stats()
    conn.close()

    db_size = os.path.getsize(SQLITE_PATH) if os.path.exists(SQLITE_PATH) else 0

    return {
        "total_memories": mem_count,
        "total_conversations": conv_count,
        "memory_by_type": by_type,
        "memory_by_tier": by_tier,
        "storage_size_bytes": db_size,
    }


# ══════════════════════════════════════════════════════════════════
# ChromaDB 向量层
# ══════════════════════════════════════════════════════════════════

_client_instance = None


def _get_chroma_client():
    """获取 ChromaDB 客户端（单例）"""
    global _client_instance
    if _client_instance is None:
        _client_instance = chromadb.PersistentClient(
            path=CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client_instance


def _get_collection():
    """获取或创建集合"""
    client = _get_chroma_client()
    try:
        return client.get_collection(COLLECTION_NAME)
    except Exception:
        return client.create_collection(
            COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )


def _upsert_vector(memory_id: str, text: str, metadata: Optional[dict] = None):
    """写入/更新向量"""
    if not text.strip():
        return
    embedding = _embed(text)
    collection = _get_collection()
    collection.upsert(
        ids=[memory_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[metadata or {}],
    )


def _search_vector(query: str, top_k: int = 10) -> list[str]:
    """向量检索，返回记忆 ID 列表"""
    if not query.strip():
        return []
    embedding = _embed(query)
    collection = _get_collection()
    results = collection.query(
        query_embeddings=[embedding],
        n_results=min(top_k, 50),
    )
    if results and results.get("ids") and results["ids"][0]:
        return results["ids"][0]
    return []


def _delete_vector(memory_id: str):
    """删除向量"""
    collection = _get_collection()
    collection.delete(ids=[memory_id])
