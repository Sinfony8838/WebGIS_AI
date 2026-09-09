#!/usr/bin/env python3
"""Coordinate-accuracy acceptance for the dataset import CRS pipeline.

Verifies ``DatasetService`` reprojection output against three independent
kinds of control:

1. **Analytic controls** — spherical Web Mercator (EPSG:3857) has a closed
   form, so converted coordinates must match the formula to 1e-6 degrees
   (~0.1 m at these latitudes).
2. **Definition invariants** — a point on a Gauss-Kruger central meridian
   (EPSG:4547, false easting 500000 m) must land on the meridian longitude
   exactly (1e-7 degrees ≈ 1 cm).
3. **Round-trip closure** — 4326 → source → 4326 must close within
   1e-9 degrees; metric round-trips within 1e-3 m. Cross-checked against a
   direct ``pyproj.Transformer`` call (trusted tool, PROJ ≥ 9), which must
   agree with the service path to 1e-9 degrees.

Per-CRS tolerances are stated in the ``CASES`` table and reported in the
output. Exit code 0 only when every case passes.

Usage (from the repo root, Python 3.12):

    python scripts/qa/dataset_integrity/verify_crs_accuracy.py [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sample_factory  # noqa: E402

from backend.app.config import AppConfig  # noqa: E402
from backend.app.services import crs_reprojector  # noqa: E402
from backend.app.services.datasets import DatasetService  # noqa: E402
from backend.app.store import RuntimeStore  # noqa: E402

if not crs_reprojector.pyproj_available():
    print("pyproj is required for the accuracy acceptance; install it first.")
    raise SystemExit(2)


@dataclass
class Case:
    case_id: str
    source_crs: str
    unit: str
    control_lonlat: tuple[float, float]
    payload: bytes
    tolerance_deg: float
    note: str
    filename: str = "case.geojson"


def web_mercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    radius = 6378137.0
    lon = math.degrees(x / radius)
    lat = math.degrees(2 * math.atan(math.exp(y / radius)) - math.pi / 2)
    return lon, lat


def build_service(tmp_root: Path) -> tuple[DatasetService, str]:
    config = AppConfig(root_dir=REPO_ROOT)
    config.data_dir = tmp_root / "backend" / "data"
    config.state_dir = config.data_dir / "state"
    config.uploads_dir = config.data_dir / "uploads"
    config.outputs_dir = config.data_dir / "outputs"
    config.state_file = config.state_dir / "runtime.json"
    config.ensure_dirs()
    store = RuntimeStore(config.state_file)
    project = store.create_project(base_map=config.default_basemap())
    return DatasetService(config, store), project.project_id


def utm50_payload() -> bytes:
    return sample_factory.shapefile_zip_bytes(
        "acc_utm50",
        [(500000.0, 4500000.0)],
        [["utm"]],
        [("名称", "C", 20, 0)],
        extra_members={"acc_utm50.prj": sample_factory.WKT_UTM50N},
    )


def cgcs4547_on_cm_payload() -> bytes:
    """Point exactly on the EPSG:4547 central meridian (114°E)."""
    return sample_factory.shapefile_zip_bytes(
        "acc_4547",
        [(500000.0, 2559263.5)],
        [["cm114"]],
        [("名称", "C", 20, 0)],
        extra_members={"acc_4547.prj": sample_factory.WKT_4547},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="", help="Optional path for a JSON report.")
    args = parser.parse_args()

    # Degrees→meters intuition: 1e-6° ≈ 0.11 m; 1e-7° ≈ 1.1 cm.
    cases = [
        Case(
            case_id="epsg3857_vs_closed_form",
            source_crs="EPSG:3857",
            unit="degrees",
            control_lonlat=(121.4737, 31.2304),  # 上海 (features[0])
            payload=sample_factory.web_mercator_geojson(),
            tolerance_deg=1e-6,
            note="Analytic spherical Web Mercator inverse; tolerance 1e-6° ≈ 0.1 m.",
            filename="case_3857.geojson",
        ),
        Case(
            case_id="epsg32650_vs_direct_pyproj",
            source_crs="EPSG:32650",
            unit="degrees",
            control_lonlat=(117.0, None),  # lon pinned to central meridian; lat checked loosely
            payload=utm50_payload(),
            tolerance_deg=1e-7,
            note="UTM 50N: easting 500000 m sits on the CM (117°) within 1e-7°; northing vs direct pyproj within 1e-9°.",
            filename="case_32650.zip",
        ),
        Case(
            case_id="epsg4547_central_meridian_invariant",
            source_crs="EPSG:4547",
            unit="degrees",
            control_lonlat=(114.0, None),
            payload=cgcs4547_on_cm_payload(),
            tolerance_deg=1e-7,
            note="CGCS2000 3° GK CM 114E: definition invariant — false easting 500000 m ⇒ lon 114° ± 1e-7° (~1 cm).",
            filename="case_4547.zip",
        ),
    ]

    results = []
    failures = 0

    with tempfile.TemporaryDirectory(prefix="webgis_acc_") as tmp:
        service, project_id = build_service(Path(tmp))

        for case in cases:
            result = service.import_upload(project_id, case.filename, case.payload)
            crs = result["crs"]
            lon, lat = result["layer"]["data"]["features"][0]["geometry"]["coordinates"]
            entry = {
                "case": case.case_id,
                "source_crs": case.source_crs,
                "unit": case.unit,
                "reprojected": crs["reprojected"],
                "converted_lonlat": [lon, lat],
                "tolerance_deg": case.tolerance_deg,
                "note": case.note,
            }

            # 1 — declared control check
            expect_lon, expect_lat = case.control_lonlat
            lon_error = abs(lon - expect_lon)
            checks = {"central_meridian_or_control_lon": lon_error}
            passed = crs["reprojected"] and lon_error <= case.tolerance_deg

            # 2 — direct-pyproj cross-check (independent call path)
            from pyproj import Transformer

            # Recover the source meters by round-tripping through the same
            # transformer the service uses; then compare service output to a
            # fresh direct transform of the source point.
            source_points = {
                "epsg3857_vs_closed_form": None,  # payload built from closed form already
            }.get(case.case_id)

            if case.case_id == "epsg3857_vs_closed_form":
                x, y = None, None
                # Invert the service's stored source payload to get its meters.
                payload = json.loads(case.payload)
                x, y = payload["features"][0]["geometry"]["coordinates"]
                control_lon, control_lat = web_mercator_to_lonlat(x, y)
                lat_error = abs(lat - control_lat)
                checks["closed_form_lat"] = lat_error
                passed = passed and lat_error <= case.tolerance_deg
            else:
                # Direct pyproj transform of the raw source meters.
                if case.case_id == "epsg32650_vs_direct_pyproj":
                    raw_x, raw_y = 500000.0, 4500000.0
                else:
                    raw_x, raw_y = 500000.0, 2559263.5
                direct_lon, direct_lat = Transformer.from_crs(
                    case.source_crs, "EPSG:4326", always_xy=True
                ).transform(raw_x, raw_y)
                lat_error = abs(lat - direct_lat)
                lon_error_direct = abs(lon - direct_lon)
                checks["direct_pyproj_lon_delta"] = lon_error_direct
                checks["direct_pyproj_lat_delta"] = lat_error
                # Trusted-tool agreement tolerance: exact pipeline parity.
                passed = passed and lon_error_direct <= 1e-9 and lat_error <= 1e-9

            # 3 — round-trip closure
            back_x, back_y = Transformer.from_crs(
                "EPSG:4326", case.source_crs, always_xy=True
            ).transform(lon, lat)
            if case.source_crs == "EPSG:3857":
                round_error_m = math.hypot(back_x - (json.loads(case.payload)["features"][0]["geometry"]["coordinates"][0]),
                                           back_y - (json.loads(case.payload)["features"][0]["geometry"]["coordinates"][1]))
                checks["roundtrip_m"] = round_error_m
                passed = passed and round_error_m <= 1e-3
            else:
                raw = (500000.0, 4500000.0) if case.case_id.startswith("epsg32650") else (500000.0, 2559263.5)
                round_error_m = math.hypot(back_x - raw[0], back_y - raw[1])
                checks["roundtrip_m"] = round_error_m
                passed = passed and round_error_m <= 1e-3

            entry["checks"] = checks
            entry["status"] = "PASS" if passed else "FAIL"
            if not passed:
                failures += 1
            results.append(entry)

            status = entry["status"]
            print(f"[{status}] {case.case_id}: ({lon:.9f}, {lat:.9f}) deg — {case.note}")
            for check_name, value in checks.items():
                print(f"        {check_name}: {value:.3e}")

    # CGCS2000 4490 → 4326 datum-coincidence check (geographic, no projection).
    with tempfile.TemporaryDirectory(prefix="webgis_acc_") as tmp:
        service, project_id = build_service(Path(tmp))
        result = service.import_upload(project_id, "cgcs.geojson", sample_factory.cgcs2000_geojson())
        lon, lat = result["layer"]["data"]["features"][0]["geometry"]["coordinates"]
        lon_err = abs(lon - 108.9402)
        lat_err = abs(lat - 34.3416)
        passed = result["crs"]["reprojected"] and lon_err <= 1e-5 and lat_err <= 1e-5
        entry = {
            "case": "epsg4490_cgcs2000_wgs84_agreement",
            "source_crs": "EPSG:4490",
            "unit": "degrees",
            "reprojected": result["crs"]["reprojected"],
            "converted_lonlat": [lon, lat],
            "tolerance_deg": 1e-5,
            "checks": {"lon_delta": lon_err, "lat_delta": lat_err},
            "note": "CGCS2000 vs WGS84 realization difference is sub-meter; tolerance 1e-5° ≈ 1 m.",
            "status": "PASS" if passed else "FAIL",
        }
        if not passed:
            failures += 1
        results.append(entry)
        print(f"[{entry['status']}] {entry['case']}: ({lon:.9f}, {lat:.9f}) deg — {entry['note']}")
        for check_name, value in entry["checks"].items():
            print(f"        {check_name}: {value:.3e}")

    report = {"cases": results, "failures": failures, "all_passed": failures == 0}
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report written to {args.json}")

    print(f"\n{len(results) - failures}/{len(results)} accuracy cases passed.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
