"""
映记 — 记忆检索器
混合检索：向量语义 + SQL 关键词 + 重要性加权
"""

from typing import Optional
from store.memory_store import search_memories, recall_memories, get_memory_tier


def retrieve(
    query: str,
    top_k: int = 5,
    memory_type: Optional[str] = None,
    min_importance: float = 0.0,
    include_expired: bool = False,
) -> list[dict]:
    """
    主检索入口：智能召回 + 过滤 + 排序

    返回格式：
    [{
        "id": str,
        "content": str,
        "memory_type": str,
        "importance": float,
        "tier": "hot"|"warm"|"cold",
        "access_count": int,
        "created_at": str,
        ...
    }]
    """
    # 1. 先向量/关键词检索
    results = recall_memories(query, top_k=top_k * 2, memory_type=memory_type)

    # 2. 过滤
    filtered = []
    for r in results:
        if r.get("importance", 0) < min_importance:
            continue
        if not include_expired:
            tier = get_memory_tier(r["id"])
            if tier == "cold":
                continue
        r["tier"] = get_memory_tier(r["id"])
        filtered.append(r)

    # 3. 重排序：importance * 时间衰减
    from datetime import datetime

    def _score(mem: dict) -> float:
        imp = mem.get("importance", 0.3)
        tier_bonus = {"hot": 1.0, "warm": 0.7, "cold": 0.3}.get(mem.get("tier", "hot"), 0.5)
        return imp * tier_bonus

    filtered.sort(key=_score, reverse=True)

    return filtered[:top_k]


def format_context(results: list[dict], system_prompt: Optional[str] = None) -> str:
    """
    将检索结果格式化为可注入 LLM 上下文的纯文本。
    """
    if not results:
        return ""

    lines = ["\n─── 相关记忆（映记自动检索）───"]
    for i, r in enumerate(results, 1):
        tier_mark = {"hot": "🔥", "warm": "📎", "cold": "📦"}.get(r.get("tier", "hot"), "📄")
        mem_type = r.get("memory_type", "fact")
        content = r.get("content", "")[:200]
        lines.append(f"{tier_mark} [{mem_type}] {content}")

    if system_prompt:
        return system_prompt + "\n\n" + "\n".join(lines)
    return "\n".join(lines)
