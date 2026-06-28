"""
映记 — API 路由
"""

import json
import os
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models import (
    MemoryCreate, MemoryResponse, MemoryListResponse,
    ConversationCreate, ConversationResponse,
    RecallRequest, RecallResponse,
    SearchRequest, SearchResponse,
    ContextInjectRequest, ContextInjectResponse,
    StatsResponse,
)
from store.memory_store import (
    init_db, create_memory, get_memory, search_memories, recall_memories,
    delete_memory, get_stats, create_conversation, save_messages,
    get_conversation, get_conversation_messages, get_recent_conversations,
    _now,
)
from engine.extractor import extract_and_store, extract_conversation as rule_extract_conversation
from engine.llm_extractor import extract_with_llm, extract_batch
from engine.retriever import retrieve, format_context
from engine.forgetting import run_forgetting_cycle, get_memory_health

router = APIRouter(prefix="/api/v1")


# ─── 健康检查 ───

@router.get("/health")
def health():
    return {"status": "ok", "service": "映记 v0.1.0"}


# ─── LLM 增强记忆提取 ───

class RememberRequest(BaseModel):
    """单轮记忆提取请求"""
    user_message: str = Field(..., description="用户消息")
    assistant_message: str = Field("", description="AI 回复（可选）")
    conversation_history: Optional[list[dict]] = None
    conversation_id: Optional[str] = None
    use_llm: bool = Field(True, description="是否使用 LLM 增强提取")


@router.post("/remember", response_model=dict)
def api_remember(req: RememberRequest):
    """
    LLM 增强记忆提取：输入一轮对话，自动提取并存储记忆。
    默认使用 DeepSeek API 进行深度提取，失败时降级到规则版。
    """
    if req.use_llm:
        memory_ids = extract_with_llm(
            user_message=req.user_message,
            assistant_message=req.assistant_message,
            conversation_history=req.conversation_history,
            conversation_id=req.conversation_id,
        )
    else:
        memory_ids = extract_and_store(
            user_message=req.user_message,
            assistant_message=req.assistant_message,
            conversation_id=req.conversation_id,
        )

    memories = []
    for mid in memory_ids:
        m = get_memory(mid)
        if m:
            memories.append(MemoryResponse(**m))

    return {
        "memories_extracted": len(memory_ids),
        "extraction_method": "llm" if req.use_llm else "rules",
        "memories": memories,
    }


# ─── 记忆 CRUD ───

@router.post("/memories", response_model=MemoryResponse)
def api_create_memory(req: MemoryCreate):
    """创建一条记忆"""
    mid = create_memory(
        content=req.content,
        memory_type=req.memory_type,
        conversation_id=req.conversation_id,
        importance=req.importance,
        metadata=req.metadata,
    )
    mem = get_memory(mid)
    if not mem:
        raise HTTPException(500, "记忆创建失败")
    return MemoryResponse(**mem)


@router.get("/memories/{memory_id}", response_model=MemoryResponse)
def api_get_memory(memory_id: str):
    """获取单条记忆"""
    mem = get_memory(memory_id)
    if not mem:
        raise HTTPException(404, "记忆不存在")
    return MemoryResponse(**mem)


@router.delete("/memories/{memory_id}")
def api_delete_memory(memory_id: str):
    """删除记忆"""
    ok = delete_memory(memory_id)
    if not ok:
        raise HTTPException(404, "记忆不存在")
    return {"status": "deleted", "id": memory_id}


@router.get("/memories", response_model=MemoryListResponse)
def api_list_memories(q: Optional[str] = None, memory_type: Optional[str] = None, limit: int = 20):
    """搜索/列出记忆"""
    results = search_memories(query=q, memory_type=memory_type, limit=limit)
    return MemoryListResponse(
        total=len(results),
        memories=[MemoryResponse(**r) for r in results],
    )


# ─── 召回 ───

@router.post("/recall", response_model=RecallResponse)
def api_recall(req: RecallRequest):
    """智能召回：给定上下文，返回相关记忆"""
    results = retrieve(
        query=req.query,
        top_k=req.top_k,
        memory_type=req.memory_type,
        min_importance=req.min_importance,
        include_expired=req.include_expired,
    )
    return RecallResponse(
        query=req.query,
        total=len(results),
        results=[MemoryResponse(**r) for r in results],
    )


# ─── 搜索 ───

@router.post("/search", response_model=SearchResponse)
def api_search(req: SearchRequest):
    """语义搜索记忆"""
    results = search_memories(query=req.query, memory_type=req.memory_type, limit=req.top_k)
    return SearchResponse(
        query=req.query,
        total=len(results),
        results=[MemoryResponse(**r) for r in results],
    )


# ─── 对话管理 ───

@router.post("/conversations", response_model=dict)
def api_save_conversation(req: ConversationCreate):
    """保存对话并自动提取记忆"""
    # 创建对话
    cid = create_conversation(client=req.client, title=req.title)
    save_messages(cid, req.messages)

    # 提取记忆（LLM 增强版，失败降级）
    extracted_ids = extract_batch(req.messages, conversation_id=cid)

    conv = get_conversation(cid)
    return {
        "conversation": ConversationResponse(**conv) if conv else None,
        "memories_extracted": len(extracted_ids),
        "memory_ids": extracted_ids,
    }


@router.get("/conversations", response_model=list)
def api_list_conversations(limit: int = 10):
    """最近对话列表"""
    convs = get_recent_conversations(limit=limit)
    return [ConversationResponse(**c) for c in convs]


@router.get("/conversations/{conv_id}", response_model=dict)
def api_get_conversation(conv_id: str):
    """获取对话详情"""
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    messages = get_conversation_messages(conv_id)
    return {
        "conversation": ConversationResponse(**conv),
        "messages": messages,
    }


# ─── 上下文注入 ───

@router.post("/context-inject", response_model=ContextInjectResponse)
def api_context_inject(req: ContextInjectRequest):
    """
    给 LLM 调用前注入上下文。
    输入用户消息 → 检索相关记忆 → 格式化为上下文字符串。
    """
    results = retrieve(query=req.user_message, top_k=req.top_k)
    context_text = format_context(results, system_prompt=req.system_prompt)

    return ContextInjectResponse(
        user_message=req.user_message,
        memories=[MemoryResponse(**r) for r in results],
        memory_context=context_text,
        system_prompt=req.system_prompt,
    )


# ─── 遗忘调度 ───

@router.post("/forgetting/run")
def api_run_forgetting():
    """手动触发遗忘调度"""
    stats = run_forgetting_cycle()
    return {"status": "completed", "stats": stats}


@router.get("/forgetting/health")
def api_forgetting_health():
    """记忆健康报告"""
    return get_memory_health()


# ─── 统计 ───

@router.get("/stats", response_model=StatsResponse)
def api_stats():
    """系统统计"""
    return StatsResponse(**get_stats())
