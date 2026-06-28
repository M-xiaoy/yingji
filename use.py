"""
映记 — 快速调用入口
小云通过此模块在对话中按需存取记忆。

用法：
  from 映记.use import recall, remember, remember_turn

  # 检索相关记忆（给当前对话上下文）
  memories = recall("多Agent token优化")

  # 存储当前对话的关键信息
  remember("用户决定用Tauri做前端框架", type="decision", importance=0.7)

  # 存储一轮对话
  remember_turn("用户消息", "AI回复", conv_id="xxx")
"""

import sys, os, json, requests

YINGJI_API = "http://127.0.0.1:8712/api/v1"


def recall(query: str, top_k: int = 3) -> list[dict]:
    """检索相关记忆。返回按重要性排序的记忆列表。"""
    try:
        resp = requests.post(
            f"{YINGJI_API}/recall",
            json={"query": query, "top_k": top_k},
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as e:
        print(f"[映记] recall 失败: {e}")
        return []


def remember(content: str, type: str = "fact", importance: float = 0.5,
              metadata: dict = None, conv_id: str = None) -> str | None:
    """手动存一条记忆。返回 memory_id。"""
    try:
        resp = requests.post(
            f"{YINGJI_API}/memories",
            json={
                "content": content,
                "memory_type": type,
                "importance": importance,
                "metadata": metadata or {},
                "conversation_id": conv_id,
            },
            timeout=5,
        )
        resp.raise_for_status()
        mid = resp.json().get("id", "")
        return mid
    except Exception as e:
        print(f"[映记] remember 失败: {e}")
        return None


def remember_turn(user_msg: str, assistant_msg: str = "",
                   conv_id: str = None, use_llm: bool = True) -> list[str]:
    """存一轮对话并提取记忆。返回 memory_id 列表。"""
    try:
        resp = requests.post(
            f"{YINGJI_API}/remember",
            json={
                "user_message": user_msg,
                "assistant_message": assistant_msg,
                "conversation_id": conv_id,
                "use_llm": use_llm,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("memories", [])
    except Exception as e:
        print(f"[映记] remember_turn 失败: {e}")
        return []


def format_memories(memories: list[dict]) -> str:
    """将记忆格式化为易读文本（不包含 emoji，避免 Windows GBK 问题）"""
    if not memories:
        return ""
    lines = ["[相关记忆]"]
    for m in memories:
        mt = m.get("memory_type", "fact")
        content = m.get("content", "")[:150]
        lines.append(f"  [{mt}] {content}")
    return "\n".join(lines)
