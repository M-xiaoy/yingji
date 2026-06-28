"""
映记 — 记忆提取器
从对话文本中提取结构化记忆：事实、偏好、决策、话题
"""

import re
from typing import Optional
from store.memory_store import create_memory


# ─── 话题/关键词提取（规则版） ───

_TOPIC_KEYWORDS = {
    "project": ["项目", "开发", "build", "搭建", "上线", "部署", "仓库"],
    "learning": ["学习", "学", "教程", "文档", "研究", "了解", "搞懂"],
    "preference": ["喜欢", "觉得", "想", "希望", "想要", "倾向", "偏好"],
    "decision": ["决定", "选", "选择", "换", "用", "改用", "采用"],
    "problem": ["问题", "bug", "报错", "错误", "故障", "卡", "不行"],
    "plan": ["打算", "计划", "准备", "明天", "下周", "下次", "下一步"],
}

_IMPORTANCE_BOOST = {
    "decision": 0.7,
    "project": 0.6,
    "problem": 0.6,
    "preference": 0.5,
    "plan": 0.5,
    "learning": 0.3,
}


def _classify_topic(text: str) -> str:
    """基于关键词的粗略主题分类"""
    text_lower = text.lower()
    for topic, keywords in _TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower or kw in text:
                return topic
    return "general"


def _extract_highlights(text: str, max_bullets: int = 3) -> list[str]:
    """提取可能是重要句子的片段"""
    sentences = re.split(r'[。！？\n.!?]', text)
    highlights = []

    # 含关键词的句子优先
    weight_keywords = ["关键", "核心", "重要", "注意", "记住", "必须", "一定", "决定", "选择"]
    for s in sentences:
        s = s.strip()
        if len(s) < 8:
            continue
        if any(kw in s for kw in weight_keywords):
            highlights.append(s)
            if len(highlights) >= max_bullets:
                break

    # 没找到，用最长句子
    if not highlights:
        sorted_s = sorted(sentences, key=len, reverse=True)
        for s in sorted_s[:max_bullets]:
            s = s.strip()
            if len(s) >= 10:
                highlights.append(s)

    return highlights


def extract_and_store(
    user_message: str,
    assistant_message: str,
    conversation_id: Optional[str] = None,
) -> list[str]:
    """
    从一轮对话中提取记忆并存储。
    返回创建的记忆 ID 列表。
    """
    memory_ids = []

    # 1. 从用户消息中提取
    user_topic = _classify_topic(user_message)
    importance = _IMPORTANCE_BOOST.get(user_topic, 0.3)

    highlights = _extract_highlights(user_message)
    for h in highlights:
        mid = create_memory(
            content=h,
            memory_type=user_topic if user_topic != "general" else "fact",
            conversation_id=conversation_id,
            importance=importance,
            metadata={"source": "user", "topic": user_topic},
        )
        memory_ids.append(mid)

    # 2. 从助手回复中提取（如果回复包含关键信息）
    if assistant_message:
        ass_topic = _classify_topic(assistant_message)
        ass_highlights = _extract_highlights(assistant_message)
        for h in ass_highlights:
            mid = create_memory(
                content=h,
                memory_type=ass_topic if ass_topic != "general" else "fact",
                conversation_id=conversation_id,
                importance=0.3,  # 助手回复重要性略低
                metadata={"source": "assistant", "topic": ass_topic},
            )
            memory_ids.append(mid)

    return memory_ids


def extract_conversation(
    messages: list[dict],
    conversation_id: Optional[str] = None,
) -> list[str]:
    """
    从完整对话中批量提取记忆。
    messages: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
    """
    all_ids = []
    for i in range(0, len(messages) - 1, 2):
        user_msg = messages[i] if messages[i].get("role") == "user" else None
        ass_msg = messages[i + 1] if i + 1 < len(messages) and messages[i + 1].get("role") == "assistant" else None

        if user_msg and ass_msg:
            ids = extract_and_store(
                user_msg.get("content", ""),
                ass_msg.get("content", ""),
                conversation_id=conversation_id,
            )
            all_ids.extend(ids)
        elif user_msg:
            ids = extract_and_store(
                user_msg.get("content", ""),
                "",
                conversation_id=conversation_id,
            )
            all_ids.extend(ids)

    return all_ids
