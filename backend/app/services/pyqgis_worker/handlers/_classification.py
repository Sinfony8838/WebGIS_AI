"""Shared classification helpers used by ``choropleth`` and ``classify``.

Provides break-point computation for the standard methods (jenks /
natural_breaks, equal_interval, quantile, stddev) and a small label
formatter. **No** styling concerns here — color ramps stay in
``choropleth.py`` because they are presentation, not classification.

Extracted in v1.2 Phase 1.1 so the new ``classify`` handler doesn't have
to duplicate the algorithm — and so a future "user-defined break edits"
flow has one place to mutate.

Backward-compat note: this preserves the original behaviour of
``choropleth._compute_breaks`` exactly, including the tolerant fall-back
to jenks for unknown method strings (the validator already rejects bad
methods before they reach the handler).
"""
from __future__ import annotations

import statistics
from typing import List

from ..errors import WorkflowExecutionError


#: Method strings the helper recognises. Validator-level enum in
#: ``workflow_validator.ALLOWED_CLASSIFY_METHODS`` is the source of truth
#: for what is accepted at API boundary; the extra aliases here keep the
#: helper tolerant of minor variants.
SUPPORTED_METHODS = frozenset({
    "jenks",
    "natural_breaks",
    "equal",
    "equal_interval",
    "quantile",
    "stddev",
    "std_dev",
})


def compute_breaks(values: List[float], classes: int, method: str = "jenks") -> List[float]:
    """Return ``classes + 1`` ordered breakpoints from ``values``.

    Raises :class:`WorkflowExecutionError` if ``values`` is empty.
    For unknown methods, falls back to jenks to preserve the historical
    handler behaviour.
    """
    if not values:
        raise WorkflowExecutionError(
            code="GEOMETRY_INVALID",
            message="no values to classify",
            user_friendly="无法分级：没有任何样本。",
        )
    sorted_values = sorted(values)
    method_key = (method or "jenks").lower()
    if method_key in {"equal", "equal_interval"}:
        return _equal_interval(sorted_values, classes)
    if method_key == "quantile":
        return _quantile(sorted_values, classes)
    if method_key in {"stddev", "std_dev"}:
        return _stddev(sorted_values, classes)
    # jenks / natural_breaks / anything else → jenks (lenient fallback)
    return _fisher_jenks(sorted_values, classes)


def classify_value(value: float, breaks: List[float]) -> int:
    """Return the 0-based class index for ``value`` against ``breaks``.

    Half-open intervals ``[breaks[i], breaks[i+1])`` for all classes
    except the last, which is fully closed so the max value lands in the
    top class. Out-of-range values are clamped to the nearest class.
    """
    if not breaks or len(breaks) < 2:
        return 0
    if value < breaks[0]:
        return 0
    last_class = len(breaks) - 2
    for i in range(last_class):
        if breaks[i] <= value < breaks[i + 1]:
            return i
    return last_class


def format_label(low: float, high: float) -> str:
    """Render a human-friendly ``"123.45 - 678.90"`` style label."""
    def _fmt(value: float) -> str:
        if abs(value) >= 1000 or abs(value) < 0.01:
            return f"{value:.2g}"
        return f"{value:.2f}"
    return f"{_fmt(low)} - {_fmt(high)}"


# ---------------------------------------------------------------------------
# Internal break algorithms (kept identical to the original choropleth.py
# implementation so the refactor produces byte-identical breaks).
# ---------------------------------------------------------------------------


def _equal_interval(sorted_values: List[float], classes: int) -> List[float]:
    lo = sorted_values[0]
    hi = sorted_values[-1]
    if hi <= lo:
        return [lo, hi]
    step = (hi - lo) / classes
    return [lo + step * i for i in range(classes + 1)]


def _quantile(sorted_values: List[float], classes: int) -> List[float]:
    breaks = [sorted_values[0]]
    for i in range(1, classes):
        idx = int(round(i * (len(sorted_values) - 1) / classes))
        breaks.append(sorted_values[idx])
    breaks.append(sorted_values[-1])
    return breaks


def _stddev(sorted_values: List[float], classes: int) -> List[float]:
    mean = sum(sorted_values) / len(sorted_values)
    stdev = statistics.pstdev(sorted_values) or 1.0
    breaks = [mean + (i - classes / 2) * stdev for i in range(classes + 1)]
    breaks[0] = min(breaks[0], sorted_values[0])
    breaks[-1] = max(breaks[-1], sorted_values[-1])
    return breaks


def _fisher_jenks(sorted_values: List[float], classes: int) -> List[float]:
    """Simple Fisher-Jenks approximation: quantile seed + 2 refinement passes."""
    n = len(sorted_values)
    if classes <= 1:
        return [sorted_values[0], sorted_values[-1]]
    breaks = [sorted_values[0]]
    for i in range(1, classes):
        idx = int(round(i * (n - 1) / classes))
        breaks.append(sorted_values[idx])
    breaks.append(sorted_values[-1])
    for _ in range(2):
        for i in range(1, classes):
            left_idx = next(idx for idx, v in enumerate(sorted_values) if v >= breaks[i - 1])
            right_idx = next(idx for idx, v in enumerate(sorted_values) if v >= breaks[i + 1])
            window = sorted_values[left_idx:right_idx + 1]
            if window:
                breaks[i] = statistics.median(window)
    breaks.sort()
    return breaks
