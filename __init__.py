"""
映记 (Yìngjì) v0.2 — 程序的 AI 接口层

v0.2 新增 AI 对话层，可内嵌到任意程序使用
v0.3 新增安全门 + 能力注册中心 + AI-to-AI 协议

两种用法：

1. 内嵌模式（推荐）：
   from yingji import Yingji
   yj = Yingji()
   result = yj.chat("帮我查一下之前讨论过的实习计划")

2. 服务模式（兼容）：
   python server.py   # 启动 HTTP 服务
"""

from typing import Optional, Any

from config import AI_NAME

# ─── 引擎模块 ───
from capabilities import get_handler
from store.memory_store import get_stats, get_total_memory_count

# ─── v0.2 新模块 ───
from _capability import discover as discover_capability, describe as describe_capability
from _chat import process_chat

# ─── v0.3 安全门 ───
from _gate import validate_request, check_intent, check_security, clip_context, GateBlocked


class Yingji:
    """
    映记主类 — 程序的 AI 接口。

    用法：
        yj = Yingji()

        # AI 对话（外部 AI 用自然语言交流）
        reply = yj.chat("帮我查一下实习相关的记忆")

        # 传统工具调用（兼容）
        memories = yj.recall("实习")

        # 能力声明（让对方 AI 知道我能做什么）
        cap = yj.capability()
    """

    def __init__(self, name: str = None, max_context_turns: int = 10):
        self.name = name or AI_NAME
        self._engine_router = self._route_via_capabilities
        self._max_context_turns = max_context_turns
        # v0.3 上下文管理
        self._context = {
            "last_input": None,
            "last_intent": None,
            "last_params": None,
            "last_data": None,
            "last_reply": None,
            "turns": [],
        }

    # ─── v0.3 核心：AI 对话（带安全门） ───

    def chat(self, message: str | dict) -> dict:
        """
        外部 AI 通过此方法与映记对话。

        支持两种输入模式：
          模式1（协议模式）: 传入 dict，走三道代码关卡
          模式2（兼容模式）: 传入 str，走 LLM 意图理解（v0.2 fallback）

        返回结构化 dict（v0.3 统一格式）:
          reply:  自然语言回复
          status: success/error/need_info/need_confirmation
          intent: 匹配到的操作名
          data:   结构化执行结果
        """
        # ── 上下文裁剪（防止层级 0 被稀释） ──
        self._context = clip_context(self._context, self._max_context_turns)

        # ── 关卡1：协议校验（针对 dict 输入） ──
        if isinstance(message, dict):
            try:
                validate_request(message)
            except GateBlocked as e:
                return {
                    "reply": e.recovery_hint or e.detail,
                    "status": "error",
                    "error_code": e.error_code,
                    "intent": None,
                    "data": None,
                }

            intent = message.get("intent", "")
            content = message.get("content", "")
            params = message.get("params", {})
        else:
            # 兼容模式：纯文本输入 → 走 LLM 解析
            content = str(message)
            intent = None
            params = {}

        # ── 关卡2：Intent 白名单（协议模式才检查） ──
        if intent:
            operations = self._all_operations()
            try:
                check_intent(intent, operations)
            except GateBlocked as e:
                return {
                    "reply": e.recovery_hint or e.detail,
                    "status": "error",
                    "error_code": e.error_code,
                    "intent": intent,
                    "data": None,
                }

        # ── 关卡3：安全等级检查（协议模式才检查） ──
        if intent:
            operations = self._all_operations()
            security = check_security(intent, params, operations)
            if not security["approved"]:
                return {
                    "reply": security["reason"],
                    "status": "need_confirmation",
                    "intent": intent,
                    "data": {
                        "security_level": security.get("level", 2),
                        "needs_confirmation": True,
                    },
                }

        # ── 执行 ──
        if intent:
            # 协议模式：直接路由
            result = self._engine_router(intent, params)
        else:
            # 兼容模式：走 LLM 意图理解
            result = process_chat(content, engine_router=self._engine_router)
            if isinstance(result, str):
                return {
                    "reply": result,
                    "status": "success",
                    "intent": "chat",
                    "data": None,
                }
            return result

        # ── 更新上下文 ──
        self._context["last_input"] = content
        self._context["last_intent"] = intent
        self._context["last_params"] = params
        self._context["last_data"] = result
        self._context["turns"].append((content, result))

        # ── 构建响应 ──
        status = "error" if result.get("status") == "error" else "success"
        # 失败时附带经验提示
        if status == "error":
            reply = result.get("message", "操作失败")
            hint = result.get("experience_hint", "")
            if hint:
                reply += "\n" + hint
        else:
            reply = _format_success_reply(intent, result)
        return {
            "reply": reply,
            "status": status,
            "intent": intent,
            "data": result,
        }

    def _all_operations(self) -> dict:
        """
        收集所有可用 intent 白名单。
        v0.2 只有 memory 类操作，v0.3 扩展为 Service 注册模式。
        """
        from capabilities import get_operations
        return get_operations()

    # ─── v0.2 兼容：AI 对话（纯文本） ───

    def chat_text(self, message: str) -> str:
        """快捷方式：纯文本输入 + 纯文本输出（仅兼容）"""
        result = self.chat(message)
        return result.get("reply", "")

    # ─── v0.2 核心：能力声明 ───

    def capability(self, text_mode: bool = False):
        """
        返回映记的能力声明。
        text_mode=True 返回纯文本（供 chat() 用）
        text_mode=False 返回结构化 dict
        """
        if text_mode:
            return describe_capability()
        return discover_capability()

    # ─── v0.1 兼容：传统工具调用（直接调引擎，不走 HTTP） ───

    def recall(self, query: str, top_k: int = 3) -> list[dict]:
        """检索相关记忆（v0.1 兼容，直接调引擎不走 HTTP）"""
        from engine.retriever import retrieve
        return retrieve(query=query, top_k=top_k)

    def remember(self, content: str, type: str = "fact",
                  importance: float = 0.5, metadata: dict = None,
                  conv_id: str = None) -> Optional[str]:
        """存储记忆（v0.1 兼容，直接调引擎不走 HTTP）"""
        from store.memory_store import create_memory
        return create_memory(
            content=content,
            memory_type=type,
            importance=importance,
            metadata=metadata or {},
            conversation_id=conv_id,
        )

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """搜索记忆（v0.1 兼容）"""
        return search_memories(query=query, limit=limit)

    def stats(self) -> dict:
        """系统统计（v0.1 兼容）"""
        return get_stats()

    # ─── 统一路由 ───

    def _route_via_capabilities(self, intent: str, params: dict) -> dict:
        """
        通过 capabilities 注册中心路由 intent。
        所有 handler 都在 capabilities.py 中注册，
        新操作只需调一次 register() 即可加入路由。
        """
        handler = get_handler(intent)
        if handler:
            from experience_tracker import record_experience, search_related_experience, format_experience_hint
            from datetime import datetime
            start = datetime.now()
            try:
                result = handler(params)
            except Exception as e:
                result = {"status": "error", "message": str(e)}

            elapsed = (datetime.now() - start).total_seconds() * 1000

            # 记录本次执行经验
            record_experience(
                intent=intent,
                params=params,
                result=result,
                duration_ms=elapsed,
            )

            # 失败时自动查历史经验
            if result.get("status") == "error":
                past = search_related_experience(intent, result.get("message", ""))
                if past:
                    result["experience_hint"] = format_experience_hint(past)

            return result
        return {"status": "unknown_intent", "intent": intent}

    def __repr__(self):
        ops = list(self._all_operations().keys())
        return f"<Yingji name={self.name} intents={ops}>"


