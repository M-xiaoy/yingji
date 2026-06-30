"""
映记 — 配置管理
"""
import os

# 基础路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 数据库
SQLITE_PATH = os.path.join(DATA_DIR, "yingji.db")

# ChromaDB 存储路径（复用 unified_kb 的数据目录或独立）
CHROMA_PERSIST_DIR = os.path.join(DATA_DIR, "chroma")
COLLECTION_NAME = "yingji_memories"

# Ollama 嵌入
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "nomic-embed-text:latest"

# 检索配置
TOP_K_DEFAULT = 10
TOP_K_MAX = 50
RECALL_TOP_K = 5  # 默认召回数量

# 记忆重要性
IMPORTANCE_THRESHOLD_LOW = 0.2
IMPORTANCE_THRESHOLD_MED = 0.5
IMPORTANCE_THRESHOLD_HIGH = 0.8

# 遗忘调度：天数阈值
FORGET_HOT_DAYS = 7     # 7天内访问 → 热
FORGET_WARM_DAYS = 30   # 30天内访问 → 温
FORGET_COLD_DAYS = 90   # 超过 → 冷（可归档）

# 服务器
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8712

# 记忆类型
MEMORY_TYPES = ["fact", "preference", "decision", "topic", "question", "insight"]

# ─── v0.2 新增：AI 对话层配置 ───

# 程序方 AI 用什么模型做意图理解 + 回复生成
# 可选: "ollama" (纯本地, qwen2.5:7b), "deepseek" (云端 API), "auto" (优先 ollama, 不可用则 deepseek)
CHAT_MODEL = "auto"

# Ollama 模型名（CHAT_MODEL=ollama 时生效）
CHAT_OLLAMA_MODEL = "qwen2.5:7b"

# DeepSeek 模型（CHAT_MODEL=deepseek 时生效）
CHAT_DEEPSEEK_MODEL = "deepseek-chat"

# 程序方 AI 的身份名称（在对话中自我介绍用）
AI_NAME = "映记"

# 程序方 AI 的能力描述（v1 静态声明）
AI_DESCRIPTION = (
    "我是映记，程序的 AI 接口层。"
    "我能访问程序的记忆系统和知识库。"
    "我可以检索存储的信息，也可以记录新的信息。"
    "我不执行代码、不访问网络、不操作文件系统。"
)

# 安全等级
# L1 = 直接放行（读取/检索）
# L2 = 需确认（写入/修改）
# L3 = 双重确认（删除/覆盖）
SECURITY_LEVEL_READ = 1
SECURITY_LEVEL_WRITE = 2
SECURITY_LEVEL_DELETE = 3
