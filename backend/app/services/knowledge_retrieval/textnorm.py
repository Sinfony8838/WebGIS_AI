"""Text normalization shared by every knowledge retrieval path.

Chinese classroom queries mix full-width punctuation, Latin words, digits
and units such as ``2020年``. Normalization happens once, here, so
scoring never sees two spellings of the same query.
"""

from __future__ import annotations

import re
import unicodedata

# Punctuation and symbols that carry no retrieval meaning. Kept as a
# replacement map instead of ``isalnum`` filtering so CJK text survives.
_PUNCT_RE = re.compile(
    "["
    "，；：？！、。“”‘’"
    "（）《》—…·｡ｒ"
    ",;:!?()\\[\\]{}<>\"'.…"
    "]"
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Return a lowercase, half-width, punctuation-free version of ``value``.

    ``2020年`` stays ``2020年``; ``ＱＧＩＳ`` becomes ``qgis``; ``人口密度？``
    becomes ``人口密度``. Empty input maps to an empty string.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def digit_runs(text: str) -> list[str]:
    """Return digit runs inside already-normalized text (``2020年`` → ``["2020"]``)."""
    return re.findall(r"\d{2,4}", normalize_text(text))
