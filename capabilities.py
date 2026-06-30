"""
映记 v0.3 — 能力注册与操作白名单

服务方通过此模块注册操作，`_gate.py` 通过 `get_operations()` 获取完整白名单。
所有 intent 必须在此注册后才能通过关卡2 的校验。
"""

from typing import Optional

# 安全等级（与 config.py 保持一致）
SECURITY_LEVEL_READ = 1
SECURITY_LEVEL_WRITE = 2
SECURITY_LEVEL_DELETE = 3

# ─── 操作注册表 ───
# 格式: { "intent_name": { "description", "security_level", "parameters", ... } }
_operation_registry: dict = {}


def register(name: str, description: str, security_level: int = 1,
             requires_confirmation: bool = False,
             parameters: Optional[dict] = None,
             handler: Optional[callable] = None) -> None:
    """
    注册一个可用的操作。

    Args:
        name: 操作名（intent 标识，必须全局唯一）
        description: 操作描述（供能力声明用）
        security_level: 1=读取, 2=写入, 3=删除
        requires_confirmation: 是否需要安全确认
        parameters: 参数 Schema
        handler: 执行函数（默认用 _default_handlers）
    """
    if name in _operation_registry:
        raise ValueError(f"操作 '{name}' 已注册")
    _operation_registry[name] = {
        "name": name,
        "description": description,
        "security_level": security_level,
        "requires_confirmation": requires_confirmation,
        "parameters": parameters or {},
        "_handler": handler,
    }


def get_operations() -> dict:
    """返回所有已注册的操作（供关卡2/3 和安全门使用）"""
    return dict(_operation_registry)


def get_handler(intent: str) -> Optional[callable]:
    """获取指定 intent 的处理函数"""
    op = _operation_registry.get(intent)
    if op:
        return op.get("_handler")
    return None


# ─── 默认处理函数 ───

def _handler_recall(params: dict) -> dict:
    from store.memory_store import recall_memories
    query = params.get("query", "")
    top_k = min(params.get("top_k", 3), 10)
    results = recall_memories(query, top_k=top_k)
    return {
        "status": "success",
        "action": "recall",
        "total": len(results),
        "results": [
            {"id": r.get("id", ""), "type": r.get("memory_type", "fact"),
             "content": r.get("content", "")[:200], "importance": r.get("importance", 0)}
            for r in results
        ],
    }


def _handler_store(params: dict) -> dict:
    from store.memory_store import create_memory
    content = params.get("content", "")
    mtype = params.get("type", "fact")
    importance = min(max(params.get("importance", 0.5), 0), 1)
    mid = create_memory(content, memory_type=mtype, importance=importance)
    if mid:
        return {"status": "success", "action": "store", "id": mid}
    return {"status": "error", "message": "存储失败"}


def _handler_list(params: dict) -> dict:
    from store.memory_store import search_memories
    limit = min(params.get("limit", 10), 50)
    mtype = params.get("type")
    results = search_memories(query=None, memory_type=mtype, limit=limit)
    return {
        "status": "success",
        "action": "list",
        "total": len(results),
        "results": [
            {"id": r.get("id", ""), "type": r.get("memory_type", "fact"),
             "content": r.get("content", "")[:200], "created": r.get("created_at", "")}
            for r in results
        ],
    }


def _handler_delete(params: dict) -> dict:
    from store.memory_store import delete_memory
    mid = params.get("id", "")
    ok = delete_memory(mid)
    if ok:
        return {"status": "success", "action": "delete", "id": mid}
    return {"status": "error", "message": f"记忆 {mid} 不存在"}


# ─── 注册默认操作 ───

register("recall", "检索与给定话题相关的记忆", security_level=SECURITY_LEVEL_READ,
         requires_confirmation=False,
         parameters={"query": {"type": "string", "required": True},
                      "top_k": {"type": "integer", "default": 3}},
         handler=_handler_recall)

register("store", "存储一条新的记忆", security_level=SECURITY_LEVEL_WRITE,
         requires_confirmation=True,
         parameters={"content": {"type": "string", "required": True},
                      "type": {"type": "string", "default": "fact"},
                      "importance": {"type": "number", "default": 0.5}},
         handler=_handler_store)

register("list", "列出最近的记忆，按时间倒序", security_level=SECURITY_LEVEL_READ,
         requires_confirmation=False,
         parameters={"limit": {"type": "integer", "default": 10},
                      "type": {"type": "string", "optional": True}},
         handler=_handler_list)

register("delete", "删除一条指定的记忆", security_level=SECURITY_LEVEL_DELETE,
         requires_confirmation=True,
         parameters={"id": {"type": "string", "required": True}},
         handler=_handler_delete)
