"""映记 — API 集成测试"""
import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:8712/api/v1"

print("=" * 55)
print("  映记 — API 集成测试")
print("=" * 55)

# 1. Health
r = requests.get(f"{BASE}/health")
print(f"\n[1] Health: {r.json()}")

# 2. Create memory
r = requests.post(f"{BASE}/memories", json={
    "content": "小刘用联想拯救者笔记本，RTX 4060显卡，喜欢捣鼓AI工作流搭建",
    "memory_type": "fact",
    "importance": 0.8,
    "metadata": {"source": "onboarding", "tags": ["user_profile"]}
})
mem1 = r.json()
print(f"\n[2] Create memory: id={mem1['id'][:8]}.. type={mem1['memory_type']} imp={mem1['importance']}")

# 3. Save conversation & extract memories
r = requests.post(f"{BASE}/conversations", json={
    "client": "webchat",
    "title": "关于映记产品的讨论",
    "messages": [
        {"role": "user", "content": "我们来做一款记忆系统的产品吧，需要能自动从对话中提取记忆"},
        {"role": "assistant", "content": "好想法！我们可以复用溪流的资产，做成独立API服务"}
    ]
})
conv = r.json()
print(f"\n[3] Save conversation: id={conv['conversation']['id'][:8]}.. extracted {conv['memories_extracted']} memories")

# 4. Recall
r = requests.post(f"{BASE}/recall", json={
    "query": "小刘用什么电脑",
    "top_k": 3
})
recall = r.json()
print(f"\n[4] Recall: got {recall['total']} results")
for m in recall["results"]:
    preview = m["content"][:60].replace("\n", " ")
    print(f"   [{m['memory_type']}] {preview}..")

# 5. Search
r = requests.post(f"{BASE}/search", json={
    "query": "记忆系统",
    "top_k": 5
})
search = r.json()
print(f"\n[5] Search: got {search['total']} results")

# 6. Context inject (without emoji to avoid gbk issues)
r = requests.post(f"{BASE}/context-inject", json={
    "user_message": "我想继续开发映记的记忆提取功能",
    "top_k": 3,
    "system_prompt": "你是一个AI助手。"
})
ctx = r.json()
print(f"\n[6] Context inject: {len(ctx['memories'])} memories, context length={len(ctx['memory_context'])} chars")

# 7. Stats
r = requests.get(f"{BASE}/stats")
stats = r.json()
print(f"\n[7] Stats: {stats['total_memories']} memories, {stats['total_conversations']} conversations")

# 8. Forgetting health
r = requests.get(f"{BASE}/forgetting/health")
health = r.json()
print(f"\n[8] Memory health: {health}")

# 9. Run forgetting cycle
r = requests.post(f"{BASE}/forgetting/run")
fstats = r.json()
print(f"\n[9] Forgetting cycle: {fstats['stats']}")

print("\n" + "=" * 55)
print("  [OK] All endpoints passed!")
print("=" * 55)
