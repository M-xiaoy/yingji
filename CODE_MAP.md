# 映记 v0.2 代码理解（完整记录）

> 记录时间：2026-06-30 20:15
> 用途：小云对映记代码库的全部理解，用于后续讨论和开发
> 路径：`workspace/映记/`

---

## 一、目录结构

```
映记/
├── __init__.py          # 入口：Yingji 主类
├── _chat.py             # AI 对话层：意图理解 + 回复生成（LLM）
├── _capability.py       # 能力声明：自我介绍 + 动态 Service 扫描
├── _gate.py             # 🆕 安全门：三道代码关卡（v0.3 新增）
├── capabilities.py      # 🆕 操作注册中心：intent 白名单管理（v0.3 新增）
├── config.py            # 全局配置
├── models.py            # Pydantic 数据模型（API 输入输出）
├── server.py            # FastAPI HTTP 服务入口
├── use.py               # 快速调用入口（小云专用，HTTP 调 v0.1 API）
│
├── services/
│   └── memory_service.py  # MemoryService（v0.2 新增，但当前 Yingji 未集成）
│
├── engine/
│   ├── retriever.py       # 混合检索 v3：向量+BM25+RRF+Cross-encoder重排
│   ├── reranker.py        # Cross-encoder 重排器（bge-reranker-v2-m3）
│   ├── extractor.py       # 规则版记忆提取（关键词分类）
│   ├── llm_extractor.py   # LLM 增强记忆提取（DeepSeek API）
│   ├── phrase_detector.py # 动态词组检测（自动组词）
│   ├── compactor.py       # 记忆压缩（去重/降冷）
│   └── forgetting.py      # 遗忘调度（热→温→冷衰减）
│
├── store/
│   ├── abc.py             # MemoryBackend 抽象接口
│   ├── default_backend.py # 默认后端（封装 memory_store）
│   └── memory_store.py    # SQLite + ChromaDB 双引擎持久化层
│
├── api/
│   └── routes.py          # v0.1 REST API 路由（FastAPI）
│
└── data/                  # 运行时数据
    ├── yingji.db          # SQLite（元数据 + FTS5 全文索引）
    └── chroma/            # ChromaDB 向量存储
```

---

## 二、核心数据流

### 2.1 调用链路（v0.2 原始）

```
Yingji.chat("帮我查实习")
  → _chat.py: process_chat()
     → _parse_intent() → LLM 意图理解（2-10s）
     → 安全检查（确认/拒绝）
     → _default_router() → engine/store
     → _generate_response() → LLM 回复生成
  → 返回字符串
```

### 2.2 调用链路（v0.3 改造后）

```
Yingji.chat({"type":"request", "intent":"recall", ...})
  → clip_context()  ← 先裁剪，防止层级0被稀释
  → validate_request()   ← 关卡1：协议校验
  → check_intent()       ← 关卡2：intent 白名单
  → check_security()     ← 关卡3：安全等级检查
  → _engine_router()     ← 直接路由，不走 LLM
  → 返回结构化 dict
```

### 2.3 两种模式共存

| 模式 | 输入类型 | 经过 LLM | 经过 Gate | 速度 | 安全性 |
|------|---------|---------|----------|------|-------|
| 协议模式 | dict | ❌ 不经过 | ✅ 三道关卡 | 快（无 LLM） | 高 |
| 兼容模式 | str | ✅ 走 LLM | ❌ 不经过 | 慢（2-10s） | 中 |

---

## 三、模块详解

### 3.1 `__init__.py` — Yingji 主类

**关键字段：**
- `self.name` — AI 名称（来自 config.AI_NAME = "映记"）
- `self._engine_router` — 意图路由函数（默认 `_default_router`）
- `self._context` — 多轮对话上下文（dict，维护 last_input/intent/params/data/reply/turns）
- `self._max_context_turns` — 最大轮数（默认 10）

**关键方法：**

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `chat()` | `message: str \| dict` | `dict` | 核心入口，两种模式 |
| `chat_text()` | `message: str` | `str` | 纯文本快捷方式 |
| `capability()` | `text_mode: bool` | `dict \| str` | 能力声明 |
| `_all_operations()` | — | `dict` | 收集所有 intent 白名单 |
| `_default_router()` | `intent, params` | `dict` | 默认路由（memory CRUD） |
| `recall/remember/search/list/delete` | — | — | 兼容 v0.1 的直接调用 |

