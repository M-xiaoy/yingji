"""
映记 v0.3 — 安全门 (Governance Gate)

三道代码关卡，在执行任何操作前拦截非法/越权请求。
均在 LLM 调用之前执行，不受上下文稀释影响。
"""

from typing import Optional, Any

# ─── 可导出错误类型 ───
class GateBlocked(Exception):
    """关卡拦截异常"""
    def __init__(self, error_code: str, detail: str, recoverable: bool = False,
                 recovery_hint: str = ""):
        self.error_code = error_code
        self.detail = detail
        self.recoverable = recoverable
        self.recovery_hint = recovery_hint
        super().__init__(f"[{error_code}] {detail}")


# ══════════════════════════════════════════════════════════════
# 关卡1：协议校验层
# ══════════════════════════════════════════════════════════════

# 协议要求的必填字段
_REQUIRED_REQUEST_FIELDS = {"type", "session_id", "message_id", "content"}
_ALLOWED_TYPES = {"request"}


def validate_request(msg: dict) -> None:
    """
    关卡1：校验传入请求的协议格式。

    所有请求必须先通过此关，格式不合格直接拒绝，不经过 LLM。

    校验项：
      - 必须是 dict
      - type 字段必须存在且有效
      - 必填字段齐全
      - 字段类型正确
    """
    if not isinstance(msg, dict):
        raise GateBlocked(
            "invalid_format",
            f"请求必须是 JSON 对象，收到 {type(msg).__name__}",
            recoverable=True,
            recovery_hint="请发送有效的 JSON 格式请求",
        )

    # 校验 type 字段
    msg_type = msg.get("type")
    if not msg_type:
        raise GateBlocked(
            "invalid_format",
            "缺少 type 字段",
            recoverable=True,
            recovery_hint="请求必须包含 type 字段（'request'）",
        )
    if msg_type not in _ALLOWED_TYPES:
        raise GateBlocked(
            "invalid_format",
            f"不支持的 type: '{msg_type}'，仅支持 {_ALLOWED_TYPES}",
            recoverable=True,
            recovery_hint=f"请使用 type='request'",
        )

    # 校验必填字段
    missing = _REQUIRED_REQUEST_FIELDS - set(msg.keys())
    if missing:
        raise GateBlocked(
            "invalid_format",
            f"缺少必填字段: {', '.join(sorted(missing))}",
            recoverable=True,
            recovery_hint=f"请补充: {', '.join(sorted(missing))}",
        )

    # 校验字段类型
    if not isinstance(msg.get("content"), str):
        raise GateBlocked(
            "invalid_format",
            "content 必须是字符串",
            recoverable=True,
        )

    if not isinstance(msg.get("session_id"), str):
        raise GateBlocked(
            "invalid_format",
            "session_id 必须是字符串",
            recoverable=True,
        )


# ══════════════════════════════════════════════════════════════
# 关卡2：Intent 白名单
# ══════════════════════════════════════════════════════════════

def check_intent(intent: str, operations: dict) -> None:
    """
    关卡2：校验 intent 是否在已注册 Service 的白名单中。

    只有已注册 Service 中声明的 intent 才能通过。
    直接拒绝未知 intent，不经过 LLM。
    """
    if not isinstance(intent, str) or not intent.strip():
        raise GateBlocked(
            "intent_unknown",
            "intent 必须是非空字符串",
            recoverable=True,
            recovery_hint="请在请求中指定有效的 intent",
        )

    if intent not in operations:
        available = list(operations.keys()) if operations else ["（当前无可用操作）"]
        raise GateBlocked(
            "intent_unknown",
            f"intent '{intent}' 不在已注册的 Service 中。可用操作: {available}",
            recoverable=True,
            recovery_hint=f"可用操作: {available}。如需要闲聊请使用 intent='chat'",
        )


# ══════════════════════════════════════════════════════════════
# 关卡3：安全等级检查
# ══════════════════════════════════════════════════════════════

def check_security(intent: str, params: dict, operations: dict) -> dict:
    """
    关卡3：检查操作的安全等级。

    返回值:
      - {"approved": True} — 直接放行
      - {"approved": False, "reason": "..."} — 需要确认
      - {"approved": False, "reason": "...", "level": 3} — 需要双重确认

    所有写/删操作必须经过明确的用户方 AI 确认，
    LLM 无权自行批准未确认的操作。
    """
    op_def = operations.get(intent, {})
    security_level = op_def.get("security_level", 1)
    requires_confirmation = op_def.get("requires_confirmation", False)

    # L1 直接放行
    if security_level == 1 and not requires_confirmation:
        return {"approved": True}

    # L2 需要单次确认
    if security_level >= 2 or requires_confirmation:
        if params.get("_confirmed") is True:
            # 已确认 → 放行
            return {"approved": True}
        else:
            reason = op_def.get("description", intent)
            return {
                "approved": False,
                "reason": f"操作 '{intent}' ({reason}) 需要安全确认",
                "level": security_level,
            }

    return {"approved": True}


# ══════════════════════════════════════════════════════════════
# 辅助：上下文裁剪
# ══════════════════════════════════════════════════════════════

def clip_context(context: dict, max_turns: int = 10,
                 keep_system: list[str] = None) -> dict:
    """
    上下文裁剪策略：

    当对话轮次超过上限时：
      1. 保留系统级字段（层级 0 和 1 的信息）
      2. 保留最近 N 轮对话（context.turns 裁剪）
      3. 删除中间的历史轮次

    Args:
        context: 当前上下文 dict
        max_turns: 保留的最大轮次数
        keep_system: 永远保留的字段名列表

    Returns:
        裁剪后的上下文
    """
    if keep_system is None:
        keep_system = ["last_input", "last_intent", "last_params",
                       "last_data", "last_reply", "last_service"]

    if len(context.get("turns", [])) <= max_turns:
        return context

    clipped = context.copy()

    # 保留最近的 N 轮
    turns = context.get("turns", [])
    clipped["turns"] = turns[-max_turns:]

    # 保留系统级字段（继承最新的值）
    for field in keep_system:
        if field in context:
            clipped[field] = context[field]

    return clipped
