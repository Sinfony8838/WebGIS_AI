"""Pure-Python helpers to detect the CRS of an uploaded dataset.

We avoid hard deps (pyproj is optional) so a vanilla install can still
import data. Only the *detection* path is mandatory; reprojection lives
in :mod:`backend.app.services.crs_reprojector` and degrades gracefully
when pyproj is missing.

Supported detection paths:

* GeoJSON ``crs`` member (RFC 7946 deprecates this but real-world QGIS /
  ogr2ogr exports still carry it). We parse the OGC-style
  ``{"type":"name","properties":{"name":"urn:ogc:def:crs:EPSG::4326"}}``
  and the older ``{"properties":{"code":4326}}`` shape.
* Shapefile ``.prj`` sidecar — a WKT string from which we extract
  ``AUTHORITY["EPSG","XXXX"]`` (case-insensitive).
* Heuristic check for "this looks like projected meters not lon/lat" to
  reject obviously broken CSV uploads before they end up rendered in
  the Pacific Ocean.

All helpers return canonical ``"EPSG:XXXX"`` strings or ``None``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Optional


_EPSG_RE = re.compile(r"^\s*EPSG\s*:\s*(\d+)\s*$", re.IGNORECASE)

# Common WKT authority pattern: AUTHORITY["EPSG","4326"]. We tolerate
# whitespace and either single or double quotes. The pattern intentionally
# matches the FINAL authority block (i.e. the outermost CS) — when WKT
# nests projected + geographic CRSes, the projected one's AUTHORITY appears
# last in the text. The simple regex below finds the last occurrence.
_WKT_AUTHORITY_RE = re.compile(
    r"""AUTHORITY\s*\[\s*["'](?P<auth>[A-Z0-9]+)["']\s*,\s*["'](?P<code>\d+)["']\s*\]""",
    re.IGNORECASE,
)

# Some PROJCS strings carry "EPSG:XXXX" in a comment or in the projection
# name itself; this is a last-ditch fallback.
_WKT_EPSG_FALLBACK_RE = re.compile(r"EPSG\s*[:_]\s*(\d{4,7})", re.IGNORECASE)


def normalize_epsg(value: Any) -> Optional[str]:
    """Return ``"EPSG:XXXX"`` if ``value`` parses as such, else ``None``."""
    if value is None:
        return None
    if isinstance(value, int):
        if value > 0:
            return f"EPSG:{value}"
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    match = _EPSG_RE.match(text)
    if match:
        return f"EPSG:{int(match.group(1))}"
    # urn:ogc:def:crs:EPSG::4326 (also OGC URI variants)
    if "EPSG" in text.upper():
        # match the trailing digits after the last colon-separator
        tail = re.search(r"(\d{4,7})\s*$", text)
        if tail:
            return f"EPSG:{int(tail.group(1))}"
        embedded = _WKT_EPSG_FALLBACK_RE.search(text)
        if embedded:
            return f"EPSG:{int(embedded.group(1))}"
    return None


def detect_geojson_crs(payload: Any) -> Optional[str]:
    """Inspect a parsed GeoJSON document for an explicit CRS declaration.

    Returns ``None`` if the document does not carry an explicit ``crs``.
    Per RFC 7946 the absence of ``crs`` means EPSG:4326 — but we return
    ``None`` here so callers can distinguish "explicit 4326" from
    "implicit (assumed) 4326" in their CRS report.
    """
    if not isinstance(payload, dict):
        return None
    crs_block = payload.get("crs")
    if not isinstance(crs_block, dict):
        return None
    props = crs_block.get("properties") or {}
    if not isinstance(props, dict):
        return None
    # OGC-style: {"type":"name","properties":{"name":"urn:ogc:def:crs:EPSG::4326"}}
    name = props.get("name")
    if isinstance(name, str):
        guess = normalize_epsg(name)
        if guess:
            return guess
    # Legacy: {"properties":{"code": 4326}}
    code = props.get("code")
    if code is not None:
        guess = normalize_epsg(code)
        if guess:
            return guess
    # Some exports carry crs.type = "EPSG" + crs.properties.code
    crs_type = crs_block.get("type")
    if isinstance(crs_type, str) and crs_type.lower() == "epsg" and code is not None:
        return normalize_epsg(code)
    return None


def parse_wkt_epsg(wkt_text: str) -> Optional[str]:
    """Extract the EPSG code from a `.prj` WKT string (last AUTHORITY wins)."""
    if not isinstance(wkt_text, str) or not wkt_text.strip():
        return None
    last: Optional[str] = None
    for match in _WKT_AUTHORITY_RE.finditer(wkt_text):
        if match.group("auth").upper() == "EPSG":
            last = f"EPSG:{int(match.group('code'))}"
    if last:
        return last
    # Some custom .prj have no AUTHORITY block but mention EPSG in PROJCS name.
    fallback = _WKT_EPSG_FALLBACK_RE.search(wkt_text)
    if fallback:
        return f"EPSG:{int(fallback.group(1))}"
    return None


def detect_shapefile_crs(extract_dir: Path) -> Optional[str]:
    """Locate the first ``.prj`` under ``extract_dir`` and parse its EPSG."""
    if not isinstance(extract_dir, Path) or not extract_dir.exists():
        return None
    for prj in sorted(extract_dir.rglob("*.prj")):
        try:
            text = prj.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        guess = parse_wkt_epsg(text)
        if guess:
            return guess
    return None


def looks_like_projected_meters(values: Iterable[float], *, axis: str) -> bool:
    """Heuristic: do these numbers look like projected meters rather than lon/lat?

    Used by CSV upload to surface a friendly error before features end up
    rendered at (700000°, 4500000°). The threshold is intentionally
    conservative — small projected offsets (a few hundred meters near the
    equator) are indistinguishable from lon/lat and will be accepted.
    """
    axis_lo, axis_hi = ((-180.0, 180.0) if axis == "lon" else (-90.0, 90.0))
    for value in values:
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if not (axis_lo <= v <= axis_hi):
            return True
    return False


def is_wgs84(crs: Optional[str]) -> bool:
    """True iff ``crs`` is EPSG:4326 in canonical form."""
    return crs == "EPSG:4326"
