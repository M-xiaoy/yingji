"""
映记 — 动态词组检测（自动组词合并）

策略：
1. 每次写入/检索时扫描文本，统计相邻字组出现频率
2. 频率超过阈值 → 自动加入词组表
3. 分词时：单字与词组双通道共存，互不干扰

核心逻辑：
- 2~4 字滑动窗口统计共现
- 词组表持久化到 SQLite
- 新写入触发增量更新，不需要批量重扫
"""

import re
import sqlite3
import json
from typing import Optional

from config import SQLITE_PATH


# ─── 阈值 ───
PHRASE_MIN_FREQ = 3       # 出现几次才认为是词组
PHRASE_MIN_LEN = 2         # 最短词组字数
PHRASE_MAX_LEN = 4         # 最长词组字数
CLEANUP_INTERVAL = 50      # 每多少次写入触发一次清理


# ══════════════════════════════════════════════════════════════
# 持久化
# ══════════════════════════════════════════════════════════════

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_phrase_table():
    """初始化词组表（幂等）"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS phrases (
            phrase TEXT PRIMARY KEY,
            length INTEGER NOT NULL,
            freq INTEGER NOT NULL DEFAULT 1,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_phrases_len ON phrases(length);
    """)
    conn.commit()
    conn.close()


def _now() -> str:
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


# ══════════════════════════════════════════════════════════════
# 词组发现
# ══════════════════════════════════════════════════════════════

def _extract_chinese_chars(text: str) -> str:
    """只保留中文字符"""
    return re.sub(r'[^\u4e00-\u9fff\u3400-\u4dbf]', '', text)


def _ngrams(chars: str, n: int) -> list[str]:
    """提取所有长度为 n 的连续字组"""
    if len(chars) < n:
        return []
    return [chars[i:i+n] for i in range(len(chars) - n + 1)]


def _update_phrases_from_text(text: str):
    """
    扫描文本中的中文部分，更新词组频率表。
    只统计 2~4 字组，频率超出阈值的自动保留。
    """
    chars = _extract_chinese_chars(text)
    if len(chars) < PHRASE_MIN_LEN:
        return

    now = _now()
    conn = _get_conn()
    seen = set()  # 去重：同一段文本内同词组只计一次

    for n in range(PHRASE_MIN_LEN, min(PHRASE_MAX_LEN, len(chars)) + 1):
        for gram in _ngrams(chars, n):
            if gram in seen:
                continue
            seen.add(gram)

            row = conn.execute(
                "SELECT freq FROM phrases WHERE phrase = ?", (gram,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE phrases SET freq = freq + 1, last_seen = ? WHERE phrase = ?",
                    (now, gram),
                )
            else:
                conn.execute(
                    "INSERT INTO phrases (phrase, length, freq, first_seen, last_seen) VALUES (?, ?, 1, ?, ?)",
                    (gram, n, now, now),
                )

    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════
# 词组查询
# ══════════════════════════════════════════════════════════════

def get_known_phrases() -> set[str]:
    """
    返回所有频率达标且活跃的词组。
    按长度降序排列，长词组优先（避免短词组干扰长词组匹配）。
    过滤被其他词组完全包含的短词组。
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT phrase FROM phrases WHERE freq >= ? ORDER BY length DESC, freq DESC",
        (PHRASE_MIN_FREQ,),
    ).fetchall()
    conn.close()

    all_phrases = [r["phrase"] for r in rows]

    # 过滤：如果一个短词组被长词组完全包含，且长词组词频不更低，则去掉短的
    # 例如「流水线」包含「流水」和「水线」→ 去掉后两者
    filtered = []
    for p in all_phrases:
        # 检查 p 是否被某个更长的词组包含
        contained = False
        for longer in all_phrases:
            if len(longer) > len(p) and p in longer:
                contained = True
                break
        if not contained:
            filtered.append(p)

    return set(filtered)


# ══════════════════════════════════════════════════════════════
# 分词：单字 + 词组双通道
# ══════════════════════════════════════════════════════════════

_phrase_cache: set[str] | None = None
_write_counter = 0


def _invalidate_cache():
    """使词组缓存失效（下次分词时重新加载）"""
    global _phrase_cache
    _phrase_cache = None


def _load_phrases() -> set[str]:
    """懒加载词组表"""
    global _phrase_cache
    if _phrase_cache is None:
        _phrase_cache = get_known_phrases()
    return _phrase_cache


def tokenize_with_phrases(text: str) -> str:
    """
    词组分词主入口。
    输入：「映记混合检索流水线开始工作」
    输出：「映记 混合检索 流水线 开 始 工 作」

    规则：
    - 已知词组按最长优先匹配，保留为完整词
    - 剩余中文字逐字拆分
    - 词组和单字互不干扰（同时存在）
    """
    global _write_counter

    # 更新词组统计
    _update_phrases_from_text(text)
    _write_counter += 1
    if _write_counter % CLEANUP_INTERVAL == 0:
        _invalidate_cache()

    phrases = _load_phrases()
    chars = _extract_chinese_chars(text)

    if not chars:
        return text

    # ── 按最长词组优先匹配 ──
    # 先找出所有匹配的词组及其位置
    matches = []  # [(start, end, phrase)]
    for phrase in phrases:
        plen = len(phrase)
        start = 0
        while True:
            pos = chars.find(phrase, start)
            if pos == -1:
                break
            matches.append((pos, pos + plen, phrase))
            start = pos + 1

    # 合并重叠词组（保留最长的）
    if matches:
        matches.sort(key=lambda x: (x[0], -x[1]))
        merged = [matches[0]]
        for m in matches[1:]:
            if m[0] >= merged[-1][1]:
                merged.append(m)
        matches = merged
    else:
        matches = []

    # ── 构建分词结果 ──
    tokens = []
    pos = 0
    match_idx = 0

    while pos < len(chars):
        if match_idx < len(matches) and matches[match_idx][0] == pos:
            # 命中词组
            tokens.append(matches[match_idx][2])
            pos = matches[match_idx][1]
            match_idx += 1
        else:
            # 命中词组之间的间隙 → 逐字拆分
            next_match = matches[match_idx][0] if match_idx < len(matches) else len(chars)
            gap = chars[pos:next_match]
            tokens.extend(list(gap))
            pos = next_match

    return ' '.join(tokens)


# ══════════════════════════════════════════════════════════════
# 词组统计查询
# ══════════════════════════════════════════════════════════════

def get_phrase_stats() -> dict:
    """返回词组统计信息"""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) as c FROM phrases").fetchone()["c"]
    active = conn.execute(
        "SELECT COUNT(*) as c FROM phrases WHERE freq >= ?",
        (PHRASE_MIN_FREQ,),
    ).fetchone()["c"]
    top = conn.execute(
        "SELECT phrase, length, freq FROM phrases WHERE freq >= ? ORDER BY freq DESC LIMIT 20",
        (PHRASE_MIN_FREQ,),
    ).fetchall()
    conn.close()
    return {
        "total_phrases": total,
        "active_phrases": active,
        "threshold": PHRASE_MIN_FREQ,
        "top_phrases": [{"phrase": r["phrase"], "len": r["length"], "freq": r["freq"]} for r in top],
    }