# ─── 辅助函数 ───

def _format_success_reply(intent: str, result: dict) -> str:
    """把成功执行结果包装为自然语言回复"""
    action = result.get("action", intent)
    status = result.get("status")

    if status == "error":
        return result.get("message", "操作失败")

    if intent == "recall":
        total = result.get("total", 0)
        if total == 0:
            return "没有找到相关记录。"
        items = result.get("results", [])
        lines = [f"找到 {total} 条相关记录："]
        for i, item in enumerate(items[:5], 1):
            content = item.get("content", "")[:80]
            lines.append(f"  {i}. {content}")
        if total > 5:
            lines.append(f"  ...还有 {total - 5} 条")
        return "\n".join(lines)

    if intent == "store":
        return "已保存。"

    if intent == "delete":
        return f"已删除。"

    if intent == "list":
        total = result.get("total", 0)
        if total == 0:
            return "当前没有记录。"
        items = result.get("results", [])
        lines = [f"共 {total} 条："]
        for i, item in enumerate(items[:10], 1):
            content = item.get("content", "")[:60]
            lines.append(f"  {i}. {content}")
        return "\n".join(lines)

    # 通用 fallback：handler 自带 message/summary 时直接返回
    if "message" in result:
        return result["message"]
    if "summary" in result:
        return result["summary"]

    return "操作完成。"


# ─── 快捷入口 ───

_default_instance = None


def get_default() -> Yingji:
    """获取默认实例（单例）"""
    global _default_instance
    if _default_instance is None:
        _default_instance = Yingji()
    return _default_instance
