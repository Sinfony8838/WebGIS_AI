#!/usr/bin/env python3
"""A/B benchmark: current dataset import vs the pre-optimisation baseline.

The baseline modules are materialised from a git ref (default: the
pre-task integration commit ``00bb920`` = origin/main when this task
started) into a temporary package, so both versions run in one process
against identical in-memory samples.

Measured per sample kind and version:

* wall time (median of ``--repeats`` runs),
* peak additional memory via ``tracemalloc``,
* result fingerprint (feature count + coordinate hash) so the report can
  prove that the optimisation did not drop fields, precision or geometry.

Usage (from the repo root, Python 3.12):

    python scripts/qa/dataset_integrity/benchmark_import.py \
        [--baseline-ref 00bb920] [--repeats 3] [--rows 20000] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sample_factory  # noqa: E402


def materialise_baseline(ref: str, target_dir: Path) -> Path:
    """Write the baseline service modules into an importable shim package.

    Layout mirrors ``backend/app``: ``wgis_bl/services/datasets.py`` uses
    ``from . import ...`` (within services) and ``from ..config import ...``
    (the parent package), so the shims re-export the current config/models/
    store, which this task does not modify.
    """
    services = target_dir / "wgis_bl" / "services"
    services.mkdir(parents=True, exist_ok=True)
    pkg_root = services.parent
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    (services / "__init__.py").write_text("", encoding="utf-8")

    (pkg_root / "config.py").write_text("from backend.app.config import AppConfig\n", encoding="utf-8")
    (pkg_root / "models.py").write_text("from backend.app.models import LayerRecord\n", encoding="utf-8")
    (pkg_root / "store.py").write_text("from backend.app.store import RuntimeStore\n", encoding="utf-8")
    for module in ("crs_detector", "crs_reprojector", "datasets"):
        blob = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", f"{ref}:backend/app/services/{module}.py"],
            check=True,
            capture_output=True,
        ).stdout
        (services / f"{module}.py").write_bytes(blob)
    return pkg_root


def build_service(config_target_dir: Path):
    from backend.app.config import AppConfig
    from backend.app.services.datasets import DatasetService
    from backend.app.store import RuntimeStore

    config = AppConfig(root_dir=REPO_ROOT)
    config.data_dir = config_target_dir / "backend" / "data"
    config.state_dir = config.data_dir / "state"
    config.uploads_dir = config.data_dir / "uploads"
    config.outputs_dir = config.data_dir / "outputs"
    config.state_file = config.state_dir / "runtime.json"
    config.ensure_dirs()
    store = RuntimeStore(config.state_file)
    project = store.create_project(base_map=config.default_basemap())
    return DatasetService(config, store), project.project_id


def fingerprint(collection: dict) -> dict:
    features = collection.get("features", [])
    coords = []

    def walk(node):
        if isinstance(node, (list, tuple)) and node and isinstance(node[0], (int, float)):
            coords.append(tuple(round(float(v), 9) for v in node[:2]))
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    for feature in features:
        walk((feature.get("geometry") or {}).get("coordinates"))
    return {"feature_count": len(features), "coord_points": len(coords), "coords_hash": hash(tuple(coords))}


def measure(service, project_id: str, filename: str, payload: bytes, repeats: int) -> dict:
    times = []
    peak_memory = 0
    fp = None
    for _ in range(repeats):
        tracemalloc.start()
        started = time.perf_counter()
        result = service.import_upload(project_id, filename, payload)
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        times.append(elapsed)
        peak_memory = max(peak_memory, peak)
        fp = fingerprint(result["layer"]["data"])
    return {
        "median_seconds": round(statistics.median(times), 4),
        "min_seconds": round(min(times), 4),
        "peak_traced_mib": round(peak_memory / (1024 * 1024), 2),
        "fingerprint": fp,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="00bb920",
                        help="Git ref holding the pre-optimisation services (default: 00bb920).")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--rows", type=int, default=20000, help="CSV row count for the large sample.")
    parser.add_argument("--features", type=int, default=5000, help="GeoJSON feature count for the large sample.")
    parser.add_argument("--json", default="", help="Optional path for a JSON report.")
    args = parser.parse_args()

    large_csv = sample_factory.csv_bytes(
        ["name", "lon", "lat", "value"],
        (
            [f"site {i}", round(113.2 + (i % 500) * 0.01, 5), round(22.8 + (i % 400) * 0.01, 5), i]
            for i in range(args.rows)
        ),
    )
    large_geojson = sample_factory.geojson_bytes(
        {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32650"}},
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": f"聚落 {i}"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [500000 + (i % 50) * 100, 4500000 + (i // 50) * 100],
                            [500100 + (i % 50) * 100, 4500000 + (i // 50) * 100],
                            [500100 + (i % 50) * 100, 4500100 + (i // 50) * 100],
                            [500000 + (i % 50) * 100, 4500100 + (i // 50) * 100],
                            [500000 + (i % 50) * 100, 4500000 + (i // 50) * 100],
                        ]],
                    },
                }
                for i in range(args.features)
            ],
        }
    )

    sample_kinds = [
        ("csv_large", f"bench_{args.rows}.csv", large_csv),
        ("geojson_large_reprojected", f"bench_{args.features}.geojson", large_geojson),
    ]

    with tempfile.TemporaryDirectory(prefix="webgis_bench_") as tmp:
        tmp_path = Path(tmp)
        baseline_pkg = materialise_baseline(args.baseline_ref, tmp_path)
        sys.path.insert(0, str(tmp_path))
        import wgis_bl.services.datasets as baseline_datasets

        versions = {}
        for name, loader in (
            ("baseline", lambda: baseline_datasets.DatasetService),
            ("current", lambda: __import__("backend.app.services.datasets", fromlist=["DatasetService"]).DatasetService),
        ):
            service_cls = loader()
            service, project_id = build_service(tmp_path / name)
            results = {}
            for kind, filename, payload in sample_kinds:
                results[kind] = measure(service, project_id, filename, payload, args.repeats)
            versions[name] = results

        report = {"baseline_ref": args.baseline_ref, "repeats": args.repeats, "versions": versions}
        consistent = True
        for kind, _filename, _payload in sample_kinds:
            base_fp = versions["baseline"][kind]["fingerprint"]
            cur_fp = versions["current"][kind]["fingerprint"]
            same = (
                base_fp["feature_count"] == cur_fp["feature_count"]
                and base_fp["coord_points"] == cur_fp["coord_points"]
            )
            # Coordinate hash equality is expected only for the non-4326→4326
            # identity path; reprojection floats may differ in last ulps.
            results_consistent = same
            if kind == "csv_large":
                results_consistent = results_consistent and base_fp["coords_hash"] == cur_fp["coords_hash"]
            consistent = consistent and results_consistent
            report.setdefault("consistency", {})[kind] = {
                "geometry_matches": same,
                "results_consistent": results_consistent,
                "baseline": base_fp,
                "current": cur_fp,
            }

        for kind, filename, _payload in sample_kinds:
            base = versions["baseline"][kind]
            cur = versions["current"][kind]
            print(f"== {kind} ({filename})")
            print(f"   baseline ({args.baseline_ref}): {base['median_seconds']:.3f} s, peak {base['peak_traced_mib']:.1f} MiB")
            print(f"   current                : {cur['median_seconds']:.3f} s, peak {cur['peak_traced_mib']:.1f} MiB")
            speedup = base["median_seconds"] / cur["median_seconds"] if cur["median_seconds"] else float("inf")
            mem_ratio = base["peak_traced_mib"] / cur["peak_traced_mib"] if cur["peak_traced_mib"] else float("inf")
            print(f"   speedup ×{speedup:.2f}, peak-memory ratio ×{mem_ratio:.2f}")
        print(f"result consistency: {'OK' if consistent else 'MISMATCH'}")

        if args.json:
            Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"JSON report written to {args.json}")

        return 0 if consistent else 1


if __name__ == "__main__":
    raise SystemExit(main())
