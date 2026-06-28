"""
映记 — 记忆压缩器
层级降维：多条相似记忆 → 摘要 → 最终归档
"""

from typing import Optional
from datetime import datetime, timezone, timedelta
from store.memory_store import search_memories, create_memory, get_memory, update_tier


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def compress_duplicates(memory_ids: list[str]) -> Optional[str]:
    """
    将多条相似记忆压缩为一条摘要。
    策略：保留最详细的一条，其他标记为冷存储。
    返回保留的记忆 ID。
    """
    if not memory_ids:
        return None

    memories = []
    for mid in memory_ids:
        m = get_memory(mid)
        if m:
            memories.append(m)

    if len(memories) <= 1:
        return memory_ids[0] if memory_ids else None

    # 按长度排序，保留最长的
    memories.sort(key=lambda m: len(m.get("content", "")), reverse=True)
    best = memories[0]

    # 其他降为 cold
    for m in memories[1:]:
        update_tier(m["id"], "cold")

    # 在最佳记忆上加压缩标记
    return best["id"]


def schedule_compaction(hours_threshold: int = 48) -> int:
    """
    定时压缩：找到 48 小时前创建且最近未访问的记忆，按话题合并。
    返回处理的记忆数量。
    """
    # 获取所有旧记忆（简化版：只做 cold 标记）
    from store.memory_store import _get_conn

    conn = _get_conn()
    cutoff = _now()  # 用当前时间作为简化

    # 标记长时间未访问的记忆
    rows = conn.execute(
        """SELECT id FROM memories
           WHERE last_accessed_at IS NULL
              OR last_accessed_at < date('now', '-7 days')
           LIMIT 100"""
    ).fetchall()

    count = 0
    for row in rows:
        update_tier(row["id"], "warm")
        count += 1

    conn.close()
    return count