**`chat()` 返回格式（v0.3）：**
```python
{
    "reply": "自然语言回复",
    "status": "success | error | need_info | need_confirmation",
    "error_code": "仅 error 时存在",
    "intent": "匹配的操作名",
    "data": "结构化执行结果",
}
```

### 3.2 `_chat.py` — AI 对话层

**两段式设计：**
1. **意图理解** — 把自然语言转为结构化 intent（LLM 调用，低温度 0.1）
2. **回复生成** — 把执行结果转为自然语言回复（LLM 调用，中温度 0.5）

**`_ModelClient` 类：**
- 三模式：`ollama` / `deepseek` / `auto`（优先 ollama，不可用则 deepseek）
- Ollama 调用：`POST {OLLAMA_BASE_URL}/api/chat`，模型 `qwen2.5:7b`
- DeepSeek 调用：`openai.ChatCompletion`，模型 `deepseek-chat`
- 意图理解用 Ollama（本地快）— 但我观察到实际上它是 auto 模式，优先 ollama
- ⚠️ 安全风险：_chat.py 的意图理解 LLM 没有任何保护提示词，容易被带偏

**`process_chat()` 流程：**
```
1. _parse_intent() → LLM 解析 → {intent, params, confidence}
2. confidence < 0.3 → 直接当闲聊
3. _needs_confirmation() + _confirm() → 安全检查
4. engine_router(intent, params) → 执行
5. _generate_response() → LLM 包装成自然语言
6. 返回 dict {reply, intent, confidence, data, ...}
```

**多轮上下文：**
- `_build_intent_prompt()` 会注入上一轮的信息（last_intent/last_params/last_data）
- 支持指代理解（"删掉第一个" → 引用上一轮的检索结果）

### 3.3 `_gate.py` — 安全门（v0.3 新增）

**三个导出函数 + 一个异常：**

```python
def validate_request(msg: dict) -> None
    # 关卡1：校验 JSON 格式、type、必填字段、字段类型
    # 不通过 → raise GateBlocked

def check_intent(intent: str, operations: dict) -> None
    # 关卡2：校验 intent 是否在白名单
    # 不通过 → raise GateBlocked

def check_security(intent, params, operations) -> dict
    # 关卡3：检查安全等级
    # 返回 {"approved": True/False, "reason": "...", "level": 1/2/3}

def clip_context(context, max_turns=10, keep_system=None) -> dict
    # 上下文裁剪：保留头尾，剪中间
    # keep_system = ["last_input", "last_intent", ...]
```

**`GateBlocked` 异常字段：**
- `error_code`: 错误码（`invalid_format` / `intent_unknown` / ...）
- `detail`: 详细信息
- `recoverable`: 是否可恢复
- `recovery_hint`: 恢复建议

**上下文裁剪策略：**
- 轮次不超过上限 → 原样返回
- 超过上限 → 只保留最近 N 轮 + 系统级字段（last_* 系列）

### 3.4 `capabilities.py` — 操作注册中心（v0.3 新增）

**注册函数：**
```python
def register(name, description, security_level=1,
             requires_confirmation=False, parameters=None, handler=None)
```

**查询函数：**
```python
def get_operations() -> dict  # 返回注册表快照（供 gate 使用）
def get_handler(intent) -> callable  # 获取处理函数
```

**默认注册了 4 个操作：**

| intent | 安全等级 | 需确认 | handler |
|--------|---------|--------|---------|
| `recall` | L1 读取 | ❌ | `_handler_recall` |
| `store` | L2 写入 | ✅ 需确认 | `_handler_store` |
| `list` | L1 读取 | ❌ | `_handler_list` |
| `delete` | L3 删除 | ✅ 需确认 | `_handler_delete` |

**注册格式：** 每个操作有完整的参数 Schema（type/required/default），定义级。

### 3.5 `_capability.py` — 能力声明

**两个导出函数：**
```python
def discover(services=None) -> dict     # 结构化能力声明
def describe(services=None) -> str      # 纯文本版（给 chat() 用）
```

**能力声明结构：**
```python
{
    "name": "映记",
    "version": "0.2.0",
    "description": "...",
    "services": {
        "memory": {
            "description": "...",
            "operations": { recall/store/list/delete 的操作 Schema }
        }
    },
    "limitations": ["不执行代码", "不访问外部网络", ...],
    "security": { read_level: 1, write_level: 2, delete_level: 3 }
}
```

