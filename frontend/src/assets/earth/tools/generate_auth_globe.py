# Generates the login-page globe SVGs from Natural Earth 1:110m land.
#
# Usage (from this directory, network required on first run):
#   python generate_auth_globe.py
#
# The script downloads ne_110m_land.json once, projects it with a true
# orthographic projection, clips polygons and the graticule to the visible
# hemisphere, and writes auth-globe-dark.svg / auth-globe-light.svg next to
# this tools/ directory. See ../README.md for data source and license.

from __future__ import annotations

import hashlib
import json
import math
import urllib.request
from pathlib import Path

DATA_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson"

# Orthographic projection parameters. Centered on East Asia so the target
# audience recognizes the continents immediately.
CENTER_LON = 105.0
CENTER_LAT = 30.0

VIEW = 520
CX = 260.0
CY = 262.0
R = 200.0

GRATICULE_STEP = 30
SAMPLE_STEP_DEG = 1.5
MAX_EDGE_DEG = 2.0

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent
DATA_PATH = OUT_DIR / "ne_110m_land.json"

lon0 = math.radians(CENTER_LON)
lat0 = math.radians(CENTER_LAT)
sin0, cos0 = math.sin(lat0), math.cos(lat0)


def unit_vector(lon_deg: float, lat_deg: float) -> tuple[float, float, float]:
    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    return (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))


CENTER_VEC = unit_vector(CENTER_LON, CENTER_LAT)


def visible(vec: tuple[float, float, float]) -> bool:
    return vec[0] * CENTER_VEC[0] + vec[1] * CENTER_VEC[1] + vec[2] * CENTER_VEC[2] > 0.0


def project(lon_deg: float, lat_deg: float) -> tuple[float, float] | None:
    """Orthographic projection onto the plane facing the viewer."""
    vec = unit_vector(lon_deg, lat_deg)
    if not visible(vec):
        return None
    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    cos_lat = math.cos(lat)
    x = cos_lat * math.sin(lon - lon0)
    y = cos0 * math.sin(lat) - sin0 * cos_lat * math.cos(lon - lon0)
    return (CX + R * x, CY - R * y)


def subsample_ring(ring: list[list[float]]) -> list[list[float]]:
    """Split long edges so chord-vs-great-circle clipping error stays invisible."""
    out: list[list[float]] = []
    for index, start in enumerate(ring):
        out.append(start)
        if index + 1 >= len(ring):
            break
        end = ring[index + 1]
        dlon = end[0] - start[0]
        dlat = end[1] - start[1]
        steps = max(1, int(math.hypot(dlon, dlat) / MAX_EDGE_DEG))
        for step in range(1, steps):
            out.append([start[0] + dlon * step / steps, start[1] + dlat * step / steps])
    return out


def clip_ring_to_horizon(ring: list[list[float]]) -> list[list[list[float]]]:
    """Sutherland-Hodgman clip of a spherical ring against the visible hemisphere.

    Works on unit vectors; intersection points land on the horizon great
    circle, so their projection sits exactly on the disk edge.
    """
    def intersect(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
        dot_a = a[0] * CENTER_VEC[0] + a[1] * CENTER_VEC[1] + a[2] * CENTER_VEC[2]
        dot_b = b[0] * CENTER_VEC[0] + b[1] * CENTER_VEC[1] + b[2] * CENTER_VEC[2]
        t = dot_a / (dot_a - dot_b)
        mixed = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
        length = math.sqrt(mixed[0] ** 2 + mixed[1] ** 2 + mixed[2] ** 2) or 1.0
        return (mixed[0] / length, mixed[1] / length, mixed[2] / length)

    vectors = [unit_vector(lon, lat) for lon, lat in ring]
    output: list[tuple[float, float, float]] = []
    for index, current in enumerate(vectors):
        previous = vectors[index - 1]
        current_in = visible(current)
        previous_in = visible(previous)
        if current_in:
            if not previous_in:
                output.append(intersect(previous, current))
            output.append(current)
        elif previous_in:
            output.append(intersect(previous, current))
    if len(output) < 3:
        return []
    return [[
        [math.degrees(math.atan2(vec[1], vec[0])), math.degrees(math.asin(max(-1.0, min(1.0, vec[2]))))]
        for vec in output
    ]]


def ring_to_path(ring: list[list[float]]) -> str:
    points: list[tuple[float, float]] = []
    for lon, lat in ring:
        projected = project(lon, lat)
        if projected is not None:
            points.append(projected)
    if len(points) < 3:
        return ""
    return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in points) + "Z"


