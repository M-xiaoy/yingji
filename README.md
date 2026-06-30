# 映记 (Yìngjì) — AI Interface Layer for Programs

**映记** is an **embeddable AI interface layer** for any program.

**v0.1** — Tool-calling-based persistent memory system. REST API, dual-engine persistence (SQLite + ChromaDB), hybrid retrieval, forgetting scheduler.

**v0.2** — AI-to-AI conversation layer. Programs can now embed 映记 and let external AIs talk to them in natural language.

> **Core philosophy**: Memory should be *available when needed, invisible when not*.  
> No context injection. No pre-filling. The model decides.

---

## Why 映记?

Most "memory" solutions pre-inject context into the system prompt. This has fundamental problems:

| Problem | 映记's approach |
|---------|----------------|
| **Context pollution** — irrelevant memories bias responses | Memory is *never* auto-injected; the model calls `recall()` when it detects relevance |
| **Token waste** — 80% of pre-injected memory is unused | Zero token cost until the model explicitly retrieves |
| **Cognitive reset loss** — pre-filling breaks the "blank slate" of new sessions | New sessions start clean |
| **Cold start** — no history for new topics | No signal, no bias |

映记 packages memory retrieval as a **function calling tool** (`recall_memory`). The LLM decides when and what to recall.

---

## Architecture

```
┌─────────────────────┐      ┌──────────────────────────────┐
│   LLM Client        │      │  映记 Memory Service          │
│  (DeepSeek/OpenAI/  │ ──→  │                              │
│   Custom)           │      │  POST /api/v1/remember       │
│                     │      │  POST /api/v1/recall         │
│  System Prompt:     │      │  POST /api/v1/context-inject │
│    "You have        │      │  POST /api/v1/forgetting/run │
│     recall_memory   │      │                              │
│     tool..."        │      │  SQLite (metadata)           │
│                     │      │  ChromaDB (vectors)          │
│  Function Calling:  │      │  Ollama (embeddings)         │
│    recall_memory →  │      └──────────────────────────────┘
│    POST /recall     │
└─────────────────────┘
```

### Memory Engine

```
Conversation Input → Extractor (LLM/Rules) → SQLite + ChromaDB
                                                        ↓
Tool Call: recall_memory(query) ←── LLM Function Calling
     ↓
Retriever (Vector + Keyword + Importance Weighted)
     ↓
Forgetting Scheduler (Hot → Warm → Cold tier decay)
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) with `nomic-embed-text` model (`ollama pull nomic-embed-text`)
- (Optional) DeepSeek API key for LLM-enhanced memory extraction

### Install & Run

```bash
# 1. Install dependencies
pip install fastapi uvicorn chromadb requests pydantic

# 2. Clone & start
git clone https://github.com/M-xiaoy/yingji.git
cd yingji
python server.py
```

The server starts at `http://127.0.0.1:8712` with interactive docs at `http://127.0.0.1:8712/docs`.

### API Overview

| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/v1/remember` | POST | Extract memories from a conversation turn (LLM-enhanced) |
| `/api/v1/recall` | POST | Retrieve relevant memories by semantic query |
| `/api/v1/search` | POST | Full-text + vector hybrid search |
| `/api/v1/memories` | GET | List/search stored memories |
| `/api/v1/conversations` | POST | Save a conversation & auto-extract memories |
| `/api/v1/context-inject` | POST | Format memories as readable context for LLM |
| `/api/v1/forgetting/run` | POST | Run forgetting cycle (hot→warm→cold tier decay) |
| `/api/v1/forgetting/health` | GET | Memory health report |
| `/api/v1/stats` | GET | System statistics |

### Quick Test

```bash
# Create a memory
curl -X POST http://127.0.0.1:8712/api/v1/memories \
  -H "Content-Type: application/json" \
  -d '{"content": "The user prefers Python over JavaScript for backend work.", "memory_type": "preference", "importance": 0.7}'

