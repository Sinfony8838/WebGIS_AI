# -*- coding: utf-8 -*-
"""Ingest natural/human thematic datasets into the one-map catalog.

Adds real-vector datasets derived from local teaching shapefiles under
``人口课程数据/`` and (later) web-sourced GeoJSON.  Idempotent: it owns a
fixed set of dataset ids, removes any prior copies from catalog.json, then
re-appends fresh items.  Run AFTER ``ingest_one_map_data.py``.

Dependency: geopandas + shapely (available in the project env).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

import geopandas as gpd
from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parents[1]
BUILTIN = ROOT / "backend" / "app" / "data" / "builtin"
ONE_MAP = BUILTIN / "one_map"
CATALOG_PATH = ONE_MAP / "catalog.json"

LOCAL_DATA = ROOT / "人口课程数据"

CLIMATE_SHP = LOCAL_DATA / "中国气候类型_矢量" / "extracted" / "qhlx_chn.shp"
CENSUS_PROV_SHP = (
    LOCAL_DATA
    / "11_【五六七普人口数据】我国省市两级分年龄、性别的人口"
    / "11_【五六七普人口数据】我国省市两级分年龄、性别的人口"
    / "Shp格式的数据"
    / "七普"
    / "分年龄、性别的人口_省份等级.shp"
)

CLIMATE_COLORS = {
    "热带季风": "#16a34a",
    "亚热带季风": "#84cc16",
    "温带季风": "#eab308",
    "温带大陆": "#f97316",
    "温带海洋性": "#22c55e",
    "高山高原": "#06b6d4",
}

# Dataset ids this script owns (replaced on every run).
OWNED_IDS = {
    "china_climate_types",
    "china_aging_rate_province",
    "china_major_rivers",
    "china_terrain_steps",
    "china_vegetation_zones",
}


# Hand-traced teaching courses of China's major rivers (lon, lat).  These are
# classroom schematics - recognizable courses, not survey-accurate centerlines.
MAJOR_RIVERS: Dict[str, List[List[float]]] = {
    "长江": [[91.2, 33.4], [98.9, 32.4], [100.2, 29.6], [103.8, 29.0], [106.5, 29.5], [110.9, 30.1], [114.3, 30.6], [117.2, 31.7], [118.8, 32.1], [120.0, 31.5], [121.5, 31.4]],
    "黄河": [[96.0, 34.8], [99.5, 34.5], [102.9, 36.1], [105.5, 37.5], [108.5, 40.3], [111.0, 40.8], [110.5, 39.5], [110.0, 37.5], [109.5, 35.5], [110.5, 34.6], [112.5, 34.7], [114.3, 35.0], [116.0, 36.3], [117.0, 36.7], [118.5, 37.5], [119.0, 37.8]],
    "珠江": [[102.8, 24.9], [104.2, 24.9], [106.7, 25.3], [108.8, 23.9], [110.5, 23.5], [112.8, 23.1], [113.3, 23.1]],
    "黑龙江": [[121.5, 53.3], [124.0, 53.0], [127.0, 52.8], [130.5, 49.2], [134.5, 47.7]],
    "澜沧江": [[94.0, 33.2], [96.5, 31.0], [99.0, 28.5], [100.4, 25.6], [101.5, 22.0], [102.1, 21.2]],
    "雅鲁藏布江": [[82.2, 30.4], [84.5, 29.6], [87.1, 29.3], [91.0, 29.2], [94.1, 29.1], [95.4, 29.4], [96.2, 28.8]],
    "塔里木河": [[78.5, 38.6], [80.3, 40.4], [82.9, 41.2], [85.5, 41.4], [87.2, 41.0], [87.0, 40.0]],
    "辽河": [[119.5, 43.5], [121.5, 42.5], [123.0, 41.8], [122.8, 41.0], [122.3, 40.7]],
    "海河": [[114.5, 38.0], [116.0, 38.5], [117.0, 38.7], [117.8, 39.1], [118.2, 39.3]],
    "淮河": [[112.5, 32.5], [114.0, 32.5], [115.5, 32.3], [117.0, 32.3], [118.5, 32.7], [119.5, 33.2]],
    "怒江": [[96.0, 33.0], [97.5, 30.5], [98.5, 27.5], [98.8, 25.5], [99.0, 24.3]],
    "额尔齐斯河": [[88.1, 49.0], [86.5, 48.5], [85.0, 48.2], [82.5, 49.5], [80.5, 50.0]],
}

# Real river geometry: Natural Earth 50m rivers, clipped to the China boundary.
# Used when the download succeeds; MAJOR_RIVERS above is the offline schematic fallback.
NE_RIVERS_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_rivers_lake_centerlines.geojson"
NE_RIVERS_CACHE = ONE_MAP / "_cache" / "ne_10m_rivers.geojson"

RIVER_NAME_ZH: Dict[str, str] = {
    "Chang Jiang": "长江", "Yangtze": "长江", "Huang": "黄河", "Huang He": "黄河", "Yellow River": "黄河",
    "Heilong Jiang": "黑龙江", "Amur": "黑龙江", "Songhua": "松花江", "Tarim": "塔里木河",
    "Yarkant": "叶尔羌河", "Brahmaputra": "雅鲁藏布江", "Yarlung Tsangpo": "雅鲁藏布江",
    "Yarlung": "雅鲁藏布江", "Dihang": "雅鲁藏布江", "Maquan": "马泉河",
    "Nu": "怒江", "Salween": "怒江", "Jinsha": "金沙江", "Tongtian": "通天河", "Tuotuo": "沱沱河",
    "Lancang": "澜沧江", "Mekong": "澜沧江", "Pearl River": "珠江", "Pearl": "珠江", "Zhu Jiang": "珠江",
    "Xi Jiang": "西江", "Xi": "西江", "Bei Jiang": "北江", "Dong Jiang": "东江",
    "Ertis": "额尔齐斯河", "Ertix": "额尔齐斯河", "Irtysh": "额尔齐斯河",
    "Argun": "额尔古纳河", "Liao": "辽河", "Xiliao": "西辽河", "Hai": "海河", "Huai": "淮河",
    "Han": "汉江", "Gan": "赣江", "Yuan": "沅江", "Dadu": "大渡河", "Yalong": "雅砻江",
    "Nanpan": "南盘江", "Hongshui": "红水河", "Hong": "红河", "Min": "岷江", "Jialing": "嘉陵江",
    "Wei": "渭河", "Fen": "汾河", "Xiang": "湘江", "Ili": "伊犁河", "Qiantang": "钱塘江",
    "Hailar": "海拉尔河", "Xar Moron": "西拉木伦河", "Konqi": "孔雀河", "Sutlej": "象泉河",
    "Shiquan": "狮泉河", "Indus": "狮泉河", "Xun": "浔江", "Nmai": "恩梅开江",
    "Ganges": "恒河", "Yalung": "雅砻江", "Wu": "乌江", "Li": "漓江", "Ying": "颍河",
}

TERRAIN_STEP: Dict[str, str] = {
    "540000": "第一级阶梯（青藏高原）",
    "630000": "第一级阶梯（青藏高原）",
    "650000": "第二级阶梯（内陆高原盆地）",
    "150000": "第二级阶梯（内陆高原盆地）",
    "620000": "第二级阶梯（内陆高原盆地）",
    "640000": "第二级阶梯（内陆高原盆地）",
    "610000": "第二级阶梯（内陆高原盆地）",
    "140000": "第二级阶梯（内陆高原盆地）",
    "510000": "第二级阶梯（内陆高原盆地）",
    "500000": "第二级阶梯（内陆高原盆地）",
    "520000": "第二级阶梯（内陆高原盆地）",
    "530000": "第二级阶梯（内陆高原盆地）",
}

VEGETATION_ZONE: Dict[str, str] = {
    "460000": "热带季雨林",
    "310000": "亚热带常绿阔叶林", "320000": "亚热带常绿阔叶林", "330000": "亚热带常绿阔叶林",
    "340000": "亚热带常绿阔叶林", "350000": "亚热带常绿阔叶林", "360000": "亚热带常绿阔叶林",
    "420000": "亚热带常绿阔叶林", "430000": "亚热带常绿阔叶林", "440000": "亚热带常绿阔叶林",
    "450000": "亚热带常绿阔叶林", "500000": "亚热带常绿阔叶林", "510000": "亚热带常绿阔叶林",
    "520000": "亚热带常绿阔叶林", "530000": "亚热带常绿阔叶林",
    "710000": "亚热带常绿阔叶林", "810000": "亚热带常绿阔叶林", "820000": "亚热带常绿阔叶林",
    "110000": "温带落叶阔叶林", "120000": "温带落叶阔叶林", "130000": "温带落叶阔叶林",
    "370000": "温带落叶阔叶林", "410000": "温带落叶阔叶林", "210000": "温带落叶阔叶林",
    "610000": "温带落叶阔叶林", "140000": "温带落叶阔叶林",
    "150000": "温带草原", "220000": "温带草原", "230000": "温带草原",
    "650000": "温带荒漠", "620000": "温带荒漠", "640000": "温带荒漠",
    "540000": "高寒植被", "630000": "高寒植被",
}

ZONE_COLORS = {
    "热带季雨林": "#16a34a",
    "亚热带常绿阔叶林": "#65a30d",
    "温带落叶阔叶林": "#eab308",
    "温带草原": "#facc15",
    "温带荒漠": "#f59e0b",
    "高寒植被": "#06b6d4",
}

STEP_COLORS = {
    "第一级阶梯（青藏高原）": "#7c3aed",
    "第二级阶梯（内陆高原盆地）": "#a16207",
    "第三级阶梯（东部平原丘陵）": "#16a34a",
}


def round_coords(geom: Any, ndigits: int = 4) -> Any:
    """Round GeoJSON coordinates to ``ndigits`` decimals to shrink file size."""
    if isinstance(geom, dict):
        if isinstance(geom.get("coordinates"), list):
            geom = dict(geom)
            geom["coordinates"] = _round_nested(geom["coordinates"], ndigits)
        return geom
    return geom


def _round_nested(values: Any, ndigits: int) -> Any:
    if isinstance(values, (list, tuple)):
        if values and all(isinstance(v, (int, float)) for v in values):
            return [round(float(v), ndigits) for v in values]
        return [_round_nested(v, ndigits) for v in values]
    return values


def write_geojson(path: Path, features: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"type": "FeatureCollection", "features": features}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def feature_from_row(row, properties: Dict[str, Any], simplify: float = 0.01) -> Dict[str, Any]:
    geom = row.geometry
    if geom is None or geom.is_empty:
        return None
    if simplify:
        geom = geom.simplify(simplify, preserve_topology=True)
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": round_coords(mapping(geom)),
    }


def build_climate_types() -> Dict[str, Any]:
    gdf = gpd.read_file(CLIMATE_SHP, encoding="utf-8")
    gdf = gdf.to_crs("EPSG:4326")
    gdf["geometry"] = gdf.geometry.make_valid()
    gdf = gdf.dissolve(by="name").reset_index()
    features: List[Dict[str, Any]] = []
    for _, row in gdf.iterrows():
        name = str(row["name"])
        feat = feature_from_row(
            row,
            {
                "name": name,
                "climate_zone": name,
                "region_code": f"CN_CLIMATE_{name}",
                "source_year": "derived",
                "source_name": "本地中国气候类型矢量数据",
                "license": "教学用矢量，来源标注 required",
            },
            simplify=0.02,
        )
        if feat is None:
            continue
        color = CLIMATE_COLORS.get(name, "#38bdf8")
        feat["properties"]["__fillColor"] = color
        feat["properties"]["__fillOpacity"] = 0.55
        feat["properties"]["__strokeColor"] = "#0f172a"
        feat["properties"]["__strokeWidth"] = 0.6
        features.append(feat)
    write_geojson(ONE_MAP / "climate" / "china_climate_types.geojson", features)
    return {
        "id": "china_climate_types",
        "name": "中国气候类型分布",
        "category": "climate",
        "source": "builtin:one_map/climate/china_climate_types.geojson",
        "format": "geojson",
        "fields": ["name", "climate_zone", "region_code"],
        "coverage": "China",
        "source_year": "derived",
        "source_name": "本地中国气候类型矢量数据（七气候区）",
        "source_url": "",
        "license": "教学用矢量，来源标注 required",
        "includes_taiwan": True,
        "status": "ready",
        "geometry_type": "MultiPolygon",
        "recommended_template": "",
        "population_fields": [],
        "tags": ["climate", "China", "ready"],
        "description": "China climate zones (热带/亚热带/温带季风、温带大陆、高山高原) from local vector data.",
        "style_field": "",
    }


def build_aging_rate() -> tuple[Dict[str, Any], Dict[str, float]]:
    gdf = gpd.read_file(CENSUS_PROV_SHP, encoding="gbk")
    elderly_cols = [
        "65_69_男", "65_69_女", "70_74_男", "70_74_女", "75_79_男", "75_79_女",
        "80_84_男", "80_84_女", "85及以上男", "85及以上女",
    ]
    youth_cols = [
        "0_男", "0_女", "1_4_男", "1_4_女", "5_9_男", "5_9_女", "10_14_男", "10_14_女",
    ]
    working_cols = [
        "15_19_男", "15_19_女", "20_24_男", "20_24_女", "25_29_男", "25_29_女",
        "30_34_男", "30_34_女", "35_39_男", "35_39_女", "40_44_男", "40_44_女",
        "45_49_男", "45_49_女", "50_54_男", "50_54_女", "55_59_男", "55_59_女",
        "60_64_男", "60_64_女",
    ]
    all_age_cols = youth_cols + working_cols + elderly_cols
    skip = {"省", "省级码", "省类型"}
    features: List[Dict[str, Any]] = []
    shanghai_aging: Dict[str, float] = {}
    for _, row in gdf.iterrows():
        name = str(row["省"])
        adcode = str(row["省级码"])
        total = sum(float(row[c] or 0) for c in all_age_cols)
        elderly = sum(float(row[c] or 0) for c in elderly_cols)
        youth = sum(float(row[c] or 0) for c in youth_cols)
        working = sum(float(row[c] or 0) for c in working_cols)
        aging_rate = round(elderly / total, 4) if total else 0.0
        youth_rate = round(youth / total, 4) if total else 0.0
        feat = feature_from_row(
            row,
            {
                "name": name,
                "adcode": adcode,
                "region_code": adcode,
                "population": int(total),
                "elderly_65plus": int(elderly),
                "aging_rate": aging_rate,
                "youth_rate": youth_rate,
                "source_year": "2020",
                "source_name": "第七次全国人口普查（省市分年龄性别）",
                "license": "普查数据，来源标注 required",
            },
            simplify=0.01,
        )
        if feat is None:
            continue
        if "上海" in name:
            shanghai_aging = {"aging_rate": aging_rate, "total": int(total), "elderly": int(elderly)}
        features.append(feat)
    write_geojson(ONE_MAP / "population" / "china_aging_rate_province.geojson", features)
    item = {
        "id": "china_aging_rate_province",
        "name": "中国省级人口老龄化率（七普）",
        "category": "population",
        "source": "builtin:one_map/population/china_aging_rate_province.geojson",
        "format": "geojson",
        "fields": ["name", "adcode", "population", "elderly_65plus", "aging_rate", "youth_rate"],
        "coverage": "China province-level",
        "source_year": "2020",
        "source_name": "第七次全国人口普查分年龄性别数据",
        "source_url": "https://data.stats.gov.cn/easyquery.htm?cn=E0103",
        "license": "普查数据，来源标注 required",
        "includes_taiwan": True,
        "status": "ready",
        "geometry_type": "MultiPolygon",
        "recommended_template": "population_choropleth",
        "population_fields": ["name", "population", "elderly_65plus"],
        "tags": ["population", "China province-level", "ready"],
        "description": "Provincial 65+ share (老龄化率) computed from the 7th national census age/sex table.",
        "style_field": "aging_rate",
    }
    return item, shanghai_aging


def _fetch_ne_rivers() -> Dict[str, Any]:
    if NE_RIVERS_CACHE.exists():
        return json.loads(NE_RIVERS_CACHE.read_text(encoding="utf-8"))
    request = urllib.request.Request(NE_RIVERS_URL, headers={"User-Agent": "WebGIS-AI data builder"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    NE_RIVERS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    NE_RIVERS_CACHE.write_bytes(body)
    return json.loads(body.decode("utf-8"))


def _build_rivers_real() -> List[Dict[str, Any]]:
    """Clip Natural Earth rivers to the China boundary and translate names."""
    payload = _fetch_ne_rivers()
    prov = gpd.read_file(ONE_MAP / "boundaries" / "china_provinces.geojson")
    prov["geometry"] = prov.geometry.make_valid()
    china = prov.geometry.union_all()
    features: List[Dict[str, Any]] = []
    for feat in payload.get("features", []):
        name = str((feat.get("properties") or {}).get("name") or "").strip()
        if not name:
            continue
        geom = shape(feat.get("geometry") or {})
        if geom.is_empty:
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        clipped = china.intersection(geom)
        if clipped.is_empty:
            continue
        clipped = clipped.simplify(0.01, preserve_topology=True)
        zh = RIVER_NAME_ZH.get(name) or name
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": zh,
                    "name_en": name,
                    "region_code": f"CN_RIVER_{zh}",
                    "source_name": "Natural Earth ne_50m_rivers_lake_centerlines",
                    "source_url": NE_RIVERS_URL,
                    "license": "public domain (Natural Earth)",
                },
                "geometry": round_coords(mapping(clipped)),
            }
        )
    return features


def _build_rivers_schematic() -> List[Dict[str, Any]]:
    features: List[Dict[str, Any]] = []
    for name, coords in MAJOR_RIVERS.items():
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": name,
                    "region_code": f"CN_RIVER_{name}",
                    "source_name": "教学示意主要河流走向（离线）",
                    "license": "derived educational geometry",
                },
                "geometry": {"type": "LineString", "coordinates": [[round(c[0], 3), round(c[1], 3)] for c in coords]},
            }
        )
    return features


def build_major_rivers() -> Dict[str, Any]:
    source_name = "教学示意主要河流走向（离线）"
    source_url = ""
    status = "schematic"
    license_name = "derived educational geometry"
    description = "Major river courses as classroom schematics (offline fallback)."
    try:
        features = _build_rivers_real()
        if features:
            source_name = "Natural Earth ne_10m_rivers_lake_centerlines（裁剪至中国境）"
            source_url = NE_RIVERS_URL
            status = "ready"
            license_name = "public domain (Natural Earth)"
            description = "Major rivers (长江/黄河/黑龙江等) clipped from Natural Earth to the China boundary."
            # Natural Earth omits a few Chinese majors (e.g. 珠江); supplement them
            # with the hand-traced schematic so the teaching map stays complete.
            present = {f["properties"]["name"] for f in features}
            for name, coords in MAJOR_RIVERS.items():
                if name in present:
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "name": name,
                            "name_en": "",
                            "region_code": f"CN_RIVER_{name}",
                            "source_name": "教学示意（Natural Earth 未收录）",
                            "license": "derived educational geometry",
                        },
                        "geometry": {"type": "LineString", "coordinates": [[round(c[0], 3), round(c[1], 3)] for c in coords]},
                    }
                )
        else:
            features = _build_rivers_schematic()
    except Exception as exc:  # network/parse failure -> offline schematic
        print(f"  [rivers] real download failed, using schematic: {exc}")
        features = _build_rivers_schematic()
    write_geojson(ONE_MAP / "hydrology" / "china_major_rivers.geojson", features)
    return {
        "id": "china_major_rivers",
        "name": "中国主要河流" if status == "ready" else "中国主要河流（教学示意）",
        "category": "hydrology",
        "source": "builtin:one_map/hydrology/china_major_rivers.geojson",
        "format": "geojson",
        "fields": ["name", "name_en", "region_code"],
        "coverage": "China",
        "source_year": "2024" if status == "ready" else "schematic",
        "source_name": source_name,
        "source_url": source_url,
        "license": license_name,
        "includes_taiwan": False,
        "status": status,
        "geometry_type": "LineString",
        "recommended_template": "",
        "population_fields": [],
        "tags": ["hydrology", "China", status],
        "description": description,
        "style_field": "",
    }


def _dissolve_provinces_by(field_map: Dict[str, str], label_key: str) -> List[Dict[str, Any]]:
    """Group the bundled china_provinces polygons by a province->zone map."""
    prov_path = ONE_MAP / "boundaries" / "china_provinces.geojson"
    gdf = gpd.read_file(prov_path)
    gdf = gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs != "EPSG:4326" else gdf
    # Province seed polygons self-intersect in places; repair before dissolving.
    gdf["geometry"] = gdf.geometry.make_valid()
    gdf["_zone"] = gdf["adcode"].astype(str).map(field_map).fillna("第三级阶梯（东部平原丘陵）")
    gdf = gdf.dissolve(by="_zone").reset_index()
    features: List[Dict[str, Any]] = []
    for _, row in gdf.iterrows():
        zone = str(row["_zone"])
        feat = feature_from_row(
            row,
            {
                "name": zone,
                label_key: zone,
                "region_code": f"CN_{label_key.upper()}_{zone[:2]}",
                "source_year": "approximated",
                "source_name": "按省级区划归并的教学示意",
                "license": "derived educational geometry",
            },
            simplify=0.02,
        )
        if feat is None:
            continue
        features.append(feat)
    return features


def build_terrain_steps() -> Dict[str, Any]:
    features = _dissolve_provinces_by(TERRAIN_STEP, "terrain_step")
    for feat in features:
        zone = feat["properties"]["terrain_step"]
        feat["properties"]["__fillColor"] = STEP_COLORS.get(zone, "#38bdf8")
        feat["properties"]["__fillOpacity"] = 0.4
        feat["properties"]["__strokeColor"] = "#0f172a"
        feat["properties"]["__strokeWidth"] = 0.6
    write_geojson(ONE_MAP / "terrain" / "china_terrain_steps.geojson", features)
    return {
        "id": "china_terrain_steps",
        "name": "中国地形三级阶梯（教学示意）",
        "category": "terrain",
        "source": "builtin:one_map/terrain/china_terrain_steps.geojson",
        "format": "geojson",
        "fields": ["name", "terrain_step", "region_code"],
        "coverage": "China",
        "source_year": "approximated",
        "source_name": "按省级区划归并的三级阶梯",
        "source_url": "",
        "license": "derived educational geometry",
        "includes_taiwan": True,
        "status": "schematic",
        "geometry_type": "MultiPolygon",
        "recommended_template": "",
        "population_fields": [],
        "tags": ["terrain", "China", "schematic"],
        "description": "Three terrain steps (青藏高原/内陆高原盆地/东部平原丘陵) approximated by dissolving province boundaries.",
        "style_field": "",
    }


def build_vegetation_zones() -> Dict[str, Any]:
    features = _dissolve_provinces_by(VEGETATION_ZONE, "vegetation_zone")
    for feat in features:
        zone = feat["properties"]["vegetation_zone"]
        feat["properties"]["__fillColor"] = ZONE_COLORS.get(zone, "#38bdf8")
        feat["properties"]["__fillOpacity"] = 0.45
        feat["properties"]["__strokeColor"] = "#0f172a"
        feat["properties"]["__strokeWidth"] = 0.6
    write_geojson(ONE_MAP / "vegetation" / "china_vegetation_zones.geojson", features)
    return {
        "id": "china_vegetation_zones",
        "name": "中国自然植被带（教学示意）",
        "category": "vegetation",
        "source": "builtin:one_map/vegetation/china_vegetation_zones.geojson",
        "format": "geojson",
        "fields": ["name", "vegetation_zone", "region_code"],
        "coverage": "China",
        "source_year": "approximated",
        "source_name": "按省级区划归并的植被带",
        "source_url": "",
        "license": "derived educational geometry",
        "includes_taiwan": True,
        "status": "schematic",
        "geometry_type": "MultiPolygon",
        "recommended_template": "",
        "population_fields": [],
        "tags": ["vegetation", "China", "schematic"],
        "description": "Natural vegetation zones (热带季雨林/亚热带常绿阔叶林/温带落叶阔叶林/温带草原/温带荒漠/高寒植被) approximated by dissolving province boundaries.",
        "style_field": "",
    }


def update_catalog(new_items: List[Dict[str, Any]]) -> None:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    items = [item for item in payload.get("items", []) if item.get("id") not in OWNED_IDS]
    items.extend(new_items)
    items.sort(key=lambda item: (item.get("category", ""), item.get("id", "")))
    payload["items"] = items
    payload["generated_by"] = "scripts/ingest_one_map_data.py + scripts/ingest_natural_themes.py"
    CATALOG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> int:
    new_items: List[Dict[str, Any]] = []
    new_items.append(build_climate_types())
    aging_item, shanghai = build_aging_rate()
    new_items.append(aging_item)
    new_items.append(build_major_rivers())
    new_items.append(build_terrain_steps())
    new_items.append(build_vegetation_zones())
    update_catalog(new_items)
    print(f"catalog updated with {len(new_items)} datasets: {[i['id'] for i in new_items]}")
    if shanghai:
        print(
            "Shanghai aging: 65+ rate={:.1%}  total={}  elderly={}".format(
                shanghai["aging_rate"], shanghai["total"], shanghai["elderly"]
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