def project_vec(vec: tuple[float, float, float]) -> tuple[float, float]:
    """Orthographic projection of an already-visible unit vector."""
    lon = math.atan2(vec[1], vec[0])
    lat = math.asin(max(-1.0, min(1.0, vec[2])))
    cos_lat = math.cos(lat)
    x = cos_lat * math.sin(lon - lon0)
    y = cos0 * math.sin(lat) - sin0 * cos_lat * math.cos(lon - lon0)
    return (CX + R * x, CY - R * y)


def clip_line_to_horizon(points: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """Split a lat/lon polyline into visible screen segments, interpolating to the horizon."""
    vectors = [unit_vector(lon, lat) for lon, lat in points]
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []

    def lerp_on_horizon(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float]:
        dot_a = abs(a[0] * CENTER_VEC[0] + a[1] * CENTER_VEC[1] + a[2] * CENTER_VEC[2])
        dot_b = abs(b[0] * CENTER_VEC[0] + b[1] * CENTER_VEC[1] + b[2] * CENTER_VEC[2])
        t = dot_a / (dot_a + dot_b) if (dot_a + dot_b) else 0.0
        mixed = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
        length = math.sqrt(mixed[0] ** 2 + mixed[1] ** 2 + mixed[2] ** 2) or 1.0
        return project_vec((mixed[0] / length, mixed[1] / length, mixed[2] / length))

    for index, current_vec in enumerate(vectors):
        if visible(current_vec):
            current.append(project_vec(current_vec))
        elif current:
            current.append(lerp_on_horizon(vectors[index - 1], current_vec))
            segments.append(current)
            current = []
        if visible(current_vec) and index + 1 < len(vectors) and not visible(vectors[index + 1]):
            current.append(lerp_on_horizon(current_vec, vectors[index + 1]))
            segments.append(current)
            current = []
    if len(current) > 1:
        segments.append(current)
    return [segment for segment in segments if len(segment) > 1]


def graticule_paths() -> list[str]:
    paths: list[str] = []
    lat_range = range(-90 + GRATICULE_STEP, 90, GRATICULE_STEP)
    lon_range = range(-180, 180, GRATICULE_STEP)
    sample = int(SAMPLE_STEP_DEG * 2)

    def drawn_paths(segments: list[list[tuple[float, float]]]) -> None:
        for segment in segments:
            if len(segment) > 1:
                paths.append("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in segment))

    for lat in lat_range:
        drawn_paths(clip_line_to_horizon([(lon, lat) for lon in range(-180, 181, sample)]))

    for lon in lon_range:
        drawn_paths(clip_line_to_horizon([(lon, lat) for lat in range(-90, 91, sample)]))
    return paths


def load_land() -> dict:
    geojson_path = DATA_PATH
    if not geojson_path.exists():
        urllib.request.urlretrieve(DATA_URL, geojson_path)
    payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(geojson_path.read_bytes()).hexdigest()
    print(f"ne_110m_land.geojson sha256={digest}")
    return payload


def land_paths(payload: dict) -> list[str]:
    paths: list[str] = []
    for feature in payload["features"]:
        geometry = feature["geometry"]
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for polygon in polygons:
            exterior = subsample_ring(polygon[0])
            holes = [subsample_ring(hole) for hole in polygon[1:]]
            for clipped in clip_ring_to_horizon(exterior):
                path = ring_to_path(clipped)
                if path:
                    paths.append(path)
            for hole in holes:
                for clipped in clip_ring_to_horizon(hole):
                    path = ring_to_path(clipped)
                    if path:
                        paths.append(path)
    return paths


PALETTES = {
    "dark": {
        "ocean_inner": "#1d6a70",
        "ocean_outer": "#0a2e46",
        "land_fill": "#3f9d8f",
        "land_edge": "#7fd8c4",
        "graticule_stroke": "#8fe0ff",
        "graticule_equator_stroke": "#aeeaff",
        "halo": "#69d8ff",
        "orbit": "#79d9ff",
        "globe_rim": "#9adfff",
        "bg": "transparent",
    },
    "light": {
        "ocean_inner": "#d8f0ef",
        "ocean_outer": "#b7dede",
        "land_fill": "#3c8d80",
        "land_edge": "#27655d",
        "graticule_stroke": "#2f7d86",
        "graticule_equator_stroke": "#1f6b74",
        "halo": "#4db6c9",
        "orbit": "#3c9fae",
        "globe_rim": "#2f7d86",
        "bg": "transparent",
    },
}

SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 520" role="img" aria-hidden="true" focusable="false">
  <!-- Generated by tools/generate_auth_globe.py — do not edit by hand.
       Data: Natural Earth 1:110m land (public domain), orthographic
       projection centered at 105E/30N, graticule every 30 degrees. -->
  <style>
    .globe-orbit-spin {{ animation: globe-orbit 18s linear infinite; transform-origin: 260px 262px; }}
    .globe-halo {{ animation: globe-halo 14s ease-in-out infinite alternate; }}
    @keyframes globe-orbit {{ to {{ transform: rotate(360deg); }} }}
    @keyframes globe-halo {{ from {{ opacity: .55; }} to {{ opacity: 1; }} }}
    @media (prefers-reduced-motion: reduce) {{
      .globe-orbit-spin, .globe-halo {{ animation: none; }}
    }}
  </style>
  <defs>
    <radialGradient id="ocean" cx="38%" cy="32%" r="80%">
      <stop offset="0%" stop-color="{ocean_inner}"/>
      <stop offset="100%" stop-color="{ocean_outer}"/>
    </radialGradient>
    <clipPath id="sphere"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>
  </defs>
  <g class="globe-halo" fill="none">
    <circle cx="{cx}" cy="{cy}" r="{halo_r}" stroke="{halo}" stroke-opacity=".16" stroke-width="10"/>
    <circle cx="{cx}" cy="{cy}" r="{halo_r2}" stroke="{halo}" stroke-opacity=".08" stroke-width="2"/>
  </g>
  <g fill="none" transform="rotate(-18 {cx} {cy})">
    <g class="globe-orbit-spin">
      <ellipse cx="{cx}" cy="{cy}" rx="{orbit_rx}" ry="{orbit_ry}"
        stroke="{orbit}" stroke-opacity=".38" stroke-width="1.4" stroke-dasharray="3 9" stroke-linecap="round"/>
    </g>
  </g>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#ocean)" stroke="{globe_rim}" stroke-opacity=".55" stroke-width="1.5"/>
  <g clip-path="url(#sphere)">
    <g fill="none" stroke="{graticule_stroke}" stroke-opacity=".28" stroke-width="1">
      {graticule_paths}
    </g>
    <g fill="{land_fill}" stroke="{land_edge}" stroke-opacity=".8" stroke-width="1" fill-opacity=".92">
      {land_paths}
    </g>
    <path d="M {eq_x1:.1f} {eq_y1:.1f} A {r} {r} 0 0 1 {eq_x2:.1f} {eq_y2:.1f}" fill="none" stroke="{graticule_equator_stroke}" stroke-opacity=".45" stroke-width="1.6"/>
  </g>
</svg>
"""


def equator_arc() -> tuple[float, float, float, float]:
    """Screen-space arc of the equator inside the visible hemisphere."""
    points = []
    for lon in range(-180, 181):
        projected = project(lon, 0.0)
        if projected:
            points.append(projected)
    if not points:
        return (CX - R, CY, CX + R, CY)
    return (points[0][0], points[0][1], points[-1][0], points[-1][1])


def render(palette: dict, graticule: list[str], land: list[str]) -> str:
    eq_x1, eq_y1, eq_x2, eq_y2 = equator_arc()
    return SVG_TEMPLATE.format(
        cx=f"{CX:.0f}",
        cy=f"{CY:.0f}",
        r=f"{R:.0f}",
        halo_r=f"{R + 14:.0f}",
        halo_r2=f"{R + 30:.0f}",
        orbit_rx=f"{R + 44:.0f}",
        orbit_ry=f"{R * 0.30:.0f}",
        graticule_paths="\n      ".join(f'<path d="{item}"/>' for item in graticule),
        land_paths="\n      ".join(f'<path d="{item}"/>' for item in land),
        eq_x1=eq_x1,
        eq_y1=eq_y1,
        eq_x2=eq_x2,
        eq_y2=eq_y2,
        **palette,
    )


def main() -> None:
    payload = load_land()
    graticule = graticule_paths()
    land = land_paths(payload)
    print(f"land paths: {len(land)}, graticule segments: {len(graticule)}")
    for theme, palette in PALETTES.items():
        target = OUT_DIR / f"auth-globe-{theme}.svg"
        target.write_text(render(palette, graticule, land), encoding="utf-8")
        print(f"wrote {target} ({target.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
