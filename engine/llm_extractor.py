"""
映记 — LLM 增强记忆提取器
用 DeepSeek API 对对话进行深度记忆提取，替代规则版 extractor 的关键词匹配。

设计原则：
1. 结构化输出（JSON）— 确保提取结果可稳定解析
2. 批量化 — 一次 LLM 调用提取多条记忆，降低 token 开销
3. 保底降级 — LLM 失败时自动回退规则版 extractor
"""

import json
import os
import re
from typing import Optional
from datetime import datetime

import requests

from store.memory_store import create_memory
from engine.extractor import extract_and_store as fallback_extract


# ─── DeepSeek API 配置 ───

# 默认配置（实际读取优先级：openclaw.json > 环境变量 > 下面默认值）
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"
LLM_TIMEOUT = 30  # 秒


def _get_api_key() -> str:
    """从 openclaw 配置中读取 DeepSeek API Key"""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key

    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            ds = cfg.get("models", {}).get("providers", {}).get("deepseek", {})
            return ds.get("apiKey", "")
        except Exception:
            pass
    return ""


def _get_api_base() -> str:
    """从 openclaw 配置中读取 DeepSeek API Base URL"""
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            ds = cfg.get("models", {}).get("providers", {}).get("deepseek", {})
            return ds.get("baseUrl", DEEPSEEK_BASE_URL)
        except Exception:
            pass
    return DEEPSEEK_BASE_URL


def _call_deepseek(system_prompt: str, user_prompt: str) -> Optional[str]:
    """调用 DeepSeek API（OpenAI 兼容格式）"""
    api_key = _get_api_key()
    if not api_key:
        return None

    base_url = _get_api_base()

    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,  # 低温度确保结构化输出稳定
                "max_tokens": 2048,
            },
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[llm_extractor] DeepSeek API 调用失败: {e}")
        return None


# ─── 系统提示词 ───

EXTRACTION_SYSTEM_PROMPT = """你是一个专业的记忆提取器。你的任务是从用户和AI的对话中提取值得记住的信息。

提取规则：
1. 只提取有价值的信息：用户偏好、重要事实、决策、计划、问题、关键见解
2. 忽略寒暄、语气词、重复、无关话题
3. 每条记忆独立完整，即使脱离上下文也能理解
4. 优先提取用户侧信息（偏好、决策、事实），辅助提取有价值的AI回应

输出格式：严格的 JSON 数组
[
  {
    "content": "记忆文本（完整的自然语句）",
    "memory_type": "fact | preference | decision | topic | question | insight",
    "importance": 0.0-1.0,
    "metadata": {
      "entities": ["相关实体名称，如项目名/人名/工具名"],
      "context": "这条记忆的产生背景简述"
    }
  }
]"""


def extract_with_llm(
    user_message: str,
    assistant_message: str,
    conversation_history: Optional[list[dict]] = None,
    conversation_id: Optional[str] = None,
) -> list[str]:
    """
    LLM 增强版提取：调用 DeepSeek API 提取记忆并存储。
    返回创建的 memory_id 列表。
    失败时自动降级到规则版 extractor。
    """
    # 构建 user prompt
    prompt_parts = []
    if conversation_history:
        for msg in conversation_history[-4:]:  # 最近4轮作为上下文
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]
            prompt_parts.append(f"[{role}]: {content}")

    prompt_parts.append(f"[user]: {user_message}")
    prompt_parts.append(f"[assistant]: {assistant_message}")

    user_prompt = "\n".join(prompt_parts)

    # 调用 LLM
    raw = _call_deepseek(EXTRACTION_SYSTEM_PROMPT, user_prompt)

    if not raw:
        print("[llm_extractor] LLM 不可用，降级到规则版 extractor")
        return fallback_extract(user_message, assistant_message, conversation_id)

    # 解析 JSON
    memories_data = _parse_json_response(raw)
    if not memories_data:
        print("[llm_extractor] JSON 解析失败，降级到规则版")
        return fallback_extract(user_message, assistant_message, conversation_id)

    # 存储
    memory_ids = []
    for item in memories_data:
        mem_type = item.get("memory_type", "fact")
        if mem_type not in ("fact", "preference", "decision", "topic", "question", "insight"):
            mem_type = "fact"

        mid = create_memory(
            content=item.get("content", ""),
            memory_type=mem_type,
            conversation_id=conversation_id,
            importance=min(max(item.get("importance", 0.3), 0.0), 1.0),
            metadata=item.get("metadata"),
        )
        memory_ids.append(mid)

    return memory_ids


def _parse_json_response(raw: str) -> Optional[list[dict]]:
    """从 LLM 响应中解析 JSON 数组"""
    # 尝试直接解析
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        return None
    except json.JSONDecodeError:
        pass

    # 尝试在文本中查找 JSON 数组
    match = re.search(r"\[\s*\{.*\}\s*\]", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return None


def extract_batch(
    messages: list[dict],
    conversation_id: Optional[str] = None,
) -> list[str]:
    """
    批量提取：将整段对话分块送 LLM 提取。
    每 4 轮打包一次，减少 API 调用次数。
    """
    all_ids = []
    batch_size = 4

    for i in range(0, len(messages) - 1, batch_size * 2):
        batch = messages[i:i + batch_size * 2]
        if len(batch) < 2:
            continue

        # 提取 user 和 assistant 交替对
        user_msgs = [m for m in batch if m.get("role") == "user"]
        ass_msgs = [m for m in batch if m.get("role") == "assistant"]

        if user_msgs and ass_msgs:
            combined_user = "\n".join(m.get("content", "") for m in user_msgs)
            combined_ass = "\n".join(m.get("content", "") for m in ass_msgs)

            ids = extract_with_llm(
                user_message=combined_user,
                assistant_message=combined_ass,
                conversation_history=batch,
                conversation_id=conversation_id,
            )
            all_ids.extend(ids)

        elif user_msgs:
            for m in user_msgs:
                ids = extract_with_llm(
                    user_message=m.get("content", ""),
                    assistant_message="",
                    conversation_id=conversation_id,
                )
                all_ids.extend(ids)

    return all_ids