**两种模式：**
- 无 services 参数 → v1 静态声明（硬编码 memory 操作）
- 有 services 列表 → v2 动态扫描已注册的 Service

### 3.6 `config.py` — 全局配置

**路径相关：**
```
BASE_DIR          → 映记目录
DATA_DIR          → ./data/
SQLITE_PATH       → ./data/yingji.db
CHROMA_PERSIST_DIR → ./data/chroma/
```

**模型相关：**
```
OLLAMA_BASE_URL   → http://127.0.0.1:11434
EMBED_MODEL       → nomic-embed-text:latest
CHAT_MODEL        → "auto"（优先 ollama, 不可用 deepseek）
CHAT_OLLAMA_MODEL → qwen2.5:7b
CHAT_DEEPSEEK_MODEL → deepseek-chat
AI_NAME           → "映记"
```

**检索相关：**
```
TOP_K_DEFAULT     → 10
TOP_K_MAX         → 50
RECALL_TOP_K      → 5
```

**记忆分层阈值：**
```
IMPORTANCE_THRESHOLD_LOW  → 0.2
IMPORTANCE_THRESHOLD_MED  → 0.5
IMPORTANCE_THRESHOLD_HIGH → 0.8
```

**遗忘调度天数：**
```
FORGET_HOT_DAYS   → 7  天
FORGET_WARM_DAYS  → 30 天
FORGET_COLD_DAYS  → 90 天
```

**服务器：**
```
SERVER_HOST       → 127.0.0.1
SERVER_PORT       → 8712
```

**允许的记忆类型：**
```
MEMORY_TYPES = ["fact", "preference", "decision", "topic", "question", "insight"]
```

**安全等级：**
```
SECURITY_LEVEL_READ   → 1  # 直接放行
SECURITY_LEVEL_WRITE  → 2  # 需确认
SECURITY_LEVEL_DELETE → 3  # 双重确认
```

### 3.7 `store/memory_store.py` — 持久化层

**双引擎架构：**
```
           ┌─────────────┐
           │  SQLite     │ ← 元数据、关系、FTS5 全文索引
           │  (yingji.db)│
           └──────┬──────┘
                  │
           ┌──────▼──────┐
           │  ChromaDB   │ ← 向量存储（语义检索）
           │  (chroma/)  │
           └─────────────┘
```

**数据库表结构（10 张表）：**

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `conversations` | 对话会话 | id, client, title, turn_count, created_at |
| `messages` | 消息历史 | id, conversation_id, role, content |
| `memories` | 记忆存储 | id, content, memory_type, importance, access_count |
| `memory_tiers` | 记忆层级 | memory_id, tier(hot/warm/cold) |
| `memories_fts` | FTS5 全文索引 | content, memory_id |
| `phrases` | 动态词组表 | phrase, length, freq (不在这个文件中，在 phrase_detector.py 中创建) |

**核心函数：**

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `init_db()` | — | — | 初始化所有表 + FTS 重建 |
| `create_memory()` | content, type, importance | memory_id (str) | SQLite + ChromaDB 双写 |
| `get_memory()` | memory_id | dict | 单条查询 |
| `search_memories()` | query, type, limit | list[dict] | 先向量搜索，降级 SQL LIKE |
| `search_bm25()` | query, limit | list[(id, score)] | FTS5 BM25 全文检索 |
| `recall_memories()` | query, top_k | list[dict] | 智能召回（带访问统计更新） |
| `delete_memory()` | memory_id | bool | SQLite + ChromaDB 双删 |

**专有名词保护分词：**
```python
PROTECTED_TERMS = [
    "OpenClaw", "ChromaDB", "ComfyUI", "MusicGen", "Ollama",
    "DeepSeek", "cross-encoder", "bge-reranker", "nomic-embed-text",
    "BM25", "RRF", "FTS5", "IDF", "PMI", "eBPF",
    "映记", "溪流",
    "Agent", "LLM", "RAG", "API", "GPU", "CPU", "VRAM",
]
```

**`_tokenize_for_fts()` 分词流程：**
1. 专有名词保护（替换为规范形式）
2. 清洗非词字符
3. 词组感知分词（调 phrase_detector）
4. 标准化空白 + 小写

