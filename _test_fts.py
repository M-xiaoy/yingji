"""
验证 FTS 分词 + BM25 检索
"""
import sys
sys.path.insert(0, '.')

import requests
from store.memory_store import init_db, search_bm25, _tokenize_for_fts

# 1. 检查服务
try:
    r = requests.get('http://127.0.0.1:8712/api/v1/health', timeout=3)
    print(f"服务: {r.json()}")
except Exception:
    print("服务未运行，仅测试分词")

# 2. 重建 FTS 索引
print("\n=== 重建 FTS 索引 ===")
init_db()

# 3. 测试 BM25
print("\n=== BM25 检索测试 ===")
for query in ["DeepSeek", "映记", "向量检索", "cross_encoder", "OpenClaw", "ChromaDB"]:
    results = search_bm25(query, limit=5)
    print(f'\n搜 "{query}": {len(results)} 条')
    for mid, score in results[:3]:
        print(f'  [{mid[:8]}] score={score:.4f}')

# 4. 测试混合检索
print("\n=== 混合检索测试 ===")
from engine.retriever import retrieve

for query in ["DeepSeek", "映记 项目", "系统架构"]:
    results = retrieve(query, top_k=3, use_reranker=False)
    print(f'\n搜 "{query}": {len(results)} 条')
    for r in results:
        content = r["content"][:80]
        print(f'  [{r["tier"]}] (s={r.get("score", 0):.3f}) {content}...')