# Recall it
curl -X POST http://127.0.0.1:8712/api/v1/recall \
  -H "Content-Type: application/json" \
  -d '{"query": "programming language preference", "top_k": 3}'
```

---

## Integrating with LLMs

### Option 1: Function Calling (recommended)

Add this tool definition to your LLM API call:

```json
{
  "type": "function",
  "function": {
    "name": "recall_memory",
    "description": "Retrieve historical memories relevant to the current conversation topic. Call this when the user references past discussions, projects, decisions, or preferences.",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {"type": "string"},
        "top_k": {"type": "integer", "default": 3}
      },
      "required": ["query"]
    }
  }
}
```

And add this to your system prompt:

> You have a `recall_memory` tool to retrieve historical context. Use it when the user mentions past discussions, decisions, or projects. Call with a relevant query, then incorporate the returned memories naturally.

See [`tools/recall_tool.py`](tools/recall_tool.py) for the complete handler.

### Option 2: Direct API (for custom agents)

```python
from tools.recall_tool import simple_recall, format_memories_for_llm

# Retrieve memories
results = simple_recall("multi-agent token optimization", top_k=3)

# Format as readable context
context = format_memories_for_llm(results)
```

---

## Project Structure

```
yingji/
├── server.py              # FastAPI entry point
├── config.py              # Configuration
├── models.py              # Pydantic schemas
├── requirements.txt       # Dependencies
│
├── store/
│   └── memory_store.py    # SQLite + ChromaDB dual engine
│
├── engine/
│   ├── extractor.py       # Rule-based memory extraction (fallback)
│   ├── llm_extractor.py   # LLM-enhanced extraction (DeepSeek)
│   ├── retriever.py       # Hybrid semantic + keyword retrieval
│   ├── compactor.py       # Memory compression & dedup
│   ├── forgetting.py      # Hot → Warm → Cold lifecycle
│   └── phrase_detector.py # [v0.2] Auto phrase detection & merging
│
├── api/
│   └── routes.py          # REST API routes
│
├── _chat.py               # [v0.2] AI conversation layer
├── _capability.py          # [v0.2] Capability introspection
├── __init__.py             # [v0.2] Yingji main class (embeddable)
│
└── tools/
    ├── recall_tool.py     # Function calling tool definition + handler
    └── demo_full_flow.py  # End-to-end demo
```

---

## Usage (Embedded Mode, v0.2)

```python
from yingji import Yingji

yj = Yingji()

# AI-to-AI conversation
reply = yj.chat("帮我查一下之前讨论过的实习计划")

# Capability introspection
cap = yj.capability()  # structured dict
desc = yj.capability(text_mode=True)  # plain text for LLM prompt
```

## v0.2 API (HTTP Mode)

| Endpoint | Method | What it does |
|----------|--------|-------------|
| `/api/v2/chat` | POST | AI-to-AI natural language conversation |
| `/api/v2/capability` | GET | Program capability introspection |

All v0.1 REST endpoints remain unchanged.

---

## Status

**v0.2.0** — Active development. v0.1 memory system stable; v0.2 conversation layer in prototype.

### v0.1 (stable)
- ✅ REST API with 10+ endpoints
- ✅ LLM-enhanced memory extraction (with rule-based fallback)
- ✅ Hybrid retrieval (vector + BM25 + RRF + Cross-encoder)
- ✅ Forgetting scheduler (tiered memory lifecycle)
- ✅ Function calling tool definition for any LLM
- ✅ Adaptive candidate pool

### v0.2 (new)
- ✅ AI-to-AI conversation layer (chat-based interface)
- ✅ Program capability introspection
- ✅ Embeddable mode (`pip install -e .` → `from yingji import Yingji`)
- ✅ Auto phrase detection & merging (dynamic n-gram → FTS5)
- ⬜ Dynamic service registry (currently static capability)
- ⬜ Security confirmation refinement

---

## License

MIT

---

*From the abyss I gaze, but mostly I just remember what you said.*