### 3.8 `engine/retriever.py` — 混合检索

**检索流程：**
```
1. 向量检索（ChromaDB） → 候选集
2. BM25 全文检索（FTS5） → 候选集
3. RRF 融合（Reciprocal Rank Fusion, k=60）
4. Cross-encoder 重排（bge-reranker-v2-m3, ~568MB）
5. 时间衰减权重（hot=1.0, warm=0.7, cold=0.3）
6. 最终截断 top_k
```

**自适应候选池：**
```python
def _adaptive_candidate_count(top_k):
    total = get_total_memory_count()
    if total < 100:     return total           # 小库全量
    if total < 500:     return max(top_k*4, total*0.5)  # 中库等比
    else:               return max(top_k*4, min(200, total//5))  # 大库硬上限
```

### 3.9 `engine/phrase_detector.py` — 动态词组检测

**机制：**
- 每次写入/检索时扫描文本，统计 2-4 字组共现频率
- 频率 >= 3 次 → 自动加入词组表（持久化到 SQLite `phrases` 表）
- 分词时：词组优先匹配（最长优先），剩余逐字拆分
- 短词组过滤：如果被长词组完全包含，自动排除

**缓存机制：** 词组表加载到 `_phrase_cache`，每 50 次写入后刷新。

### 3.10 `engine/reranker.py` — Cross-encoder 重排

- 模型：`BAAI/bge-reranker-v2-m3`（~568MB，CPU 可跑）
- 全局单例，懒加载
- SSL 补丁（Windows 证书环境兼容）
- 模型路径：先远程下载，失败则尝试本地缓存

### 3.11 `engine/forgetting.py` — 遗忘调度

**三级衰减：**
```
hot  (7天内访问)  →  降 warm 条件：超过7天 + 访问 <10次
warm (30天内)     →  降 cold 条件：超过30天
cold (90天内)     →  标记 archivable：超过90天
```

### 3.12 `services/memory_service.py` — MemoryService

- 继承 `YingjiService` 基类
- 将记忆 CRUD 包装为标准的 YingjiService 格式
- 包含完整的操作 Schema（类型/必填/默认值/枚举约束）
- 包含自然语言示例（帮助 LLM 理解用户怎么说）
- **但当前 `__init__.py` 的 Yingji 类还没有集成 services 注册机制**，走的是 `_default_router` 硬编码

### 3.13 `store/abc.py` — MemoryBackend 抽象接口

```python
class MemoryBackend(ABC):
    def recall(self, query, top_k=3, memory_type=None) -> list[dict]
    def store(self, content, memory_type="fact", importance=0.5,
              metadata=None, conversation_id=None) -> Optional[str]
    def list_memories(self, limit=10, memory_type=None) -> list[dict]
    def delete_memory(self, id) -> bool
    def get_stats(self) -> dict
    def search(self, query, limit=10, memory_type=None) -> list[dict]
```

`NullBackend` — 空后端实现，所有操作返回空。

### 3.14 `store/default_backend.py` — 默认后端

包装 `memory_store.py` + `engine/retriever.py`，直接内存调用（不走 HTTP）。
修复了 v0.1 内嵌模式下的 HTTP 自调用循环问题。

### 3.15 `server.py` — HTTP 服务

- FastAPI + uvicorn
- CORS 全开
- v0.1 路由：`/api/v1/`（CRUD + 召回 + 搜索 + 对话管理 + 遗忘调度 + 统计）
- v0.2 路由：`/api/v2/chat`（AI 对话端点）+ `/api/v2/capability`（能力声明）
- 启动时自动初始化数据库

**当前 `server.py` 使用的是全局单例 Yingji 实例，未集成 v0.3 的 gate 和 capabilities 注册。**

### 3.16 `api/routes.py` — v0.1 REST API

