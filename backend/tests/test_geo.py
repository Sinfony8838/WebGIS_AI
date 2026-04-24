from __future__ import annotations

import unittest

from backend.app.geo import generate_dynamic_hu_line


class DynamicHuLineTest(unittest.TestCase):
    def test_generate_dynamic_hu_line_returns_two_features(self) -> None:
        points = [
            ((126.5, 45.0), 9850),
            ((116.5, 39.2), 15600),
            ((121.0, 30.5), 23000),
            ((112.0, 30.5), 18200),
            ((113.5, 23.5), 17400),
            ((94.0, 40.5), 9800),
            ((102.0, 28.0), 12600),
        ]
        payload = generate_dynamic_hu_line(points)
        self.assertIn("features", payload)
        self.assertEqual(len(payload["features"]["features"]), 2)
        self.assertGreater(payload["dynamic_share"], 0.8)

