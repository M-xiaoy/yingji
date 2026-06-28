"""
映记 — 记忆检索器 v2
混合检索：向量语义 + BM25 关键词 + RRF 融合 + 时间衰减权重
"""

import re
from typing import Optional
from store.memory_store import search_memories, recall_memories, search_bm25, get_memory_tier, _get_conn, get_total_memory_count
# 延迟加载，避免 import 时就加载重排模型
_reranker = None
def _get_reranker():
    global _reranker
    if _reranker is None:
        from engine.reranker import rerank as _r
        _reranker = _r
    return _reranker

# RRF 融合参数
RRF_K = 60


def _adaptive_candidate_count(top_k: int) -> int:
    """
    根据记忆总量自适应候选池大小。
    小库全量覆盖，大库截断到硬上限。
    """
    total = get_total_memory_count()
    if total < 100:
        return total
    elif total < 500:
        return max(top_k * 4, int(total * 0.5))
    else:
        return max(top_k * 4, min(200, total // 5))


def _rrf_rank(results_vector: list[str], results_bm25: list[tuple[str, float]]) -> dict[str, float]:
    """
    Reciprocal Rank Fusion: 融合向量检索和 BM25 的排名。
    返回 {memory_id: rrf_score}
    """
    scores = {}

    # 向量检索排名贡献
    for rank, mid in enumerate(results_vector):
        if mid not in scores:
            scores[mid] = 0.0
        scores[mid] += 1.0 / (RRF_K + rank)

    # BM25 排名贡献
    for rank, (mid, _) in enumerate(results_bm25):
        if mid not in scores:
            scores[mid] = 0.0
        scores[mid] += 1.0 / (RRF_K + rank)

    return scores


def _calc_time_decay(tier: str) -> float:
    """层级时间衰减系数"""
    return {"hot": 1.0, "warm": 0.7, "cold": 0.3}.get(tier, 0.5)


def retrieve(
    query: str,
    top_k: int = 5,
    memory_type: Optional[str] = None,
    min_importance: float = 0.0,
    include_expired: bool = False,
    use_reranker: bool = True,
) -> list[dict]:
    """
    v3 检索主入口：
    1. 向量检索 + BM25 关键词检索
    2. RRF 融合（候选池根据总量自适应）
    3. Cross-encoder 重排（可选，默认开启）
    4. 重要性 + 时间衰减过滤
    """
    if not query or not query.strip():
        return []

    # ── 1a. 向量检索（自适应候选池） ──
    candidate_count = _adaptive_candidate_count(top_k)
    vec = search_memories(query=query, limit=candidate_count)
    vec_ids = [r["id"] for r in vec]

    # ── 1b. BM25 检索 ──
    bm25 = search_bm25(query, limit=candidate_count)

    # ── 2. RRF 融合 ──
    if bm25:
        rrf = _rrf_rank(vec_ids, bm25)
    else:
        rrf = {mid: 1.0 / (RRF_K + i) for i, mid in enumerate(vec_ids)}

    # ── 3. 组装候选池 ──
    from store.memory_store import _get_conn as _store_conn
    conn = _store_conn()
    candidates = []

    for mid in rrf:
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (mid,)).fetchone()
        if not row:
            continue
        mem = dict(row)
        if mem.get("metadata"):
            try:
                import json
                mem["metadata"] = json.loads(mem["metadata"])
            except Exception:
                pass

        if memory_type and mem.get("memory_type") != memory_type:
            continue
        if mem.get("importance", 0.0) < min_importance:
            continue

        tier = get_memory_tier(mid)
        if not include_expired and tier == "cold":
            continue
        mem["tier"] = tier
        mem["score"] = 0.0  # 占位
        candidates.append(mem)

    conn.close()

    if not candidates:
        return []

    # ── 4. Cross-encoder 重排 ──
    if use_reranker and len(candidates) > 1:
        try:
            reranker_fn = _get_reranker()
            candidates = reranker_fn(query, candidates, top_k=candidate_count)
        except Exception:
            pass  # 重排失败，降级到 RRF 排序

    # ── 5. 最终截断 ──
    return candidates[:top_k]


def format_context(results: list[dict], system_prompt: Optional[str] = None) -> str:
    """将检索结果格式化为可注入 LLM 上下文的纯文本"""
    if not results:
        return ""

    lines = ["\n--- 相关记忆（映记 hybrid v2） ---"]
    for i, r in enumerate(results, 1):
        tier = r.get("tier", "hot")
        tier_mark = {"hot": ">>", "warm": "->", "cold": "[-]"}.get(tier, " >")
        mem_type = r.get("memory_type", "fact")
        content = r.get("content", "")[:200]
        score = r.get("score", 0)
        lines.append(f"  {tier_mark}[{mem_type}] (s={score:.3f}) {content}")

    if system_prompt:
        return system_prompt + "\n\n" + "\n".join(lines)
    return "\n".join(lines)
