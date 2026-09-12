"""Field-weighted scoring with constraint penalties and deduplication.

One scorer serves both knowledge services so a card and a manifest item
are ranked by the same rules. Scores are comparable only within a single
query: they mix term idf, field weight and constraint multipliers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .constraints import (
    METRIC_CONFLICTS,
    REGION_SIBLINGS,
    SPECIFIC_REGIONS,
    DocumentConstraints,
    QueryConstraints,
)
from .textnorm import normalize_text

# Per-field multipliers; a title hit says more than a summary hit.
FIELD_WEIGHTS: dict[str, float] = {
    "title": 3.0,
    "keywords": 2.0,
    "tags": 1.6,
    "topic": 1.4,
    "region": 1.2,
    "materials": 0.9,
    "teaching_points": 0.8,
    "summary": 0.6,
    "canonical_answer": 0.6,
}

# Curated fields — a hit here counts as strong evidence even when overall
# coverage of a long natural question is low. teaching_points are prose
# sentences, not curated terms, so they stay out of this set.
STRONG_FIELDS = frozenset({"title", "keywords", "tags", "topic"})

# Multipliers applied when a parsed query constraint meets (or misses) the
# document's own constraint signature.
REGION_MATCH_BONUS = 1.4
YEAR_MATCH_BONUS = 1.5
METRIC_MATCH_BONUS = 1.3
METRIC_CONFLICT_PENALTY = 0.4
MATERIAL_MATCH_BONUS = 1.2

# Region handling is strict: a query pinned to 上海/全国/全球 must not be
# answered by documents bound to a sibling region, the same way years are.
REGION_CONFLICT_EXCLUDE = True

# Year handling is deliberately strict: a time-bound document (it carries
# its own statistical year) must never answer a question about a different
# year. Documents about statistics that carry no year at all are heavily
# discounted under an explicit-year query, not returned as equals.
YEAR_CONFLICT_EXCLUDE = True
YEAR_UNLABELED_STAT_TOPIC = 0.2
YEAR_UNLABELED_OTHER = 0.5

# Topics whose documents are time-bound statements even without a year.
TIME_BOUND_TOPICS = frozenset(
    {"population_census", "population_distribution", "population_migration", "urbanization"}
)

# Evidence guard: a question may carry content words the corpus cannot
# answer (股票/房价/航运…). When the weight of matched evidence is small
# relative to those unmatched content words, the honest answer is "no
# match", even though the matched fragment alone looks strong.
GUARD_RATIO = 0.45
GUARD_RATIO_STRONG = 0.40
GUARD_STRONG_MIN_IDF = 3.5
GUARD_STRONG_MIN_LEN = 4
# single term, prose-only hit
GUARD_WEAK_SINGLE = 0.65
# document whose matched terms live only in prose fields
WEAK_ONLY_DISCOUNT = 0.5

# Evidence floors: below either one, a hit is treated as "no solid match"
# instead of being returned as a Top-N answer. A strong-field hit (title,
# keywords, tags, topic, teaching points) earns a lower coverage floor,
# which keeps long natural questions from being killed by function-word
# bigrams in the denominator.
MIN_ABSOLUTE_SCORE = 1.0
MIN_COVERAGE = 0.34
MIN_COVERAGE_STRONG = 0.15

# Near-duplicate titles merge (keep the higher score) when the canonical
# answers also agree. Char bigram Jaccard keeps this cheap and
# script-agnostic. Different statistical years never merge — 五普/六普
# titles read alike but are different documents.
DEDUP_JACCARD = 0.6


@dataclass
class ScoredDoc:
    """Internal scoring record for one document."""

    doc_id: str
    score: float
    coverage: float
    matched_fields: dict[str, list[str]] = field(default_factory=dict)
    constraint_notes: list[str] = field(default_factory=list)


def char_bigrams(text: str) -> set[str]:
    normalized = normalize_text(text)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[i : i + 2] for i in range(len(normalized) - 1)}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    return intersection / (len(left) + len(right) - intersection)


def constraint_multiplier(query: QueryConstraints, doc: DocumentConstraints) -> tuple[float, list[str]] | None:
    """Combine region/year/metric/material agreement into one multiplier.

    Returns ``None`` when the document must be excluded outright — currently
    a time-bound document queried under a different explicit year.
    """
    multiplier = 1.0
    notes: list[str] = []

    if query.regions and doc.region in SPECIFIC_REGIONS:
        if doc.region in query.regions:
            multiplier *= REGION_MATCH_BONUS
            notes.append(f"region:{doc.region}")
        elif REGION_CONFLICT_EXCLUDE:
            # 问句明确提到了区域（上海和全国的“全国”也算），而资料绑定在
            # 另一个具体区域上：排除。问句未提区域时不做排除。
            return None

    if query.years and doc.years:
        if set(query.years) & set(doc.years):
            multiplier *= YEAR_MATCH_BONUS
            notes.append(f"year:{doc.years[0]}")
        elif set(query.years) & set(doc.mentioned_years):
            # 资料正文/出处提到过该年份（发布年、对照年）：中立保留，
            # 不奖励也不排除。
            notes.append("year_mentioned")
        elif any(min(query.years) <= year <= max(query.years) for year in doc.years):
            # 对比类问句（五普到七普）：中间年份属于问句区间，不奖励也不排除
            notes.append("year_in_range")
        elif YEAR_CONFLICT_EXCLUDE:
            return None
    elif query.years and not doc.years:
        if doc.topic in TIME_BOUND_TOPICS:
            multiplier *= YEAR_UNLABELED_STAT_TOPIC
            notes.append("year_unlabeled_stat")
        else:
            multiplier *= YEAR_UNLABELED_OTHER
            notes.append("year_unlabeled")

    if query.metrics and doc.metrics:
        if set(query.metrics) & set(doc.metrics):
            multiplier *= METRIC_MATCH_BONUS
            notes.append(f"metric:{doc.metrics[0]}")
        elif _metric_conflict(query.metrics, doc.metrics):
            multiplier *= METRIC_CONFLICT_PENALTY
            notes.append(f"metric_conflict:{doc.metrics[0]}")

    if query.material_types and doc.material_types:
        if set(query.material_types) & set(doc.material_types):
            multiplier *= MATERIAL_MATCH_BONUS
            notes.append(f"material:{doc.material_types[0]}")

    return multiplier, notes


def _metric_conflict(query_metrics: tuple[str, ...], doc_metrics: tuple[str, ...]) -> bool:
    for query_metric in query_metrics:
        conflicts = METRIC_CONFLICTS.get(query_metric, frozenset())
        if conflicts & set(doc_metrics):
            return True
    return False


def idf_map(total_docs: int, document_frequency: dict[str, int]) -> dict[str, float]:
    """Smoothed idf; terms in every document get a small but non-zero weight."""
    return {
        term: math.log(1.0 + total_docs / max(1, df))
        for term, df in document_frequency.items()
    }


def dedupe_hits(
    scored: list[ScoredDoc],
    titles: dict[str, str],
    canonicals: dict[str, str],
    years_by_id: dict[str, tuple[int, ...]] | None = None,
) -> list[ScoredDoc]:
    """Drop near-duplicate documents, keeping the first (highest-scored) one.

    A duplicate needs both a near-identical title AND a similar canonical
    answer AND the same statistical identity: the same map in two
    resolutions is one result, but 五普 and 六普 summaries read alike and
    must stay separate — different census years are different documents.
    """
    years_by_id = years_by_id or {}
    kept: list[ScoredDoc] = []
    kept_title_bigrams: list[set[str]] = []
    kept_canonical_bigrams: list[set[str]] = []
    for row in scored:
        row_years = set(years_by_id.get(row.doc_id, ()))
        title_bigrams = char_bigrams(titles.get(row.doc_id, ""))
        canonical_bigrams = char_bigrams(canonicals.get(row.doc_id, ""))
        duplicate = False
        for other, other_title, other_canonical in zip(kept, kept_title_bigrams, kept_canonical_bigrams):
            other_years = set(years_by_id.get(other.doc_id, ()))
            if row_years and other_years and row_years != other_years:
                continue
            if jaccard(title_bigrams, other_title) >= DEDUP_JACCARD and jaccard(
                canonical_bigrams, other_canonical
            ) >= 0.5:
                duplicate = True
                break
        if duplicate:
            continue
        kept.append(row)
        kept_title_bigrams.append(title_bigrams)
        kept_canonical_bigrams.append(canonical_bigrams)
    return kept
