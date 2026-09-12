"""Shared Chinese retrieval building blocks for the knowledge services.

The module keeps the retrieval logic in one place so
``KnowledgeService`` (builtin teaching cards) and
``KnowledgeBaseService`` (manifest-driven knowledge base) stop drifting
apart: identical normalization, tokenization, constraint handling,
scoring, deduplication and "insufficient evidence" thresholds.
"""

from __future__ import annotations

from .constraints import QueryConstraints, extract_constraints
from .engine import RetrievalDoc, RetrievalEngine, RetrievalHit, RetrievalResult
from .textnorm import normalize_text

__all__ = [
    "QueryConstraints",
    "extract_constraints",
    "RetrievalDoc",
    "RetrievalEngine",
    "RetrievalHit",
    "RetrievalResult",
    "normalize_text",
]
