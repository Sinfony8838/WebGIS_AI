"""Dictionary-driven Chinese tokenization with bigram fallback.

A real segmentation dictionary is not available offline, so the lexicon is
built from the corpus itself (titles, keywords, tags) plus the alias
tables in :mod:`.constraints`. Known terms win over raw bigrams, which is
what makes ``上海人口密度`` tokenize into ``上海`` + ``人口密度`` instead of
noise windows.
"""

from __future__ import annotations

import re

from .textnorm import normalize_text

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_RE = re.compile(r"[a-z0-9]+")

# Function words that appear in nearly every natural question and must not
# drive scoring. Kept here (not in scoring) so token consumers stay simple.
STOP_TERMS = frozenset(
    {
        "什么", "怎么", "怎样", "如何", "为什么", "为何", "多少", "哪些", "哪里",
        "请问", "请", "告诉我", "介绍", "一下", "一下下", "有关", "关于",
        "可以", "能够", "是不是", "有没有", "属于", "以及", "还有",
        "这个", "那个", "这些", "他们", "我们", "一个", "一种",
        "哪一", "哪年", "一年", "几年", "何时", "今年", "是哪", "哪个",
        "差距", "差异", "比较", "对比", "哪个", "更大", "更高", "更大",
    }
)

# Interrogative/copula/preposition/classifier characters: bigrams containing
# one of them are segmentation fragments of function phrases
# (条什/么线/图在/某个/个小) and carry no retrieval meaning. Applied after
# bigram merging. Deliberately excludes 对 (对比/对策 are real terms).
STOP_CHARS = frozenset("的吗呢吧啊哪怎样是有了呀嘛啦么什在就都个")


def tokenize(text: str, lexicon: frozenset[str] | set[str] | None = None) -> list[str]:
    """Split normalized Chinese/mixed text into retrieval terms.

    ``lexicon`` holds multi-character terms worth preferring (e.g.
    ``人口密度``). Matching is greedy longest-first inside CJK runs; spans
    not covered by the lexicon fall back to character bigrams so unseen
    wording still produces overlap signals.
    """
    normalized = normalize_text(text)
    if not normalized:
        return []
    tokens: list[str] = []
    for chunk in normalized.split(" "):
        if not chunk:
            continue
        tokens.extend(_tokenize_chunk(chunk, lexicon or frozenset()))
    return [token for token in tokens if token]


def _tokenize_chunk(chunk: str, lexicon: frozenset[str] | set[str]) -> list[str]:
    tokens: list[str] = []
    position = 0
    length = len(chunk)
    while position < length:
        latin = _LATIN_RE.match(chunk, position)
        if latin:
            tokens.append(latin.group(0))
            position = latin.end()
            continue
        if not _is_cjk(chunk[position]):
            position += 1
            continue
        cjk_run = _CJK_RE.match(chunk, position).group(0)  # type: ignore[union-attr]
        tokens.extend(_tokenize_cjk_run(cjk_run, lexicon))
        position += len(cjk_run)
    return _drop_stop_char_tokens(tokens)


def _drop_stop_char_tokens(tokens: list[str]) -> list[str]:
    """Drop function-char fragments (``条什``/``么线``) produced by bigram merging."""
    cleaned: list[str] = []
    for token in tokens:
        if len(token) == 1 and token in STOP_CHARS:
            continue
        if len(token) == 2 and (token[0] in STOP_CHARS or token[1] in STOP_CHARS):
            continue
        cleaned.append(token)
    return cleaned


def _tokenize_cjk_run(run: str, lexicon: frozenset[str] | set[str]) -> list[str]:
    max_len = max((len(term) for term in lexicon if len(term) > 1), default=2)
    max_len = min(max_len, 12)
    tokens: list[str] = []
    position = 0
    length = len(run)
    while position < length:
        matched = ""
        for size in range(min(max_len, length - position), 1, -1):
            candidate = run[position : position + size]
            if candidate in lexicon:
                matched = candidate
                break
        if matched:
            tokens.append(matched)
            position += len(matched)
            continue
        # Uncovered span: single char now, bigram merged below.
        tokens.append(run[position])
        position += 1
    return _merge_single_chars(tokens)


def _merge_single_chars(tokens: list[str]) -> list[str]:
    """Collapse runs of leftover single characters into bigrams.

    Keeps one-character output only when a char is truly isolated, so
    scoring gets stable overlap units instead of single-char noise.
    """
    merged: list[str] = []
    buffer: list[str] = []
    for token in tokens:
        if len(token) == 1:
            buffer.append(token)
            continue
        _flush_buffer(buffer, merged)
        merged.append(token)
    _flush_buffer(buffer, merged)
    return merged


def _flush_buffer(buffer: list[str], merged: list[str]) -> None:
    if len(buffer) == 1 and merged:
        merged.append(buffer[0])
    else:
        for index in range(len(buffer) - 1):
            merged.append(buffer[index] + buffer[index + 1])
    buffer.clear()


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"
