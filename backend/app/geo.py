from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence, Tuple


Point = Tuple[float, float]
WeightedPoint = Tuple[Point, float]

# Heihe (NE) and Tengchong (SW) endpoints of the classic Hu Huanyong Line.
# These anchors keep any fitted variation inside the same geographical corridor.
CLASSIC_START: Point = (127.5, 50.2)
CLASSIC_END: Point = (98.5, 25.0)
# A reference point well inside the south-east half (Shanghai) so that
# "same side as reference" consistently means the populated south-east side.
REFERENCE_POINT: Point = (121.47, 31.23)


def normalize_vector(dx: float, dy: float) -> Tuple[float, float]:
    length = math.hypot(dx, dy)
    if length == 0:
        return (1.0, 0.0)
    return (dx / length, dy / length)


def rotate_vector(dx: float, dy: float, angle_radians: float) -> Tuple[float, float]:
    cosine = math.cos(angle_radians)
    sine = math.sin(angle_radians)
    return (
        dx * cosine - dy * sine,
        dx * sine + dy * cosine,
    )


def line_side_value(point: Point, anchor: Point, direction: Tuple[float, float]) -> float:
    return (point[0] - anchor[0]) * direction[1] - (point[1] - anchor[1]) * direction[0]


def population_share_for_line(
    weighted_points: Sequence[WeightedPoint],
    anchor: Point,
    direction: Tuple[float, float],
    reference_point: Point,
) -> float:
    if not weighted_points:
        return 0.0
    reference_side = line_side_value(reference_point, anchor, direction)
    east_total = 0.0
    total = 0.0
    for point, weight in weighted_points:
        side = line_side_value(point, anchor, direction)
        total += weight
        if side == 0 or side * reference_side >= 0:
            east_total += weight
    return east_total / total if total else 0.0


def segment_for_line(anchor: Point, direction: Tuple[float, float], weighted_points: Sequence[WeightedPoint]) -> Tuple[Point, Point]:
    if not weighted_points:
        return ((anchor[0] - 5.0, anchor[1] - 5.0), (anchor[0] + 5.0, anchor[1] + 5.0))
    xs = [point[0] for point, _ in weighted_points]
    ys = [point[1] for point, _ in weighted_points]
    diagonal = max(math.hypot(max(xs) - min(xs), max(ys) - min(ys)), 1.0)
    scale = diagonal * 0.9
    return (
        (anchor[0] - direction[0] * scale, anchor[1] - direction[1] * scale),
        (anchor[0] + direction[0] * scale, anchor[1] + direction[1] * scale),
    )


def generate_dynamic_hu_line(
    weighted_points: Iterable[WeightedPoint],
    target_share: float = 0.94,
    shift_range_degrees: float = 4.0,
    shift_steps: int = 81,
) -> Dict[str, object]:
    """Fit a population-dividing line inside the Heihe-Tengchong corridor.

    The classic Hu Line separates China into a south-east half with ~94% of the
    population and a north-west half with ~6%.  The dynamic fitted line keeps
    the same Heihe-Tengchong orientation and only shifts perpendicular to it,
    so it remains geographically interpretable as a Hu-Line-like divider rather
    than an arbitrary straight line somewhere over north-west China.
    """
    points = list(weighted_points)
    classic_direction = normalize_vector(CLASSIC_END[0] - CLASSIC_START[0], CLASSIC_END[1] - CLASSIC_START[1])
    classic_anchor = ((CLASSIC_START[0] + CLASSIC_END[0]) / 2.0, (CLASSIC_START[1] + CLASSIC_END[1]) / 2.0)
    classic_share = population_share_for_line(points, classic_anchor, classic_direction, REFERENCE_POINT)

    # Perpendicular direction: positive shifts move the line toward the
    # south-east, negative shifts move it toward the north-west.
    normal = (-classic_direction[1], classic_direction[0])
    best_candidate = None
    shift_range = max(float(shift_range_degrees), 0.0)
    steps = max(int(shift_steps), 2)

    for shift_index in range(steps):
        shift_ratio = shift_index / float(steps - 1)
        shift_value = -shift_range + 2.0 * shift_range * shift_ratio
        shifted_start = (
            CLASSIC_START[0] + normal[0] * shift_value,
            CLASSIC_START[1] + normal[1] * shift_value,
        )
        shifted_end = (
            CLASSIC_END[0] + normal[0] * shift_value,
            CLASSIC_END[1] + normal[1] * shift_value,
        )
        anchor = ((shifted_start[0] + shifted_end[0]) / 2.0, (shifted_start[1] + shifted_end[1]) / 2.0)
        share = population_share_for_line(points, anchor, classic_direction, REFERENCE_POINT)
        # The primary objective is matching the target share.  A tiny
        # regularisation term breaks ties in favour of the classic line.
        score = abs(share - float(target_share)) + 1e-6 * abs(shift_value)
        candidate = {
            "score": score,
            "share": share,
            "anchor": anchor,
            "shift_distance": shift_value,
            "shifted_start": shifted_start,
            "shifted_end": shifted_end,
        }
        if best_candidate is None or candidate["score"] < best_candidate["score"]:
            best_candidate = candidate

    assert best_candidate is not None
    classic_segment = (CLASSIC_START, CLASSIC_END)
    fitted_segment = (best_candidate["shifted_start"], best_candidate["shifted_end"])
    return {
        "classic_share": classic_share,
        "dynamic_share": best_candidate["share"],
        "shift_distance": best_candidate["shift_distance"],
        "features": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "name": "经典胡焕庸线",
                        "line_type": "classic",
                        "east_share": round(classic_share, 4),
                        "__strokeColor": "#07575f",
                        "__strokeWidth": 3,
                        "__lineDash": []
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [list(classic_segment[0]), list(classic_segment[1])]
                    }
                },
                {
                    "type": "Feature",
                    "properties": {
                        "name": "教学拟合线（预设94%目标）",
                        "line_type": "dynamic",
                        "east_share": round(best_candidate["share"], 4),
                        "__strokeColor": "#d88a26",
                        "__lineDash": [7, 5],
                        "__strokeWidth": 2
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [list(fitted_segment[0]), list(fitted_segment[1])]
                    }
                }
            ]
        }
    }
