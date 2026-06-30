"""
经验追踪器 — 自动记录每一次 handler 调用的成败与上下文

让 Yingji 通过自己的记忆库实现自我迭代：
  1. 每次 handler 执行 → 自动记录
  2. 出错时 → 自动搜索相似历史经验
  3. 返回结果时 → 附带经验上下文
  4. 再次遇到同类问题 → 直接给出历史方案
"""

import traceback
from datetime import datetime
from typing import Optional, Any, Callable

# 导入 Yingji 自己的记忆库
from store.memory_store import create_memory, recall_memories

# 经验类型常量
EXPERIENCE_TYPE = "experience"


def record_experience(intent: str, params: dict, result: dict,
                      error: Optional[str] = None,
                      duration_ms: Optional[float] = None,
                      recovery: Optional[str] = None) -> Optional[str]:
    """
    记录一次 handler 执行经验到 Yingji 记忆库。

    写入内容（content）:
        自然语言描述，方便语义检索

    元数据（metadata）:
        结构化信息，供程序精确匹配

    Returns:
        记忆 ID，存储失败时返回 None
    """
    status = "error" if error or result.get("status") == "error" else "success"
    outcome = result.get("status", status)

    # 构造自然语言描述（方便 recall 语义搜索）
    if error:
        description = (
            f"[{intent}] 失败: {error}\n"
            f"参数: {params}\n"
            f"时间: {datetime.now().isoformat()}"
        )
    else:
        description = (
            f"[{intent}] 成功\n"
            f"参数: {params}\n"
            f"时间: {datetime.now().isoformat()}"
        )

    # 元数据（供结构化过滤）
    meta = {
        "intent": intent,
        "outcome": outcome,
        "error": error or "",
        "params": str(params),
        "duration_ms": duration_ms or 0,
        "recovery": recovery or "",
    }

    # 写入记忆库
    try:
        mid = create_memory(
            content=description,
            memory_type=EXPERIENCE_TYPE,
            importance=0.5 if outcome == "error" else 0.2,
            metadata=meta,
        )
        return mid
    except Exception:
        return None


def search_experience(query: str, top_k: int = 3) -> list[dict]:
    """
    搜索历史经验。

    语义搜索（自动）：通过 content 自然语言匹配
    过滤：只返回 EXPERIENCE_TYPE 的记忆
    """
    try:
        results = recall_memories(query=query, top_k=top_k,
                                   memory_type=EXPERIENCE_TYPE)
        extracted = []
        for r in results:
            meta = r.get("metadata", {}) or {}
            extracted.append({
                "id": r.get("id", ""),
                "content": r.get("content", "")[:200],
                "intent": meta.get("intent", ""),
                "outcome": meta.get("outcome", ""),
                "error": meta.get("error", ""),
                "recovery": meta.get("recovery", ""),
                "time": r.get("created_at", r.get("timestamp", "")),
                "importance": r.get("importance", 0),
            })
        return extracted
    except Exception:
        return []


def search_related_experience(intent: str, error_msg: str = "",
                               top_k: int = 3) -> list[dict]:
    """
    根据 intent + 错误信息搜索关联经验。

    以 intent 名为第一线索，错误描述为补充线索。
    """
    query = f"{intent} {error_msg[:100]}"
    return search_experience(query=query, top_k=top_k)


def format_experience_hint(past_experiences: list[dict]) -> str:
    """将历史经验格式化为自然语言提示"""
    if not past_experiences:
        return ""

    lines = ["\n📋 基于历史经验的建议："]
    for exp in past_experiences[:2]:
        intent = exp.get("intent", "")
        outcome = exp.get("outcome", "?")
        error = exp.get("error", "")
        recovery = exp.get("recovery", "")
        parts = [f"[{intent}] {outcome}"]
        if error:
            parts.append(f"曾报错: {error[:80]}")
        if recovery:
            parts.append(f"修复: {recovery[:100]}")
        lines.append(f"  {' → '.join(parts)}")
    return "\n".join(lines)


# ───────── 装饰器 — 自动追踪任意 handler ─────────

def auto_track(handler_fn: Callable) -> Callable:
    """
    自动追踪 handler 的装饰器。

    用法:
        @auto_track
        def my_handler(params):
            ...

    自动做:
      1. 记录调用开始时间
      2. 执行 handler
      3. 记录结果（成功/失败）
      4. 失败时搜索历史经验
      5. 附带经验提示到返回结果中
    """
    import functools

    @functools.wraps(handler_fn)
    def wrapper(params: dict) -> dict:
        from syncthing_service import get_intent_name
        intent = getattr(handler_fn, "_intent_name",
                         handler_fn.__name__)
        start = datetime.now()

        try:
            result = handler_fn(params)
            elapsed = (datetime.now() - start).total_seconds() * 1000

            # 成功时记录
            record_experience(
                intent=intent,
                params=params,
                result=result,
                duration_ms=elapsed,
            )

            return result

        except Exception as e:
            elapsed = (datetime.now() - start).total_seconds() * 1000
            error_msg = f"{type(e).__name__}: {e}"
            tb = traceback.format_exc()

            # 报错时记录 + 搜索历史
            record_experience(
                intent=intent,
                params=params,
                result={"status": "error", "message": error_msg},
                error=error_msg,
                duration_ms=elapsed,
            )
            past = search_related_experience(intent, error_msg)
            hint = format_experience_hint(past)

            return {
                "status": "error",
                "message": str(e),
                "experience_hint": hint,
                "traceback": tb,
            }

    return wrapper
