"""Retrieval engine tying normalization, tokenization, constraints and scoring together.

The engine is corpus-local: it is constructed from already
permission-filtered documents, so a caller that filters access before
building (or reuses its per-owner cache) can never leak another user's
private item through a shared index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .constraints import (
    CENSUS_YEAR_ALIASES,
    METRIC_ALIASES,
    REGION_ALIASES,
    REGION_CANONICAL_ALIASES,
    DocumentConstraints,
    QueryConstraints,
    extract_constraints,
)
from .scoring import (
    FIELD_WEIGHTS,
    GUARD_RATIO,
    GUARD_RATIO_STRONG,
    GUARD_STRONG_MIN_IDF,
    GUARD_STRONG_MIN_LEN,
    GUARD_WEAK_SINGLE,
    MATERIAL_MATCH_BONUS,
    MIN_ABSOLUTE_SCORE,
    MIN_COVERAGE,
    MIN_COVERAGE_STRONG,
    STRONG_FIELDS,
    WEAK_ONLY_DISCOUNT,
    ScoredDoc,
    constraint_multiplier,
    dedupe_hits,
    idf_map,
)
from .textnorm import normalize_text
from .tokenize import STOP_TERMS, tokenize

# Fields indexed per document; weights live in scoring.FIELD_WEIGHTS.
_TEXT_FIELDS = (
    "title",
    "keywords",
    "tags",
    "topic",
    "region",
    "materials",
    "teaching_points",
    "summary",
    "canonical_answer",
)

CENSUS_ALIAS_TERMS = frozenset(CENSUS_YEAR_ALIASES)

# “NOUN的XXX怎么/什么…” 问句里，“的”后头名词才是真正要问的东西；语料
# 缺失该名词时应如实说无资料，而不是用 NOUN 部分的字面重叠作答。
_DE_HEAD_RE = re.compile(r"的([一-鿿]{2,6})(?=怎么|什么|如何|多少|是多少|吗|呢)")
MATERIAL_ALIAS_TERMS = frozenset(
    {
        "地图",
        "分布图",
        "图片",
        "影像",
        "视频",
        "动画",
        "文档",
        "课件",
        "图层",
        "地图图层",
    }
)

# 领域泛词：只说明“这是一份资料”，不指示主题，不作为证据。
DOMAIN_STOP_TERMS = frozenset({"资料", "数据", "内容", "情况", "信息", "材料"})

# 表述同义：同一地理格局方向一致的常见口头说法。相反表述（如
# “西多东少”）描述相反的空间格局，不得映射为“东密西疏”——否则纠错、
# 判断类问题会被当成同义改写。
PHRASE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "东多西少": ("东密西疏",),
    "东南密集": ("东密西疏",),
}

WEAK_FIELDS = frozenset({"summary", "canonical_answer", "materials"})

# sub-terms backfilled from long lexicon matches weigh this fraction
SUB_TERM_WEIGHT = 0.7


@dataclass(frozen=True)
class RetrievalDoc:
    """One retrievable knowledge document."""

    doc_id: str
    title: str
    keywords: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    topic: str = ""
    region: str = ""
    time_value: str = ""
    summary: str = ""
    canonical_answer: str = ""
    teaching_points: tuple[str, ...] = ()
    material_texts: tuple[str, ...] = ()
    constraints: DocumentConstraints = field(default_factory=DocumentConstraints)

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any], material_texts: Iterable[str] = ()) -> "RetrievalDoc":
        materials = tuple(normalize_text(text) for text in material_texts)
        teaching_points = tuple(str(part) for part in (item.get("teaching_points") or []))
        text_blob = " ".join(
            [
                str(item.get("title") or ""),
                " ".join(str(part) for part in (item.get("keywords") or [])),
                " ".join(str(part) for part in (item.get("tags") or [])),
                str(item.get("summary") or ""),
                str(item.get("canonical_answer") or ""),
                " ".join(teaching_points),
                " ".join(materials),
            ]
        )
        return cls(
            doc_id=str(item.get("id") or ""),
            title=str(item.get("title") or ""),
            keywords=tuple(str(part) for part in (item.get("keywords") or [])),
            tags=tuple(str(part) for part in (item.get("tags") or [])),
            topic=str(item.get("topic") or ""),
            region=str(item.get("region") or ""),
            time_value=str(item.get("time") or ""),
            summary=str(item.get("summary") or ""),
            canonical_answer=str(item.get("canonical_answer") or item.get("summary") or ""),
            teaching_points=teaching_points,
            material_texts=materials,
            constraints=DocumentConstraints.from_fields(
                region=str(item.get("region") or ""),
                time_value=str(item.get("time") or ""),
                text=text_blob,
                topic=str(item.get("topic") or ""),
            ),
        )

    def field_texts(self) -> dict[str, str]:
        region_text = normalize_text(self.region)
        for alias in REGION_CANONICAL_ALIASES.get(
            region_text, ()
        ):  # region "china" also answers 中国/全国/我国
            region_text = f"{region_text} {alias}" if region_text else alias
        return {
            "title": normalize_text(self.title),
            "keywords": normalize_text(" ".join(self.keywords)),
            "tags": normalize_text(" ".join(self.tags)),
            "topic": normalize_text(self.topic),
            "region": normalize_text(region_text),
            "materials": normalize_text(" ".join(self.material_texts)),
            "teaching_points": normalize_text(" ".join(self.teaching_points)),
            "summary": normalize_text(self.summary),
            "canonical_answer": normalize_text(self.canonical_answer),
        }


@dataclass(frozen=True)
class RetrievalHit:
    """One ranked hit; ``score`` is only comparable within the same query."""

    doc_id: str
    score: float
    coverage: float
    matched_fields: dict[str, list[str]]
    constraint_notes: list[str]


@dataclass
class RetrievalResult:
    """Ranked hits plus an explicit evidence verdict."""

    hits: list[RetrievalHit]
    insufficient: bool
    message: str = ""

    @property
    def ids(self) -> list[str]:
        return [hit.doc_id for hit in self.hits]


class RetrievalEngine:
    """Index a set of documents and answer Chinese natural-language queries.

    Build cost is linear in corpus size and intended for per-owner caches
    on top of knowledge manifests of classroom scale (tens to hundreds of
    items).
    """

    def __init__(self, docs: Iterable[RetrievalDoc]):
        self.docs: list[RetrievalDoc] = [doc for doc in docs if doc.doc_id]
        self._fields: dict[str, dict[str, str]] = {doc.doc_id: doc.field_texts() for doc in self.docs}
        self._lexicon = self._build_lexicon()
        self._vocab_substrings = self._build_vocab_substrings()
        self._terms: dict[str, list[str]] = {
            doc.doc_id: self._doc_terms(doc) for doc in self.docs
        }
        self._idf = self._build_idf()

    # -- public API -----------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 5,
        min_score: float = MIN_ABSOLUTE_SCORE,
        min_coverage: float = MIN_COVERAGE,
        constraints: QueryConstraints | None = None,
    ) -> RetrievalResult:
        # 表述同义展开：让“东多西少”也能命中写作“东密西疏”的资料。
        expanded_text = query
        for phrase, synonyms in PHRASE_SYNONYMS.items():
            if phrase in normalize_text(query):
                expanded_text = f"{expanded_text} {' '.join(synonyms)}"
        # “的”后头名词是问句真正的落点：全部不在语料词表内则如实无资料。
        # 捕获可能带入尾随动词（“分界线叫”），因此从最长候选逐步截短，
        # 任一前缀能被词表片段覆盖即认为语料覆盖了该问点。
        de_heads = _DE_HEAD_RE.findall(normalize_text(query))
        if de_heads and all(not self._head_covered(head) for head in de_heads):
            return self._insufficient(
                "知识库中没有找到与该问题匹配的资料，请尝试更换关键词或放宽筛选条件。"
            )
        parsed = constraints or extract_constraints(query)
        raw_tokens = tokenize(expanded_text, self._lexicon)
        query_terms = [
            term
            for term in raw_tokens
            if term not in STOP_TERMS and (len(term) >= 2 or term.isdigit())
        ]
        if not query_terms:
            return self._insufficient("未识别出可检索的关键词，请换一种问法。")

        # Constraint terms (region aliases, bare years, material types) are
        # not topical evidence on their own: “今天上海天气怎么样” must not
        # hit the Shanghai material purely on 上海. Census shorthand (七普)
        # stays evidence: it is corpus-specific vocabulary, unlike 区域词.
        content_terms = [
            term
            for term in query_terms
            if term not in REGION_ALIASES
            and term not in MATERIAL_ALIAS_TERMS
            and term not in DOMAIN_STOP_TERMS
            and not term.isdigit()
        ]
        # Metric synonym expansion: 人口总数 also searches 人口数量, keeping
        # paraphrased indicators findable without hard-coding queries.
        expanded_terms: set[str] = set()
        seen_terms = set(query_terms)
        for term in query_terms:
            metric = METRIC_ALIASES.get(term)
            if not metric:
                continue
            for sibling in METRIC_ALIASES:
                if sibling != term and METRIC_ALIASES[sibling] == metric and len(sibling) >= 2 and sibling not in seen_terms:
                    seen_terms.add(sibling)
                    expanded_terms.add(sibling)
        query_terms = query_terms + sorted(expanded_terms)
        content_terms = content_terms + [term for term in expanded_terms if term not in content_terms]

        # Sub-term backfill: a long lexicon hit (人口分布特点) must not hide
        # documents that only carry its inner term (人口分布). Add contained
        # lexicon terms at reduced weight so partial-overlap docs still rank.
        sub_term_weight: dict[str, float] = {}
        for term in query_terms:
            if len(term) < 4:
                continue
            for size in range(2, len(term) - 1):
                for start in range(len(term) - size + 1):
                    piece = term[start : start + size]
                    if piece in self._lexicon and piece not in seen_terms and piece not in sub_term_weight:
                        sub_term_weight[piece] = SUB_TERM_WEIGHT
        if sub_term_weight:
            query_terms = query_terms + [
                term for term in sub_term_weight if term not in query_terms
            ]
            content_terms = content_terms + [
                term for term in sub_term_weight if term not in content_terms
            ]

        weighted = {term: self._idf.get(term, 1.0) for term in query_terms}
        for piece, factor in sub_term_weight.items():
            weighted[piece] = weighted[piece] * factor
        # Only in-vocabulary content terms count as ranking evidence: OOV
        # spans (“GDP”, “房价”) can never match a document. But they still
        # count against the evidence guard below, so a question whose real
        # subject is missing from the corpus abstains instead of returning
        # a document that shares one generic word.
        invocab_content = [term for term in content_terms if term in self._idf]
        # Expansion terms are retrieval aids, not user-typed content:
        # missing siblings must not pollute the OOV penalty.
        oov_content = [
            term for term in content_terms if term not in self._idf and term not in expanded_terms
        ]
        if invocab_content:
            evidence_terms = invocab_content
            total_weight = sum(weighted[term] for term in invocab_content)
        elif parsed.census_terms or parsed.years:
            return self._constraint_search(parsed, limit, min_score)
        elif not content_terms and parsed.region:
            return self._constraint_search(parsed, limit, min_score)
        else:
            return self._insufficient(
                "知识库中没有找到与该问题匹配的资料，请尝试更换关键词或放宽筛选条件。"
            )
        oov_weight = sum(weighted[term] for term in oov_content)
        # Constraint admission may only fire when the question itself has
        # answerable vocabulary beyond backfilled sub-terms.
        invocab_non_sub = [term for term in invocab_content if term not in sub_term_weight]

        scored: list[ScoredDoc] = []
        strong_field_names = list(STRONG_FIELDS)
        for doc in self.docs:
            fields = self._fields[doc.doc_id]
            matched_fields: dict[str, list[str]] = {}
            score = 0.0
            matched_evidence: list[str] = []
            strong_hit = False
            for term, weight in weighted.items():
                hit_fields = [name for name in _TEXT_FIELDS if term in fields[name]]
                if not hit_fields:
                    continue
                if term in evidence_terms:
                    matched_evidence.append(term)
                    if any(name in strong_field_names for name in hit_fields):
                        strong_hit = True
                best_weight = max((FIELD_WEIGHTS[name] for name in hit_fields), default=0.5)
                score += weight * best_weight
                for name in hit_fields:
                    matched_fields.setdefault(name, []).append(term)
            if not matched_evidence:
                # Constraint-admission: a query with viable corpus
                # vocabulary may still legitimately surface documents that
                # match its region/material constraints (「上海的资料」).
                # Only when the question itself has answerable words —
                # otherwise「今天上海天气怎么样」would list Shanghai docs.
                admitted_notes: list[str] = []
                admit_score = 0.0
                if (
                    invocab_non_sub
                    and not oov_content
                    and parsed.regions
                    and doc.constraints.region in parsed.regions
                ):
                    admit_score += 1.5
                    admitted_notes.append(f"region_admitted:{doc.constraints.region}")
                if (
                    invocab_non_sub
                    and not oov_content
                    and parsed.material_types
                    and set(doc.constraints.material_types) & set(parsed.material_types)
                ):
                    admit_score += 2.0 * MATERIAL_MATCH_BONUS
                    admitted_notes.append("material_admitted")
                if admit_score > 0:
                    scored.append(
                        ScoredDoc(
                            doc_id=doc.doc_id,
                            score=admit_score,
                            coverage=min_coverage,
                            matched_fields={"materials": ["<constraint_admitted>"]},
                            constraint_notes=admitted_notes,
                        )
                    )
                continue
            coverage = sum(weighted[term] for term in matched_evidence) / total_weight
            if coverage < min_coverage and not (strong_hit and coverage >= MIN_COVERAGE_STRONG):
                continue
            # Evidence guard: matched evidence must carry meaningful weight
            # relative to the content words the corpus cannot match.
            # Synonym/sub-term backfills count for ranking and coverage but
            # not for the guard — unless they are the only evidence, in
            # which case they are measured at full weight, because then
            # they represent the query's own words.
            # 守门只认问句自己的词：同义扩展词是检索辅助，不是用户输入，
            # 永不计入；子词仅在没有字面命中时按原权重计入。
            guard_terms = [
                term
                for term in matched_evidence
                if term not in expanded_terms and term not in sub_term_weight
            ]
            if not guard_terms:
                guard_terms = [term for term in matched_evidence if term not in expanded_terms]
            matched_weight = sum(self._idf.get(term, 1.0) for term in guard_terms)
            guard = matched_weight / (matched_weight + oov_weight) if (matched_weight + oov_weight) else 1.0
            guard_ok = guard >= GUARD_RATIO
            if not guard_ok and guard >= GUARD_RATIO_STRONG:
                strongest = max(guard_terms, key=lambda term: self._idf.get(term, 1.0))
                guard_ok = (
                    self._idf.get(strongest, 1.0) >= GUARD_STRONG_MIN_IDF
                    and len(strongest) >= GUARD_STRONG_MIN_LEN
                )
            # A single matched term that only appears in prose (summary or
            # canonical answer) is the weakest evidence shape: “原因” in one
            # answer text must not answer “火山喷发的原因”.
            if len(guard_terms) == 1 and not strong_hit:
                guard_ok = guard_ok and guard >= GUARD_WEAK_SINGLE
            if not guard_ok:
                continue
            adjusted = constraint_multiplier(parsed, doc.constraints)
            if adjusted is None:
                continue
            multiplier, notes = adjusted
            # A document whose ONLY evidence sits in prose fields (summary /
            # canonical answer) is a weaker signal than a curated-field hit;
            # discount it so prose mentions don't crowd out real matches.
            if not any(name in STRONG_FIELDS for name in matched_fields):
                score *= WEAK_ONLY_DISCOUNT
            score *= multiplier
            scored.append(
                ScoredDoc(
                    doc_id=doc.doc_id,
                    score=score,
                    coverage=coverage,
                    matched_fields=matched_fields,
                    constraint_notes=notes,
                )
            )

        scored.sort(key=lambda row: (-row.score, row.doc_id))
        years_by_id = {doc.doc_id: doc.constraints.years for doc in self.docs}
        scored = dedupe_hits(
            scored,
            {doc.doc_id: doc.title for doc in self.docs},
            {doc.doc_id: doc.canonical_answer for doc in self.docs},
            years_by_id=years_by_id,
        )

        hits: list[RetrievalHit] = []
        for row in scored:
            if row.score < min_score:
                continue
            hits.append(
                RetrievalHit(
                    doc_id=row.doc_id,
                    score=row.score,
                    coverage=row.coverage,
                    matched_fields=row.matched_fields,
                    constraint_notes=row.constraint_notes,
                )
            )
            if len(hits) >= max(1, int(limit)):
                break

        if not hits:
            return self._insufficient(
                "知识库中没有找到与该问题匹配的资料，请尝试更换关键词或放宽筛选条件。"
            )
        return RetrievalResult(hits=hits, insufficient=False)

    # -- internals -------------------------------------------------------

    def _constraint_search(
        self,
        parsed: QueryConstraints,
        limit: int,
        min_score: float,
    ) -> RetrievalResult:
        """Answer constraint-only queries (e.g. “上海”, “五普”) without text overlap.

        A bare constraint question is matched against each document's
        constraint signature instead of token overlap.
        """
        hits: list[RetrievalHit] = []
        for doc in self.docs:
            score = 0.0
            notes: list[str] = []
            if parsed.regions and doc.constraints.region in parsed.regions:
                score += 2.0
                notes.append(f"region:{doc.constraints.region}")
            if parsed.years and doc.constraints.years:
                if set(parsed.years) & set(doc.constraints.years):
                    score += 2.5
                    notes.append(f"year:{doc.constraints.years[0]}")
            if parsed.material_types and set(doc.constraints.material_types) & set(parsed.material_types):
                score += 1.0
                notes.append("material")
            if score < min_score:
                continue
            hits.append(
                RetrievalHit(
                    doc_id=doc.doc_id,
                    score=score,
                    coverage=1.0,
                    matched_fields={},
                    constraint_notes=notes,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.doc_id))
        hits = hits[: max(1, int(limit))]
        if not hits:
            return self._insufficient(
                "知识库中没有找到与该问题匹配的资料，请尝试更换关键词或放宽筛选条件。"
            )
        return RetrievalResult(hits=hits, insufficient=False)

    @staticmethod
    def _insufficient(message: str) -> RetrievalResult:
        return RetrievalResult(hits=[], insufficient=True, message=message)

    def _head_covered(self, head: str) -> bool:
        """Check whether a “的”-head noun is plausibly covered by the corpus.

        A head counts as covered when some prefix of it appears inside any
        indexed term (口径 ⊂ 统计口径, 分界线 ⊂ 人口地理分界线).
        """
        vocabulary = self._vocab_substrings
        stripped = head.rstrip("叫是有做用办属归算")
        for end in range(len(stripped), 1, -1):
            candidate = stripped[:end]
            if candidate in vocabulary:
                return True
            for start in range(len(candidate) - 1):
                if candidate[start:] in vocabulary:
                    return True
        return False

    def _doc_terms(self, doc: RetrievalDoc) -> list[str]:
        terms: list[str] = []
        for text in [
            doc.title,
            " ".join(doc.keywords),
            " ".join(doc.tags),
            doc.topic,
            doc.region,
            " ".join(doc.material_texts),
            " ".join(doc.teaching_points),
            doc.summary,
            doc.canonical_answer,
        ]:
            terms.extend(tokenize(text, self._lexicon))
        return terms

    def _build_lexicon(self) -> set[str]:
        lexicon: set[str] = set()
        for doc in self.docs:
            sources = [doc.title, *doc.keywords, *doc.tags, doc.topic, *doc.teaching_points]
            for source in sources:
                normalized = normalize_text(source)
                # Cap at 6 so teaching-point sentences never become lexicon
                # terms that swallow whole runs and hide sub-terms.
                if 2 <= len(normalized) <= 6 and normalized:
                    lexicon.add(normalized)
        return lexicon

    def _build_vocab_substrings(self) -> set[str]:
        """All length≥2 substrings of indexed terms, for head-coverage checks."""
        substrings: set[str] = set()
        for term in self._lexicon:
            for size in range(2, len(term) + 1):
                for start in range(len(term) - size + 1):
                    substrings.add(term[start : start + size])
        return substrings

    def _build_idf(self) -> dict[str, float]:
        document_frequency: dict[str, int] = {}
        for terms in self._terms.values():
            for term in set(terms):
                document_frequency[term] = document_frequency.get(term, 0) + 1
        return idf_map(len(self.docs), document_frequency)
