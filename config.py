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
