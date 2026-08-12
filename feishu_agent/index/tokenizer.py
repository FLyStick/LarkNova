"""Lightweight bilingual tokenizer used by FTS5 and sparse TF-IDF vectors.

Chinese text is split into character bigrams because SQLite's built-in
unicode61 tokenizer cannot reliably match CJK phrases. Original tokens are
kept for the sparse vectors; FTS search text uses ASCII-safe encoded tokens.
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
    """Return searchable tokens for a normalized text snapshot."""
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text or ""):
        chunk = match.group(0)
        if _CJK_RUN_RE.fullmatch(chunk):
            tokens.extend(_cjk_tokens(chunk))
        else:
            tokens.extend(_ascii_tokens(chunk))
    return tokens


def token_counts(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def tokenize_search_text(text: str) -> str:
    """Convert tokens into an ASCII-safe phrase usable by FTS5."""
    return " ".join(encode_token(token) for token in tokenize(text))


def encode_token(token: str) -> str:
    """Keep ASCII tokens readable and encode CJK bigrams as hex identifiers."""
    if token.isascii() and token.isalnum():
        return token.lower()
    return "t" + token.encode("utf-8").hex()


def _cjk_tokens(run: str) -> list[str]:
    lowered = run.lower()
    if len(lowered) == 1:
        return [lowered]
    tokens = [lowered[index : index + 2] for index in range(len(lowered) - 1)]
    if len(lowered) <= 6:
        tokens.append(lowered)
    return tokens


def _ascii_tokens(chunk: str) -> list[str]:
    lowered = chunk.lower()
    if "_" in lowered:
        tokens = [lowered.replace("_", "")]
    else:
        tokens = re.findall(r"[a-z0-9]+", lowered)
    return [token for token in tokens if token not in _ENGLISH_STOPWORDS]
