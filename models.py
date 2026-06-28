"""
映记 — Pydantic 模型
"""
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field


# ─── 记忆操作 ───

class MemoryCreate(BaseModel):
    """创建记忆的请求"""
    content: str = Field(..., description="记忆文本内容")
    memory_type: str = Field("fact", description="类型: fact/preference/decision/topic/question/insight")
    conversation_id: Optional[str] = None
    importance: float = Field(0.3, ge=0.0, le=1.0)
    metadata: Optional[dict] = None


class MemoryResponse(BaseModel):
    """记忆响应"""
    id: str
    content: str
    memory_type: str
    importance: float
    access_count: int
    created_at: str
    last_accessed_at: Optional[str] = None
    metadata: Optional[dict] = None
    tier: str = "hot"
    score: Optional[float] = None


class MemoryListResponse(BaseModel):
    """记忆列表响应"""
    total: int
    memories: list[MemoryResponse]


# ─── 对话操作 ───

class ConversationCreate(BaseModel):
    """创建/保存对话"""
    client: str = Field("unknown", description="客户端标识 (deepseek/openai/custom)")
    title: Optional[str] = None
    messages: list[dict] = Field(..., description="消息列表 [{role, content}, ...]")


class ConversationResponse(BaseModel):
    """对话响应"""
    id: str
    client: str
    title: Optional[str]
    turn_count: int
    created_at: str
    updated_at: str


# ─── 检索操作 ───

class RecallRequest(BaseModel):
    """召回相关记忆的请求"""
    query: str = Field(..., description="查询文本/上下文")
    top_k: int = Field(5, ge=1, le=50)
    memory_type: Optional[str] = None
    min_importance: float = Field(0.0, ge=0.0, le=1.0)
    include_expired: bool = False


class RecallResponse(BaseModel):
    """召回结果"""
    query: str
    results: list[MemoryResponse]
    total: int


# ─── 搜索操作 ───

class SearchRequest(BaseModel):
    """搜索记忆"""
    query: str
    top_k: int = Field(10, ge=1, le=50)
    memory_type: Optional[str] = None


class SearchResponse(BaseModel):
    """搜索结果"""
    query: str
    results: list[MemoryResponse]
    total: int


# ─── 会话注入 ───

class ContextInjectRequest(BaseModel):
    """给 LLM 调用前注入上下文的请求"""
    user_message: str = Field(..., description="用户当前消息")
    top_k: int = 5
    system_prompt: Optional[str] = None


class ContextInjectResponse(BaseModel):
    """注入结果"""
    user_message: str
    memories: list[MemoryResponse]
    memory_context: str  # 格式化为可直接注入 system prompt 的文本
    system_prompt: Optional[str]


# ─── 统计 ───

class StatsResponse(BaseModel):
    """系统统计"""
    total_memories: int
    total_conversations: int
    memory_by_type: dict
    memory_by_tier: dict  # hot/warm/cold
    storage_size_bytes: int
