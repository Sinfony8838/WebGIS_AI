from __future__ import annotations

import math
import unittest

from backend.app.geo import CLASSIC_END, CLASSIC_START, generate_dynamic_hu_line


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

    def test_dynamic_line_stays_in_heihe_tengchong_corridor(self) -> None:
        """The fitted line must remain a Hu-Line-like divider: same orientation
        as the classic Heihe-Tengchong line and endpoints close to it.  This
        prevents the optimiser from drifting into north-west China."""
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
        features = payload["features"]["features"]
        classic_coords = features[0]["geometry"]["coordinates"]
        dynamic_coords = features[1]["geometry"]["coordinates"]

        classic_direction = (
            CLASSIC_END[0] - CLASSIC_START[0],
            CLASSIC_END[1] - CLASSIC_START[1],
        )
        dynamic_direction = (
            dynamic_coords[1][0] - dynamic_coords[0][0],
            dynamic_coords[1][1] - dynamic_coords[0][1],
        )

        def _normalize(dx: float, dy: float) -> tuple[float, float]:
            length = math.hypot(dx, dy)
            return (dx / length, dy / length)

        cd = _normalize(*classic_direction)
        dd = _normalize(*dynamic_direction)
        # Directions should be the same (parallel) within a small tolerance.
        self.assertAlmostEqual(cd[0], dd[0], places=5)
        self.assertAlmostEqual(cd[1], dd[1], places=5)

        # Endpoints should not wander far from the classic corridor.
        for index, classic_point in enumerate([CLASSIC_START, CLASSIC_END]):
            dynamic_point = dynamic_coords[index]
            distance = math.hypot(
                dynamic_point[0] - classic_point[0],
                dynamic_point[1] - classic_point[1],
            )
            self.assertLess(distance, 5.0)
