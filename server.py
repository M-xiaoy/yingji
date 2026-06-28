"""
映记 — 本地记忆系统 API 服务
启动命令: python server.py
"""

import sys
import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from store.memory_store import init_db
from api.routes import router

app = FastAPI(
    title="映记 · 本地记忆系统",
    description="Yìngjì — Persistent Memory Layer for AI Applications",
    version="0.1.0",
)

# CORS（允许本地前端访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router)


@app.on_event("startup")
def startup():
    """启动时初始化数据库"""
    init_db()
    print(f"\n{'='*50}")
    print(f"  映记 v0.1.0 — 本地记忆服务")
    print(f"  API: http://127.0.0.1:8712/api/v1")
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
