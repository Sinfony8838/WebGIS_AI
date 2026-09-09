"""Build the Shanghai age layer from the archived official census table.

Run: python scripts/build_shanghai_age_layer.py
The yearbook's rounded counts are preserved; no street-level interpolation.
"""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend/app/data/builtin/population/shanghai_district_age_2020.json"
BASE = ROOT / "backend/app/data/builtin/one_map/shanghai/shanghai_population_density.geojson"
OUTPUT = BASE.with_name("shanghai_age_60_plus_2020.geojson")

def build_features(table, boundaries):
    rows = table["rows"]
    names = [row[0] for row in rows]
    features = boundaries["features"]
    if len(names) != 16 or len(set(names)) != 16 or set(names) != {f["properties"]["name"] for f in features}:
        raise ValueError("All 16 district names must match exactly")
    indexed = {row[0]: row[1:] for row in rows}
    result = []
    for original in features:
        name = original["properties"]["name"]
        values = [Decimal(str(v)) for v in indexed[name]]
        total, young, working, old, older, oldest = values
        if total <= 0 or min(values) < 0 or not oldest <= older <= old <= total or abs(young + working + old - total) > Decimal("0.02"):
            raise ValueError(f"Invalid age counts: {name}")
        ratio = float((old / total * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        feature = {"type": "Feature", "geometry": deepcopy(original["geometry"]), "properties": {
            "name": name, "region_code": original["properties"]["region_code"],
            "常住人口（万人）": float(total), "60岁及以上（万人）": float(old),
            "60岁及以上占比（%）": ratio, "age_60_plus_pct": ratio,
            "source_year": "2020", "source_name": table["source_name"], "source_url": table["source_url"],
            "boundary_source_url": original["properties"]["boundary_source_url"],
            "method": "60岁及以上 / 常住人口合计 × 100；原数以万人保留2位，比例保留1位小数",
            "limitation": "行政区平均值，不能确定年轻环的街镇边界；几何仅沿用现有区级底图，不用于计算面积"
        }}
        result.append(feature)
    return {"type": "FeatureCollection", "features": result}

def build():
    result = build_features(json.loads(SOURCE.read_text(encoding="utf-8")), json.loads(BASE.read_text(encoding="utf-8")))
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

if __name__ == "__main__":
    build()
