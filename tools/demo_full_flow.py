"""
映记 — 记忆工具化 完整流程演示
================================
模拟一次真实对话中，模型如何通过 function calling 自主检索记忆。

流程：
  1. 先存几条记忆（模拟之前的对话）
  2. 模拟新对话开始
  3. 用户消息 → 模型判断需要记忆 → 调 recall → 获取记忆 → 继续对话
"""

import sys, os, io, json, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.recall_tool import (
    RECALL_TOOL_DEFINITION,
    RECALL_SYSTEM_PROMPT,
    execute_recall,
    simple_recall,
    format_memories_for_llm,
)

YINGJI_API = "http://127.0.0.1:8712/api/v1"

print("=" * 60)
print("  映记 · 记忆工具化 — 完整流程演示")
print("=" * 60)


# ══════════════════════════════════════════════════════════════
# 第一步：准备记忆数据（模拟已存在的记忆）
# ══════════════════════════════════════════════════════════════

print("\n[1] 注入示例记忆（模拟之前的对话历史）...")

seeds = [
    {
        "content": "用户决定用LangGraph重写orchestrator的路由层，因为状态机架构更适合多Agent协作中条件分支路由的场景。",
        "memory_type": "decision",
        "importance": 0.85,
        "metadata": {"tags": ["orchestrator", "LangGraph", "architecture"]},
    },
    {
        "content": "用户在做多Agent系统时发现：缓存碎片化是token成本的主要来源，多个子Agent并行导致KV Cache无法复用。",
        "memory_type": "insight",
        "importance": 0.8,
        "metadata": {"tags": ["multi-agent", "token-optimization", "caching"]},
    },
    {
        "content": "用户最近在做映记记忆系统的产品化开发，项目定位是本地优先的通用记忆层API。",
        "memory_type": "project",
        "importance": 0.75,
        "metadata": {"tags": ["yingji", "memory-system"]},
    },
    {
        "content": "用户的实习方向是建筑行业AI应用，打算去了先搞清楚痛点再动手。",
        "memory_type": "fact",
        "importance": 0.7,
        "metadata": {"tags": ["internship", "AI"]},
    },
    {
        "content": "DeepSeek Agent Harness团队招研究员，小刘正在准备投递，作品集已优化完成。",
        "memory_type": "decision",
        "importance": 0.9,
        "metadata": {"tags": ["deepseek", "career"]},
    },
]

for i, seed in enumerate(seeds):
    r = requests.post(f"{YINGJI_API}/memories", json=seed)
    mid = r.json().get("id", "?")[:8]
    print(f"  [{i+1}] {seed['memory_type']} (imp={seed['importance']}) → id={mid}..")


# ══════════════════════════════════════════════════════════════
# 第二步：验证准备完成
# ══════════════════════════════════════════════════════════════

r = requests.get(f"{YINGJI_API}/stats")
stats = r.json()
print(f"\n[2] 准备完成: 共 {stats['total_memories']} 条记忆")


# ══════════════════════════════════════════════════════════════
# 第三步：模拟工具化调用场景
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("  场景模拟：新对话 → 模型自主检索 → 精准回应")
print("=" * 60)

scenarios = [
    {
        "user": "今天我们继续搞那个多Agent的orchestrator吧，我觉得路由层还需要优化",
        "expected_recall": True,
        "note": "用户隐式引用历史项目 → 应触发召回",
    },
    {
        "user": "今天天气不错，你最近怎么样？",
        "expected_recall": False,
        "note": "无关话题 → 不应触发召回",
    },
    {
        "user": "LangGraph的状态机比我现在的路由方案好在哪？上次我们讨论过但我记不太清了",
        "expected_recall": True,
        "note": "用户明确引用历史讨论 → 应触发召回",
    },
    {
        "user": "你觉得我实习第一周应该先做什么？",
        "expected_recall": True,
        "note": "涉及个人背景 → 应触发召回（建筑公司AI）",
    },
]

for i, sc in enumerate(scenarios, 1):
    print(f"\n  ── 场景 {i}: {sc['note']}")
    print(f"  用户: {sc['user']}")
    print(f"  预期触发: {'是' if sc['expected_recall'] else '否'}")

    # 这里模拟模型判断
    # 真实场景中，模型通过 function calling 自主决定调不调
    # 这里我们用 simple_recall 模拟触发结果

    if sc["expected_recall"]:
        results = simple_recall(sc["user"], top_k=2)
        if results:
            print(f"  📡 模型自动触发 recall_memory()")
            print(f"  返回 {len(results)} 条相关记忆:")
            for m in results:
                preview = m["content"][:80]
                print(f"    [{m['memory_type']}] {preview}..")
            print(f"  💡 记忆已注入 → 模型据此生成精准回复")
        else:
            print(f"  未检索到相关记忆")
    else:
        print(f"  模型判断无需检索 → 正常自由对话")


# ══════════════════════════════════════════════════════════════
# 第四步：展示 tool definition（实际发给 LLM 的配置）
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("  Tool Definition — 可复制到任何 DeepSeek 客户端")
print("=" * 60)
print(f"\nTools 配置:\n{json.dumps([RECALL_TOOL_DEFINITION], indent=2, ensure_ascii=False)}")
print(f"\nSystem Prompt 补充:\n{RECALL_SYSTEM_PROMPT}")


# ══════════════════════════════════════════════════════════════
# 第五步：模拟 API 调用流程（含 function calling 往返）
# ══════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("  API 往返模拟 — 完整 function calling 流程")
print("=" * 60)

print("""
Step 1: 用户发送消息 →
  "LangGraph的状态机比我现在的路由方案好在哪？"

Step 2: 客户端调用 DeepSeek API (带 tools=[recall_memory])
  → 模型返回: tool_calls=[{name: "recall_memory", args: {query: "LangGraph 路由层 状态机", top_k: 3}}]

Step 3: 客户端执行 recall (调本地映记 API)
  → POST /api/v1/recall
  → 返回: [决策: 用LangGraph重写路由层, 洞察: 缓存碎片化]

Step 4: 客户端将结果作为 tool_message 送回 DeepSeek API
  → 模型结合记忆生成回复

Step 5: 用户看到回应
  → "上次你是因为缓存碎片化的问题决定用LangGraph的。
     状态机相比现在的方案优势在于……"
""")

print("=" * 60)
print("  [OK] 记忆工具化方案就绪")
print("  集成方式: 复制上方 Tools 配置到 DeepSeek API 调用")
print("=" * 60)
