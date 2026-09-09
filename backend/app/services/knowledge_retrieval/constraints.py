"""Query-side constraint extraction: region, year, metric, material type.

Classroom questions such as ``上海2010年的人口密度是多少`` carry hard
constraints that keyword overlap alone ignores. Extracting them once lets
both knowledge services apply the same rules, so 全国/上海, 人口数量/密度
and different census years stop being interchangeable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .textnorm import normalize_text

# Alias → canonical region key. Canonical keys mirror the ``region`` field
# values already present in knowledge manifests (china / shanghai / global...).
REGION_ALIASES: dict[str, str] = {
    "中国": "china",
    "全国": "china",
    "我国": "china",
    "国内": "china",
    "china": "china",
    "chinese": "china",
    "上海": "shanghai",
    "沪": "shanghai",
    "shanghai": "shanghai",
    "世界": "global",
    "全球": "global",
    "world": "global",
    "global": "global",
}

# Region keys that are specific enough to conflict with each other. Empty
# or generic values ("general", "") never trigger a conflict penalty.
SPECIFIC_REGIONS = frozenset({"china", "shanghai", "global"})

# Containment relation used for soft conflicts: a shanghai question is not
# answered by a china-level document and vice versa, but a query without a
# region matches anything.
REGION_SIBLINGS: dict[str, frozenset[str]] = {
    "china": frozenset({"shanghai", "global"}),
    "shanghai": frozenset({"china"}),
    "global": frozenset({"china"}),
}

REGION_OF_CHINA_PREFIXES = ("中国", "全国", "我国")

# canonical region key → every alias that should count as a hit on the
# region field, so a “全国人口” query matches docs whose region is the
# literal string "china".
REGION_CANONICAL_ALIASES: dict[str, tuple[str, ...]] = {}
for _alias, _canonical in REGION_ALIASES.items():
    REGION_CANONICAL_ALIASES[_canonical] = REGION_CANONICAL_ALIASES.get(_canonical, ()) + (_alias,)

# Census shorthand → statistical year. Sourced from the builtin corpus
# itself (五普/六普/七普 items), not invented facts.
CENSUS_YEAR_ALIASES: dict[str, int] = {
    "七普": 2020,
    "六普": 2010,
    "五普": 2000,
    "四普": 1990,
    "三普": 1982,
}

# Metric families used to keep 人口数量 and 人口密度 apart.
METRIC_ALIASES: dict[str, str] = {
    "人口密度": "density",
    "密度": "density",
    "每平方千米": "density",
    "每平方公里": "density",
    "人口数量": "count",
    "总人口": "count",
    "人口总数": "count",
    "人口规模": "count",
    "常住人口": "resident",
    "户籍人口": "registered",
    "人口分布": "distribution",
    "分布格局": "distribution",
    "人口迁移": "migration",
    "迁移": "migration",
    "流动": "migration",
    "气候": "climate",
    "气候区划": "climate",
    "降水": "precipitation",
    "气温": "temperature",
}

# Documents whose topic/title belongs to one metric family conflict with a
# query asking for a sibling metric about the same subject.
METRIC_CONFLICTS: dict[str, frozenset[str]] = {
    "density": frozenset({"count"}),
    "count": frozenset({"density"}),
    "resident": frozenset({"registered"}),
    "registered": frozenset({"resident"}),
}

MATERIAL_TYPE_ALIASES: dict[str, str] = {
    "地图": "image",
    "分布图": "image",
    "图片": "image",
    "影像": "image",
    "视频": "video",
    "动画": "animation",
    "文档": "document",
    "课件": "document",
    "图层": "layer",
    "地图图层": "layer",
}

# filler tokens stripped before term matching; they never indicate topic.
_FILLER_TERMS = frozenset(
    {
        "请问", "一下", "告诉", "我想", "知道", "了解", "看看", "查一下",
        "是什么", "什么", "多少", "怎样", "怎么", "如何", "为什么", "哪些",
        "情况", "有关", "关于", "可以", "介绍",
    }
)

# \b is unusable here: CJK characters count as word chars in Python re, so
# lookarounds make “2000年” and “2000” both parse while excluding 20003.
_YEAR_RUN_RE = re.compile(r"(?<![0-9])(19|20)\d{2}(?![0-9])")


@dataclass
class QueryConstraints:
    """Hard/soft constraints parsed from a natural-language query."""

    region: str = ""
    regions: tuple[str, ...] = ()
    years: tuple[int, ...] = ()
    census_terms: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    material_types: tuple[str, ...] = ()
    matched_census_year: bool = False

    @property
    def has_constraints(self) -> bool:
        return bool(self.region or self.years or self.metrics or self.material_types)


@dataclass
class DocumentConstraints:
    """Constraint signature of one knowledge item."""

    region: str = ""
    years: tuple[int, ...] = ()
    mentioned_years: tuple[int, ...] = ()
    metrics: tuple[str, ...] = ()
    material_types: tuple[str, ...] = ()
    topic: str = ""

    @classmethod
    def from_fields(
        cls,
        region: str = "",
        time_value: str = "",
        text: str = "",
        material_types: tuple[str, ...] = (),
        topic: str = "",
    ) -> "DocumentConstraints":
        normalized_region = normalize_text(region)
        canonical_region = REGION_ALIASES.get(normalized_region, normalized_region)
        # 统计时点只认 time 字段。资料正文或出处里的年份可能是发布年份、
        # 引用年份或对照年份，不能拿来当资料的统计时点（2025 年发布的
        # 报告完全可以描述 2020 年人口），只作为“提及年份”供宽松匹配。
        years = _years_from_time_field(time_value)
        mentioned = tuple(
            int(match.group(0)) for match in _YEAR_RUN_RE.finditer(normalize_text(text))
        )
        mentioned_years = tuple(
            year for year in dict.fromkeys(mentioned) if year not in years
        )
        metrics = tuple(
            dict.fromkeys(
                metric
                for alias, metric in METRIC_ALIASES.items()
                if alias in normalize_text(text)
            )
        )
        normalized_text = normalize_text(text)
        derived_materials = tuple(
            dict.fromkeys(
                material
                for alias, material in MATERIAL_TYPE_ALIASES.items()
                if alias in normalized_text
            )
        )
        merged_materials = tuple(dict.fromkeys((*material_types, *derived_materials)))
        return cls(
            region=canonical_region,
            years=years,
            mentioned_years=mentioned_years,
            metrics=metrics,
            material_types=merged_materials,
            topic=normalize_text(topic),
        )


def extract_constraints(query: str) -> QueryConstraints:
    """Parse region/year/metric/material constraints out of a Chinese query."""
    normalized = normalize_text(query)
    constraints = QueryConstraints()

    # Prefer the longest alias so “上海” wins over a bare “中国” hit inside a
    # longer phrase, and 中国/全国/我国 all resolve to the canonical china.
    # 比较类问句（“上海和全国”）会提到多个区域，全部记录用于放宽冲突判定。
    mentioned: list[str] = []
    for alias in sorted(REGION_ALIASES, key=len, reverse=True):
        if alias in normalized:
            canonical = REGION_ALIASES[alias]
            if canonical not in mentioned:
                mentioned.append(canonical)
    constraints.regions = tuple(mentioned)
    constraints.region = mentioned[0] if mentioned else ""

    years: list[int] = []
    census_terms: list[str] = []
    for alias, year in CENSUS_YEAR_ALIASES.items():
        if alias in normalized:
            years.append(year)
            census_terms.append(alias)
    for match in _YEAR_RUN_RE.finditer(normalized):
        years.append(int(match.group(0).lstrip()))
    constraints.years = tuple(dict.fromkeys(years))
    constraints.census_terms = tuple(census_terms)
    constraints.matched_census_year = bool(census_terms)

    constraints.metrics = tuple(
        dict.fromkeys(
            metric
            for alias, metric in METRIC_ALIASES.items()
            if _alias_in_query(alias, normalized)
        )
    )
    constraints.material_types = tuple(
        dict.fromkeys(
            material
            for alias, material in MATERIAL_TYPE_ALIASES.items()
            if alias in normalized
        )
    )
    return constraints


def _alias_in_query(alias: str, normalized: str) -> bool:
    if alias not in normalized:
        return False
    # 密度 alone is too generic unless the question is about population.
    if alias == "密度" and "人口" not in normalized:
        return False
    if alias in _FILLER_TERMS:
        return False
    return True


def _longest_alias_match(normalized: str, aliases: dict[str, str]) -> str:
    best = ""
    best_region = ""
    for alias, region in aliases.items():
        if alias in normalized and len(alias) > len(best):
            best = alias
            best_region = region
    return best_region


def _years_from_time_field(time_value: str) -> tuple[int, ...]:
    import re as _re

    normalized = normalize_text(time_value)
    years = [int(match.group(0)) for match in _re.finditer(r"\b(19|20)\d{2}\b", normalized)]
    return tuple(dict.fromkeys(years))
