"""Unit tests for the shared classification helper.

This module never imports QGIS — the helper itself is pure-Python.
We assert the behaviour matches what choropleth used to do directly,
guaranteeing the v1.2 Phase 1.1 refactor is byte-identical.
"""
from __future__ import annotations

import unittest

from backend.app.services.pyqgis_worker.handlers import _classification


SAMPLE = [10.0, 12.0, 15.0, 20.0, 25.0, 33.0, 41.0, 58.0, 80.0, 120.0]


class ComputeBreaksTests(unittest.TestCase):
    def test_quantile_breaks_have_expected_length(self) -> None:
        breaks = _classification.compute_breaks(SAMPLE, classes=4, method="quantile")
        self.assertEqual(len(breaks), 5)
        self.assertEqual(breaks[0], min(SAMPLE))
        self.assertEqual(breaks[-1], max(SAMPLE))

    def test_equal_interval_breaks_are_evenly_spaced(self) -> None:
        breaks = _classification.compute_breaks(SAMPLE, classes=5, method="equal_interval")
        self.assertEqual(len(breaks), 6)
        deltas = [breaks[i + 1] - breaks[i] for i in range(len(breaks) - 1)]
        first = deltas[0]
        for delta in deltas[1:]:
            self.assertAlmostEqual(delta, first, places=9)

    def test_stddev_breaks_returned(self) -> None:
        breaks = _classification.compute_breaks(SAMPLE, classes=4, method="stddev")
        self.assertEqual(len(breaks), 5)
        # First and last must enclose the data
        self.assertLessEqual(breaks[0], min(SAMPLE))
        self.assertGreaterEqual(breaks[-1], max(SAMPLE))

    def test_jenks_breaks_are_monotonic(self) -> None:
        breaks = _classification.compute_breaks(SAMPLE, classes=5, method="jenks")
        self.assertEqual(len(breaks), 6)
        for i in range(len(breaks) - 1):
            self.assertLessEqual(breaks[i], breaks[i + 1])

    def test_unknown_method_falls_back_to_jenks(self) -> None:
        # Preserves the original tolerant fall-back behaviour of choropleth.
        breaks = _classification.compute_breaks(SAMPLE, classes=4, method="banana_split")
        expected = _classification.compute_breaks(SAMPLE, classes=4, method="jenks")
        self.assertEqual(breaks, expected)

    def test_empty_values_raises(self) -> None:
        from backend.app.services.pyqgis_worker.errors import WorkflowExecutionError
        with self.assertRaises(WorkflowExecutionError) as ctx:
            _classification.compute_breaks([], classes=5, method="jenks")
        self.assertEqual(ctx.exception.code, "GEOMETRY_INVALID")


class ClassifyValueTests(unittest.TestCase):
    def setUp(self) -> None:
        # Five classes over 0..100
        self.breaks = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]

    def test_min_value_lands_in_first_class(self) -> None:
        self.assertEqual(_classification.classify_value(0.0, self.breaks), 0)

    def test_max_value_lands_in_last_class(self) -> None:
        # Last class is fully closed so the global max lands in class N-1.
        self.assertEqual(_classification.classify_value(100.0, self.breaks), 4)

    def test_interior_value_lands_in_correct_class(self) -> None:
        self.assertEqual(_classification.classify_value(25.0, self.breaks), 1)
        self.assertEqual(_classification.classify_value(60.0, self.breaks), 3)  # half-open
        self.assertEqual(_classification.classify_value(59.999, self.breaks), 2)

    def test_below_range_clamps_to_first(self) -> None:
        self.assertEqual(_classification.classify_value(-1.0, self.breaks), 0)

    def test_above_range_clamps_to_last(self) -> None:
        self.assertEqual(_classification.classify_value(999.0, self.breaks), 4)

    def test_degenerate_breaks(self) -> None:
        # Fewer than 2 break points returns 0 by definition.
        self.assertEqual(_classification.classify_value(50.0, []), 0)
        self.assertEqual(_classification.classify_value(50.0, [10.0]), 0)


class FormatLabelTests(unittest.TestCase):
    def test_decimal_label(self) -> None:
        self.assertEqual(_classification.format_label(12.345, 67.89), "12.35 - 67.89")

    def test_large_value_label_uses_compact_format(self) -> None:
        self.assertEqual(_classification.format_label(1234.0, 56789.0), "1.2e+03 - 5.7e+04")


class ChoroplethBackwardsCompatTests(unittest.TestCase):
    """Verify the old private symbols still exist on choropleth so any
    accidental external importer (or future test) keeps working."""

    def test_choropleth_reexports_compute_breaks(self) -> None:
        from backend.app.services.pyqgis_worker.handlers import choropleth
        self.assertIs(choropleth._compute_breaks, _classification.compute_breaks)

    def test_choropleth_reexports_format_label(self) -> None:
        from backend.app.services.pyqgis_worker.handlers import choropleth
        self.assertIs(choropleth._format_label, _classification.format_label)


if __name__ == "__main__":
    unittest.main()
