"""映记 — LLM 记忆提取测试"""
import requests, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:8712/api/v1"

print("=" * 55)
print("  映记 — LLM 增强记忆提取测试")
print("=" * 55)

# 先清空测试数据（删除旧记忆）
# (keep the old ones, just test the remember endpoint)

# 1. 测试 /remember（LLM 增强模式）
print("\n[1] POST /remember (LLM 增强)...")
r = requests.post(f"{BASE}/remember", json={
    "user_message": "我最近在研究多Agent协作的token优化问题，发现缓存碎片化才是真凶，不是功能调用数。准备用LangGraph重写orchestrator的路由层。",
    "assistant_message": "这个方向有意思！缓存碎片化本质上是scheduling + caching co-optimization问题。LangGraph的状态机架构确实适合处理这种条件分支路由。你准备什么时候开始改？",
    "use_llm": True,
})
result = r.json()
print(f"  提取方式: {result['extraction_method']}")
print(f"  提取记忆数: {result['memories_extracted']}")
for m in result.get("memories", []):
    print(f"  [{m['memory_type']}] (imp={m['importance']}) {m['content'][:70]}...")

# 2. 测试 /remember（规则模式，对比）
print("\n[2] POST /remember (规则版，对比)...")
r = requests.post(f"{BASE}/remember", json={
    "user_message": "我决定用LangGraph替代现有的orchestrator路由层，因为状态机架构更适合多Agent协作的场景。",
    "assistant_message": "好决定。LangGraph的检查点机制也方便你做错误恢复和中间状态回溯。",
    "use_llm": False,
})
result = r.json()
print(f"  提取方式: {result['extraction_method']}")
print(f"  提取记忆数: {result['memories_extracted']}")
for m in result.get("memories", []):
    print(f"  [{m['memory_type']}] (imp={m['importance']}) {m['content'][:70]}...")

# 3. 综合召回
print("\n[3] 综合召回验证...")
r = requests.post(f"{BASE}/recall", json={
    "query": "多Agent token优化",
    "top_k": 5,
})
recall = r.json()
print(f"  召回 {recall['total']} 条记忆:")
for m in recall["results"]:
    preview = m["content"][:80].replace("\n", " ")
    print(f"  [{m['memory_type']}] {preview}..")

# 4. 最终统计
r = requests.get(f"{BASE}/stats")
stats = r.json()
print(f"\n[4] 系统状态: {stats['total_memories']} 条记忆 | {stats['total_conversations']} 个对话")
print(f"  按类型: {stats['memory_by_type']}")

print("\n" + "=" * 55)
print("  [OK] 测试完成")
print("=" * 55)
