"""
映记 — 交叉编码器重排器
跨编码器（cross-encoder）对 query 和每个候选文档逐对评分，
精度远高于 bi-encoder（向量检索）。

模型: BAAI/bge-reranker-v2-m3 (~568MB, CPU 可跑)
"""

from typing import Optional
import sys, io

# 全局单例，避免重复加载
_model = None


def _patch_ssl():
    """绕过 SSL 验证（Windows 证书环境问题）"""
    import os
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
    
    # patch httpx client (huggingface_hub 使用 httpx)
    try:
        import httpx
        original = httpx.Client.__init__
        def _patched_init(self, *args, **kwargs):
            kwargs['verify'] = False
            return original(self, *args, **kwargs)
        httpx.Client.__init__ = _patched_init
    except Exception:
        pass


def _get_model():
    """懒加载 cross-encoder 模型"""
    global _model
    if _model is None:
        _patch_ssl()
        print("[reranker] 加载 bge-reranker-v2-m3...", file=sys.stderr)
        from sentence_transformers import CrossEncoder
        try:
            _model = CrossEncoder("BAAI/bge-reranker-v2-m3")
        except Exception:
            # 如果远端下载失败，尝试本地缓存
            import os
            cache = os.path.expanduser("~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3")
            if os.path.exists(cache):
                _model = CrossEncoder(cache)
            else:
                raise
        print("[reranker] 模型就绪", file=sys.stderr)
    return _model


def rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """
    对候选记忆列表进行 cross-encoder 重排。

    Args:
        query: 查询文本
        candidates: 候选记忆列表（来自 hybrid 检索）
        top_k: 返回数量

    Returns:
        重排后的记忆列表，包含 score 字段（cross-encoder 分数）
    """
    if not candidates:
        return []

    try:
        model = _get_model()
    except Exception as e:
        # 模型加载失败，返回原结果
        for m in candidates[:top_k]:
            m["score"] = m.get("score", 0.5)
        return candidates[:top_k]

    # 构建 query + document 对
    pairs = [(query, m.get("content", "")) for m in candidates]

    try:
        # 批量评分
        scores = model.predict(pairs)

        # 附加评分
        for m, score in zip(candidates, scores):
            m["score"] = round(float(score), 4)

        # 按评分排序
        candidates.sort(key=lambda m: m.get("score", 0), reverse=True)

    except Exception as e:
        print(f"[reranker] 评分失败: {e}", file=sys.stderr)
        # 失败时保持原顺序

    return candidates[:top_k]
