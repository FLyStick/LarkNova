"""轻量双语分词器，用于 FTS5 全文索引和稀疏 TF-IDF 向量。

中文拆分为字符二元组，因为 SQLite 内置 unicode61 分词器无法稳定匹配
CJK 短语；稀疏向量保留原始 token，FTS 检索文本使用 ASCII 安全编码。
"""

from __future__ import annotations

import re
from collections import Counter

_CJK_CHARS = "\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
_CJK_RUN_RE = re.compile(f"[{_CJK_CHARS}]+")
_ASCII_RUN_RE = re.compile(r"[A-Za-z0-9_./-]+")
_TOKEN_RE = re.compile(f"[{_CJK_CHARS}]+|[A-Za-z0-9_./-]+")

_ENGLISH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
}


def tokenize(text: str) -> list[str]:
    """返回归一化文本快照的可检索 token 列表。"""
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text or ""):
        chunk = match.group(0)
        # 连续中文走二元组切分，其余 ASCII/数字连续段直接规约。
        if _CJK_RUN_RE.fullmatch(chunk):
            tokens.extend(_cjk_tokens(chunk))
        else:
            tokens.extend(_ascii_tokens(chunk))
    return tokens


def token_counts(text: str) -> Counter[str]:
    """统计 token 频次，供稀疏 TF-IDF 向量构建。"""
    return Counter(tokenize(text))


def tokenize_search_text(text: str) -> str:
    """把 token 转成 FTS5 可用的 ASCII 安全检索串。"""
    return " ".join(encode_token(token) for token in tokenize(text))


def encode_token(token: str) -> str:
    """保留 ASCII token 可读性，并将 CJK 二元组编码为十六进制标识。"""
    if token.isascii() and token.isalnum():
        return token.lower()
    return "t" + token.encode("utf-8").hex()


def _cjk_tokens(run: str) -> list[str]:
    """中文按相邻二元组切分；较短的连续段额外保留整词。"""
    lowered = run.lower()
    if len(lowered) == 1:
        return [lowered]
    tokens = [lowered[index : index + 2] for index in range(len(lowered) - 1)]
    if len(lowered) <= 6:
        tokens.append(lowered)
    return tokens


def _ascii_tokens(chunk: str) -> list[str]:
    """英文/数字连续段拆成小写词，并过滤常见停用词。"""
    lowered = chunk.lower()
    if "_" in lowered:
        # 下划线型标识符整体保留，避免被拆碎后无法匹配。
        tokens = [lowered.replace("_", "")]
    else:
        tokens = re.findall(r"[a-z0-9]+", lowered)
    return [token for token in tokens if token not in _ENGLISH_STOPWORDS]
