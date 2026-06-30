"""
映记 — 程序的 AI 接口层 (HTTP)
启动命令: python server.py

v0.2 新增：
- POST /api/v2/chat  AI 对话端点（外部 AI 用自然语言交流）
- GET  /api/v2/capability  能力声明
- v0.1 所有 API 保持兼容
"""

import sys
import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from store.memory_store import init_db
from api.routes import router as v1_router
from __init__ import Yingji

app = FastAPI(
    title="映记 · 程序的 AI 接口层",
    description="Yìngjì — AI Interface Layer for Programs",
    version="0.2.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# v0.1 兼容路由
app.include_router(v1_router)

# v0.2 新路由
_yj = Yingji()


class ChatRequest(BaseModel):
    message: str


@app.post("/api/v2/chat")
def api_v2_chat(req: ChatRequest):
    """
    [v0.2] AI 对话端点
    外部 AI 通过自然语言与映记交流。
    映记会理解意图、执行操作、返回自然语言回复。
    """
    reply = _yj.chat(req.message)
    return {"reply": reply, "agent": "映记"}


@app.get("/api/v2/capability")
def api_v2_capability():
    """
    [v0.2] 能力声明
    返回映记能做什么、不能做什么。
    """
    cap = _yj.capability()
    return cap


@app.on_event("startup")
def startup():
    """启动时初始化数据库"""
    init_db()
    print(f"\n{'='*50}")
    print(f"  映记 v0.2.0 — 程序的 AI 接口层")
    print(f"  v0.1 API: http://127.0.0.1:8712/api/v1")
    print(f"  v0.2 AI 对话: POST http://127.0.0.1:8712/api/v2/chat")
    print(f"  v0.2 能力声明: GET http://127.0.0.1:8712/api/v2/capability")
    print(f"  文档: http://127.0.0.1:8712/docs")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="127.0.0.1",
        port=8712,
        reload=True,
        log_level="info",
    )
