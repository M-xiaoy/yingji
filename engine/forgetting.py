"""
映记 — 遗忘调度器
基于访问频率和时间的记忆生命周期管理
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from store.memory_store import (
    _get_conn, update_tier, get_tier_stats,
    FORGET_HOT_DAYS, FORGET_WARM_DAYS, FORGET_COLD_DAYS,
)


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def run_forgetting_cycle() -> dict:
    """
    执行一轮遗忘调度：
    - 超过 FORGET_HOT_DAYS 天未访问且非高频 → warm
    - 超过 FORGET_WARM_DAYS 天未访问且非高频 → cold
    - 超过 FORGET_COLD_DAYS 天未访问 → 标记可归档

    返回操作统计。
    """
    conn = _get_conn()
    now = _now()
    stats = {"hot_to_warm": 0, "warm_to_cold": 0, "cold_to_archive": 0, "errors": 0}

    try:
        # 1. hot → warm：超过 7 天未访问且低于 5 次
        rows = conn.execute(
            """SELECT id, access_count, last_accessed_at FROM memories m
               JOIN memory_tiers t ON m.id = t.memory_id
               WHERE t.tier = 'hot'
                 AND (m.last_accessed_at IS NULL
                      OR m.last_accessed_at < date('now', ? || ' days'))
                 AND m.access_count < 10""",
            (str(-FORGET_HOT_DAYS),),
        ).fetchall()

        for row in rows:
            update_tier(row["id"], "warm")
            stats["hot_to_warm"] += 1

        # 2. warm → cold：超过 30 天未访问
        rows = conn.execute(
            """SELECT id FROM memories m
               JOIN memory_tiers t ON m.id = t.memory_id
               WHERE t.tier = 'warm'
                 AND (m.last_accessed_at IS NULL
                      OR m.last_accessed_at < date('now', ? || ' days'))""",
            (str(-FORGET_WARM_DAYS),),
        ).fetchall()

        for row in rows:
            update_tier(row["id"], "cold")
            stats["warm_to_cold"] += 1

        # 3. cold 标记可归档：超过 90 天（仅标记 metadata）
        rows = conn.execute(
            """SELECT id FROM memories m
               JOIN memory_tiers t ON m.id = t.memory_id
               WHERE t.tier = 'cold'
                 AND (m.last_accessed_at IS NULL
                      OR m.last_accessed_at < date('now', ? || ' days'))""",
            (str(-FORGET_COLD_DAYS),),
        ).fetchall()

        for row in rows:
            # 更新 metadata 标记可归档
            conn.execute(
                "UPDATE memories SET metadata = json_set(COALESCE(metadata, '{}'), '$.archivable', 1) WHERE id = ?",
                (row["id"],),
            )
            stats["cold_to_archive"] += 1

        conn.commit()

    except Exception as e:
        conn.rollback()
        stats["errors"] += 1
        stats["error_msg"] = str(e)
    finally:
        conn.close()

    stats["current_tiers"] = get_tier_stats()
    return stats


def get_memory_health() -> dict:
    """
    记忆健康报告
    """
    conn = _get_conn()

    total = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]

    stats = {
        "total_memories": total,
        "tiers": get_tier_stats(),
        "never_accessed": conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE access_count = 0"
        ).fetchone()["c"],
        "high_importance": conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE importance >= 0.7"
        ).fetchone()["c"],
    }

    conn.close()
    return stats
