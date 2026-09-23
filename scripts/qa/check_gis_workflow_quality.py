"""Real PyQGIS GIS regression checks; isolated files only, no server/API or production state."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.services.pyqgis_worker import PyQgisWorkerManager

def main():
    # Keep NumPy-dependent QA libraries out of the spawned QGIS bootstrap process.
    from pyproj import Geod
    from shapely.geometry import shape, Point
    from shapely.ops import unary_union
    parser = argparse.ArgumentParser()
    parser.add_argument("--qgis-root", default=r"D:\QGIS 3.40.10")
    parser.add_argument("--report", default=".claude/qa/gis-real-qgis-report.json")
    args = parser.parse_args()
    data = Path(tempfile.mkdtemp(prefix="webgis_gis_quality_"))
    os.environ["WEBGIS_AI_DATA_DIR"] = str(data)
    uploads = data / "uploads" / "qa"
    uploads.mkdir(parents=True)
    manager = PyQgisWorkerManager(workflows_root=data / "workflows", qgis_root=args.qgis_root,
                                 startup_timeout=180, step_timeout=120)
    geod = Geod(ellps="WGS84")
    report = {"data_dir": str(data), "checks": []}


    def call(wf, sid, op, params):
        result = manager.run_step(wf, {"id": sid, "op": op, "params": params})
        assert result["status"] == "success", result
        return result["outputs"]


    def load(wf, collection):
        path = uploads / f"{wf}.geojson"
        path.write_text(json.dumps(collection), encoding="utf-8")
        return call(wf, "load", "load_layer", {"source": f"upload:qa/{path.name}", "project_id": "qa"})["layer"]


    def export(wf, layer):
        output = call(wf, "export", "export_geojson", {"input": layer, "name": "result", "target_crs": "EPSG:4326"})
        return json.loads(Path(output["geojson"]).read_text(encoding="utf-8"))


    def points(coords, props=None):
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": props[i] if props else {"id": i, "mag": 5},
             "geometry": {"type": "Point", "coordinates": p}} for i, p in enumerate(coords)]}


    def buffer_check(wf, collection, centers, dissolve=False, projected=False):
        layer = load(wf, collection)
        if projected:
            layer = call(wf, "project", "reproject", {"input": layer, "target_crs": "EPSG:3857"})["layer"]
        buffered = call(wf, "buffer", "buffer", {"input": layer, "distance": 20000, "segments": 16, "dissolve": dissolve})
        output = export(wf, buffered["layer"])
        geom = unary_union([shape(f["geometry"]) for f in output["features"]])
        assert geom.is_valid and not geom.is_empty
        polygons = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        vertices = []
        for polygon in polygons:
            ring = list(polygon.exterior.coords)
            for a, b in zip(ring, ring[1:]):
                vertices.extend([(a[0] + (b[0] - a[0]) * fraction,
                                  a[1] + (b[1] - a[1]) * fraction) for fraction in (0, .25, .5, .75)])
        distances = [min(geod.inv(lon, lat, xy[0], xy[1])[2] for lon, lat in centers) for xy in vertices]
        error = max(abs(distance / 20000 - 1) for distance in distances)
        assert error <= .005, (wf, min(distances), max(distances), error)
        assert all(geom.covers(Point(center)) for center in centers)
        report["checks"].append({"case": wf, "pass": True, "output_features": len(output["features"]),
                                 "min_m": min(distances), "max_m": max(distances), "max_error_pct": 100 * error})


    try:
        for lat in (0, 37, 60):
            buffer_check(f"wf_lat_{lat}", points([[137, lat]]), [(137, lat)])
        buffer_check("wf_projected", points([[137, 37]]), [(137, 37)], projected=True)
        buffer_check("wf_dissolved", points([[137, 37], [137.1, 37.05]]), [(137, 37), (137.1, 37.05)], dissolve=True)
        buffer_check("wf_separate", points([[137, 37], [137.1, 37.05]]), [(137, 37), (137.1, 37.05)])
        multi = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"id": "multi"},
                 "geometry": {"type": "MultiPoint", "coordinates": [[137, 37], [137.1, 37.05]]}}]}
        buffer_check("wf_multi", multi, [(137, 37), (137.1, 37.05)])
        fixture = json.loads((ROOT / "backend/tests/fixtures/gis/usgs_noto_20240101.geojson").read_text(encoding="utf-8"))
        centers = [f["geometry"]["coordinates"][:2] for f in fixture["features"]]
        buffer_check("wf_noto", fixture, centers, dissolve=True)

        for kind, coordinates in [
            ("LineString", [[137, 37], [137.05, 37.05]]),
            ("Polygon", [[[137, 37], [137.02, 37], [137.02, 37.02], [137, 37.02], [137, 37]]]),
        ]:
            wf = "wf_" + kind.lower()
            collection = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"id": kind},
                          "geometry": {"type": kind, "coordinates": coordinates}}]}
            layer = load(wf, collection)
            buffered = call(wf, "buffer", "buffer", {"input": layer, "distance": 20000})
            output = export(wf, buffered["layer"])
            assert all(shape(f["geometry"]).is_valid for f in output["features"])
            report["checks"].append({"case": wf, "pass": True})

        wf = "wf_classify_noto"
        layer = load(wf, fixture)
        classified = call(wf, "classify", "classify", {"input": layer, "field": "mag", "classes": 3, "method": "equal", "output_field": "mag_class"})
        assert classified["breaks"] == [4.5, 5.5, 6.5, 7.5]
        output = export(wf, classified["layer"])
        assert len(output["features"]) == 35
        histogram = [0, 0, 0]
        for f in output["features"]:
            mag, actual = f["properties"]["mag"], f["properties"]["mag_class"]
            expected = 0 if mag < 5.5 else 1 if mag < 6.5 else 2
            assert actual == expected, f
            histogram[actual] += 1
        report["checks"].append({"case": wf, "pass": True, "histogram": histogram, "breaks": classified["breaks"]})

        wf = "wf_nulls"
        collection = points([[137 + i / 100, 37] for i in range(6)],
                            [{"震级": value} for value in [None, "bad", "4.5", "5.5", "6.5", "7.5"]])
        layer = load(wf, collection)
        classified = call(wf, "classify", "classify", {"input": layer, "field": "震级", "classes": 3, "method": "equal", "output_field": "class_id"})
        output = export(wf, classified["layer"])
        assert [f["properties"]["class_id"] for f in output["features"]] == [None, None, 0, 1, 2, 2]
        report["checks"].append({"case": wf, "pass": True})
        report["passed"] = True
    finally:
        manager.shutdown()
        destination = Path(args.report)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
