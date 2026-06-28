"""
映记 — 记忆检索工具 (Function Calling)
========================================
OpenAI/DeepSeek 兼容的 function calling 工具定义 + handler。

用法：
  1. 把 RECALL_TOOL_DEFINITION 作为 tool 传给 LLM API
  2. LLM 返回 tool_call 时，调 execute_recall(query) 获取记忆
  3. 把结果作为 tool_message 回传给 LLM
"""

import requests
from typing import Optional

# ─── 映记服务地址 ───
YINGJI_API_BASE = "http://127.0.0.1:8712/api/v1"


# ══════════════════════════════════════════════════════════════
# Tool Definition — 发给 LLM 的 function calling schema
# ══════════════════════════════════════════════════════════════

RECALL_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "recall_memory",
        "description": (
            "检索与当前话题相关的历史记忆。"
            "当用户提到之前讨论过的项目、决策、偏好、技术方案、问题或计划时，"
            "调用此工具获取相关记忆上下文。"
            "每次调用返回最多 5 条最相关的记忆，按重要性排序。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词。基于当前对话的核心话题生成，"
                                   "例如用户说'我们上次讨论的优化方案'，query='优化方案'。"
                                   "中文优先。",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回的记忆数量 (1-5)",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 5,
                },
            },
            "required": ["query"],
        },
    },
}


# ══════════════════════════════════════════════════════════════
# System Prompt 片段 — 告诉模型何时用这个工具
# ══════════════════════════════════════════════════════════════

RECALL_SYSTEM_PROMPT = (
    "你有 recall_memory 工具可用于检索历史记忆。"
    "以下情况请主动调用：\n"
    "1. 用户提到之前讨论过的技术方案、项目或决策时\n"
    "2. 用户说'还记得…吗''上次…''之前讨论的…'等引用性表述时\n"
    "3. 你发现当前话题和记忆中某个话题高度相关时\n"
    "4. 用户询问你的建议，而你知道过去有过相关讨论时\n\n"
    "调用后根据返回的记忆提供更准确的回应。"
    "如果返回空结果，正常回应即可。"
)


# ══════════════════════════════════════════════════════════════
# Tool Handler — 执行工具调用
# ══════════════════════════════════════════════════════════════

def execute_recall(query: str, top_k: int = 3) -> dict:
    """
    执行记忆检索，返回给 LLM 的结构化结果。
    返回格式符合 function calling 的 tool_message 要求。
    """
    try:
        resp = requests.post(
            f"{YINGJI_API_BASE}/recall",
            json={"query": query, "top_k": top_k},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return {
            "role": "tool",
            "content": f"记忆检索服务暂不可用: {e}",
            "tool_call_id": None,
        }

    results = data.get("results", [])

    if not results:
        return {
            "role": "tool",
            "content": "未找到相关记忆。",
            "tool_call_id": None,
        }

    # 格式化为易读文本
    lines = ["找到以下相关记忆："]
    for i, m in enumerate(results, 1):
        tier_mark = {"hot": "🔥", "warm": "📎", "cold": "📦"}.get(m.get("tier", "hot"), "📄")
        mem_type = m.get("memory_type", "fact")
        content = m.get("content", "")
        imp = m.get("importance", 0)
        lines.append(f'{i}. {tier_mark} [{mem_type}] (重要性: {imp}) {content}')

    return {
        "role": "tool",
        "content": "\n".join(lines),
        "tool_call_id": None,
    }


# ══════════════════════════════════════════════════════════════
# 简化接口 — 一步调用（不需要函数注册）
# ══════════════════════════════════════════════════════════════

def simple_recall(query: str, top_k: int = 3) -> list[dict]:
    """
    直接获取格式化记忆列表（不经过 function calling 流程）。
    适用于小云直接调用映记 API。
    """
    try:
        resp = requests.post(
            f"{YINGJI_API_BASE}/recall",
            json={"query": query, "top_k": top_k},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])
    except requests.RequestException as e:
        print(f"[recall_tool] 检索失败: {e}")
        return []


def format_memories_for_llm(results: list[dict]) -> str:
    """将记忆列表格式化为纯文本，供 LLM 直接读取"""
    if not results:
        return ""

    lines = ["\n── 相关记忆 ──"]
    for i, m in enumerate(results, 1):
        tier = m.get("tier", "hot")
        mem_type = m.get("memory_type", "fact")
        content = m.get("content", "")[:200]
        lines.append(f"  [{mem_type}] {content}")
    return "\n".join(lines)