完整端点列表：

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/remember` | LLM 增强记忆提取 |
| POST | `/api/v1/memories` | 创建记忆 |
| GET | `/api/v1/memories/{id}` | 获取单条记忆 |
| DELETE | `/api/v1/memories/{id}` | 删除记忆 |
| GET | `/api/v1/memories` | 搜索/列出记忆 |
| POST | `/api/v1/recall` | 智能召回 |
| POST | `/api/v1/search` | 语义搜索 |
| POST | `/api/v1/conversations` | 保存对话 + 提取记忆 |
| GET | `/api/v1/conversations` | 最近对话列表 |
| GET | `/api/v1/conversations/{id}` | 对话详情 |
| POST | `/api/v1/context-inject` | 上下文注入 |
| POST | `/api/v1/forgetting/run` | 手动遗忘调度 |
| GET | `/api/v1/forgetting/health` | 记忆健康报告 |
| GET | `/api/v1/stats` | 系统统计 |

### 3.17 `use.py` — 快速调用入口

- 小云专用，通过 HTTP 调 v0.1 API
- 三个函数：`recall()` / `remember()` / `remember_turn()` / `format_memories()`
- ⚠️ 依赖 `server.py` 运行在 `127.0.0.1:8712`

### 3.18 `models.py` — Pydantic 模型

14 个数据模型：
- `MemoryCreate/Response/ListResponse` — 记忆操作
- `ConversationCreate/Response` — 对话操作
- `RecallRequest/Response` — 检索操作
- `SearchRequest/Response` — 搜索操作
- `ContextInjectRequest/Response` — 上下文注入
- `StatsResponse` — 统计
- `RememberRequest` — 记忆提取请求

---

## 四、关键依赖

| 依赖 | 用途 | 版本要求 |
|------|------|---------|
| fastapi | HTTP 服务框架 | any |
| uvicorn | ASGI 服务器 | any |
| pydantic | 数据模型 | v2 |
| chromadb | 向量存储 | any |
| requests | HTTP 客户端 | any |
| openai | DeepSeek API 调用 | any |
| sentence-transformers | Cross-encoder 重排 | 需要 bge-reranker-v2-m3 |
| sqlite3 | 内置 | Python stdlib |

**本地模型（Ollama）：**
- `nomic-embed-text:latest` — 向量嵌入
- `qwen2.5:7b` — 意图理解 + 回复生成

**云端 API：**
- `DeepSeek Chat` — 意图理解 + 回复生成（ollama 不可用时兜底）
- `DeepSeek API` — LLM 增强记忆提取（`engine/llm_extractor.py`）
  - API Key 来源：openclaw.json > 环境变量 `DEEPSEEK_API_KEY`
  - API Base：openclaw.json > 默认 `https://api.deepseek.com`
  - 模型：`deepseek-v4-flash`

---

## 五、不确定/模糊点

1. **Desktop 和 workspace 的同步状态** — workspace/映记 和 Desktop/yingji 看起来是两份，但记录上说过已同步。当前 workspace 版本缺少 `service.py`（YingjiService 基类），不确定要不要从 Desktop 同步过来。

2. **`_chat.py` 的模型选择在实际运行时** — config 里 `CHAT_MODEL="auto"`，逻辑是优先 ollama。但如果 ollama 没运行，实际会切 deepseek。当前我没测试 ollama 是否在运行。

3. **`server.py` 的集成状态** — server.py 创建了自己的 `_yj = Yingji()` 全局实例，没有用 `get_default()`。而且 server.py 在 workspace 里有吗？

4. **chroma 集合的实际大小** — DB 显示有 memory 数据（32+ 条），但 chroma 集合的实际向量数量我还没查。

5. **Cross-encoder 模型是否本地已缓存** — `engine/reranker.py` 尝试加载 bge-reranker-v2-m3，但我不确定是否已成功下载缓存。

6. **`services/memory_service.py` 当前没有被任何地方导入** — `__init__.py` 的 `_default_router` 是硬编码的，不是通过 Service 注册。这意味着 `YingjiService` 的扩展机制虽然定义了，但实际没人用。

---

## 六、遗留问题

| 问题 | 影响 | 优先级 |
|------|------|--------|
| `_chat.py` 的 LLM 意图理解无保护提示词 | 容易被带偏 | 🔴 高（已用 _gate.py 部分解决） |
| `memory_store.py` 写操作无并发锁 | 多用户写入会崩 | 🔴 高 |
| server.py 未集成 gate | HTTP 走的还是旧路径 | 🟡 中 |
| `services/memory_service.py` 和 `_default_router` 重复 | 两套逻辑维护两套 | 🟡 中 |
| use.py 依赖本地 HTTP 服务 | 内嵌模式不可用 | 🟢 低 |
| 无单元测试 | 改代码全靠手动验证 | 🟢 低 |

---

_以上为 2026-06-30 对映记 v0.2/v0.3 代码的完整理解记录_
