from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence, Tuple


Point = Tuple[float, float]
WeightedPoint = Tuple[Point, float]


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
    angle_range_degrees: float = 18.0,
    angle_steps: int = 37,
    shift_steps: int = 61,
) -> Dict[str, object]:
    points = list(weighted_points)
    classic_start = (127.5, 50.2)
    classic_end = (98.5, 25.0)
    classic_direction = normalize_vector(classic_end[0] - classic_start[0], classic_end[1] - classic_start[1])
    classic_anchor = ((classic_start[0] + classic_end[0]) / 2.0, (classic_start[1] + classic_end[1]) / 2.0)
    reference_point = (121.47, 31.23)
    classic_share = population_share_for_line(points, classic_anchor, classic_direction, reference_point)

    xs = [point[0] for point, _ in points]
    ys = [point[1] for point, _ in points]
    diagonal = max(math.hypot(max(xs) - min(xs), max(ys) - min(ys)), 1.0) if points else 1.0
    shift_limit = diagonal * 0.35
    angle_range_radians = math.radians(angle_range_degrees)
    best_candidate = None

    for angle_index in range(max(angle_steps, 2)):
        angle_ratio = angle_index / float(max(angle_steps - 1, 1))
        angle_delta = -angle_range_radians + 2.0 * angle_range_radians * angle_ratio
        direction = rotate_vector(classic_direction[0], classic_direction[1], angle_delta)
        direction = normalize_vector(direction[0], direction[1])
        normal = (-direction[1], direction[0])
        for shift_index in range(max(shift_steps, 2)):
            shift_ratio = shift_index / float(max(shift_steps - 1, 1))
            shift_value = -shift_limit + 2.0 * shift_limit * shift_ratio
            anchor = (
                classic_anchor[0] + normal[0] * shift_value,
                classic_anchor[1] + normal[1] * shift_value,
            )
            share = population_share_for_line(points, anchor, direction, reference_point)
            candidate = {
                "score": abs(share - float(target_share)),
                "share": share,
                "anchor": anchor,
                "direction": direction,
                "angle_delta_degrees": math.degrees(angle_delta),
                "shift_distance": shift_value,
            }
            if best_candidate is None or candidate["score"] < best_candidate["score"]:
                best_candidate = candidate

    assert best_candidate is not None
    classic_segment = segment_for_line(classic_anchor, classic_direction, points)
    fitted_segment = segment_for_line(best_candidate["anchor"], best_candidate["direction"], points)
    return {
        "classic_share": classic_share,
        "dynamic_share": best_candidate["share"],
        "angle_delta_degrees": best_candidate["angle_delta_degrees"],
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
                        "__strokeColor": "#1c3d61",
                        "__strokeWidth": 3,
                        "__lineDash": [10, 8]
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [list(classic_segment[0]), list(classic_segment[1])]
                    }
                },
                {
                    "type": "Feature",
                    "properties": {
                        "name": "动态拟合线",
                        "line_type": "dynamic",
                        "east_share": round(best_candidate["share"], 4),
                        "__strokeColor": "#ffb703",
                        "__strokeWidth": 4
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [list(fitted_segment[0]), list(fitted_segment[1])]
                    }
                }
            ]
        }
    }

