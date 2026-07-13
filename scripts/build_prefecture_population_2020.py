"""Build a GeoJSON that joins 2020 七普 prefecture population (xlsx)
with the 地级市 boundary polygons (shp).

The output is stored as
    backend/app/data/builtin/population/prefecture_population_2020.geojson
and is used by the VisualQueryService as the in-process backend store.
The script is idempotent: re-running it will overwrite the output.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
import shapefile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "人口课程数据"
OUTPUT_PATH = (
    PROJECT_ROOT
    / "backend"
    / "app"
    / "data"
    / "builtin"
    / "population"
    / "prefecture_population_2020.geojson"
)

XLSX_PATH = DATA_DIR / "全国地级市 2020 七普人口数据.xlsx"
SHP_PATH = (
    DATA_DIR
    / "11_【五六七普人口数据】我国省市两级分年龄、性别的人口"
    / "11_【五六七普人口数据】我国省市两级分年龄、性别的人口"
    / "Shp格式的数据"
    / "七普"
    / "分年龄、性别的人口_地级市等级.shp"
)


PROVINCE_SUFFIXES = (
    "壮族自治区",
    "维吾尔自治区",
    "回族自治区",
    "特别行政区",
    "自治区",
    "省",
    "市",
)

CITY_SUFFIXES = (
    "自治州",
    "地区",
    "市",
    "盟",
    "林区",
    "特区",
    "区",
    "州",
)

ADMIN_SUFFIXES = (
    "示范区",
    "新区",
    "管理区",
    "矿区",
    "工业园区",
)

# Names that may appear with or without the 族 character in administrative
# region names.  We strip them when they occur as a trailing modifier so
# that short forms (e.g. 巴音郭楞州) match long forms (e.g. 巴音郭楞蒙古自治州).
ETHNIC_MODIFIERS = (
    "朝鲜族", "蒙古族", "柯尔克孜族", "哈萨克族", "维吾尔族", "哈尼族",
    "傣族", "黎族", "傈僳族", "佤族", "畲族", "高山族", "拉祜族", "水族",
    "东乡族", "纳西族", "景颇族", "土族", "达斡尔族", "仫佬族", "毛南族",
    "仡佬族", "锡伯族", "羌族", "珞巴族", "基诺族", "赫哲族", "门巴族",
    "乌孜别克族", "俄罗斯族", "裕固族", "京族", "塔塔尔族", "独龙族",
    "鄂伦春族", "鄂温克族", "德昂族", "保安族", "布朗族", "普米族",
    "阿昌族", "怒族", "撒拉族", "塔吉克族",
    "苗族", "彝族", "壮族", "布依族", "侗族", "瑶族", "白族", "土家族",
    "藏族", "回族", "满族",
    "蒙古", "哈萨克", "柯尔克孜", "维吾尔",
    "示范",
)
# Sort by length descending so the longest modifier is matched first.
ETHNIC_MODIFIERS_SORTED = tuple(sorted(set(ETHNIC_MODIFIERS), key=len, reverse=True))


def normalize_province(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text:
        return ""
    for suffix in PROVINCE_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text.replace(" ", "")


def normalize_city_variants(value: Any) -> List[str]:
    """Return candidate normalized forms of a city/prefecture name.

    For prefecture-level names that carry ethnic suffixes in the SHP (for
    example ``延边朝鲜族自治州``), we generate a second form with the
    trailing ``X族`` modifiers removed so the short forms used in the xlsx
    (for example ``延边州``) can still match.
    """
    if value is None:
        return [""]
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text:
        return [""]
    candidates: List[str] = []
    base = text
    for suffix in CITY_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            base = base[: -len(suffix)]
            break
    base = base.replace(" ", "")
    if base:
        candidates.append(base)
    for suffix in ADMIN_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            adminless = base[: -len(suffix)]
            if adminless not in candidates:
                candidates.append(adminless)
            break

    def strip_modifiers(text_value: str) -> str:
        current = text_value
        changed = True
        while changed:
            changed = False
            for modifier in ETHNIC_MODIFIERS_SORTED:
                if current.endswith(modifier) and len(current) > len(modifier):
                    current = current[: -len(modifier)]
                    changed = True
                    break
        return current

    for seed in list(candidates):
        stripped = strip_modifiers(seed)
        if stripped and stripped not in candidates:
            candidates.append(stripped)

    if not candidates:
        candidates.append(base or "")
    return candidates


def normalize(value: Any) -> str:
    """Return the primary normalized form (used for province)."""
    return normalize_province(value)


def load_population_rows(xlsx_path: Path) -> List[Dict[str, Any]]:
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Population xlsx not found: {xlsx_path}")
    workbook = openpyxl.load_workbook(xlsx_path, data_only=True)
    worksheet = workbook.active
    rows_iter = worksheet.iter_rows(min_row=1, values_only=True)
    header = next(rows_iter, None)
    if not header:
        raise ValueError("Population xlsx is empty")
    normalized_header = [str(value or "").strip() for value in header]
    province_idx = next(
        (i for i, name in enumerate(normalized_header) if "省" in name or "市" in name or "自治区" in name and "地" not in name and "人" not in name),
        0,
    )
    city_idx = next(
        (i for i, name in enumerate(normalized_header) if "地级" in name or "城市" in name),
        1,
    )
    population_idx = next(
        (i for i, name in enumerate(normalized_header) if "人口" in name),
        2,
    )

    rows: List[Dict[str, Any]] = []
    for row in rows_iter:
        if row is None or len(row) <= population_idx:
            continue
        province = row[province_idx]
        city = row[city_idx]
        population = row[population_idx]
        if province is None or city is None or population is None:
            continue
        try:
            population_value = int(round(float(population)))
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "province": str(province).strip(),
                "city": str(city).strip(),
                "population": population_value,
            }
        )
    if not rows:
        raise ValueError("Population xlsx did not yield any valid rows")
    return rows


def load_boundary_features(shp_path: Path) -> List[Dict[str, Any]]:
    if not shp_path.exists():
        raise FileNotFoundError(f"Boundary shapefile not found: {shp_path}")
    reader = shapefile.Reader(str(shp_path), encoding="gbk")
    field_names = [field[0] for field in reader.fields[1:]]
    features: List[Dict[str, Any]] = []
    for shape_record in reader.shapeRecords():
        record = dict(zip(field_names, shape_record.record))
        geometry = shape_record.shape.__geo_interface__
        features.append({"properties": record, "geometry": geometry})
    return features


def join_population_to_features(
    population_rows: List[Dict[str, Any]],
    boundary_features: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Match each xlsx row to a boundary feature.

    Returns (matched, unmatched_population).
    """
    boundary_lookup: Dict[str, Dict[str, Any]] = {}
    boundary_by_city: Dict[str, List[Dict[str, Any]]] = {}
    for feature in boundary_features:
        props = feature["properties"]
        province_key = normalize_province(props.get("省级"))
        for city_key in normalize_city_variants(props.get("地名")):
            composite = f"{province_key}|{city_key}"
            boundary_lookup[composite] = feature
            boundary_by_city.setdefault(city_key, []).append(feature)

    matched: List[Dict[str, Any]] = []
    unmatched_population: List[Dict[str, Any]] = []
    for row in population_rows:
        province_norm = normalize_province(row["province"])
        city_variants = normalize_city_variants(row["city"])
        feature: Optional[Dict[str, Any]] = None
        for city_norm in city_variants:
            composite = f"{province_norm}|{city_norm}"
            feature = boundary_lookup.get(composite)
            if feature is not None:
                break
        if feature is None and province_norm and province_norm in city_variants:
            candidates = boundary_by_city.get(province_norm, [])
            if len(candidates) == 1:
                feature = candidates[0]
            elif len(candidates) > 1:
                feature = next(
                    (
                        cand
                        for cand in candidates
                        if normalize_province(cand["properties"].get("省级")) == province_norm
                    ),
                    None,
                )
        if feature is None:
            for city_norm in city_variants:
                candidates = boundary_by_city.get(city_norm, [])
                if len(candidates) == 1:
                    feature = candidates[0]
                    break
        if feature is None:
            unmatched_population.append(row)
            continue
        matched.append({"row": row, "feature": feature})
    return matched, unmatched_population


def format_adm_code(value: Any) -> str:
    try:
        return f"{int(value):06d}"
    except (TypeError, ValueError):
        return str(value or "")


def build_geojson(matched: List[Dict[str, Any]]) -> Dict[str, Any]:
    matched_sorted = sorted(
        matched,
        key=lambda item: (-item["row"]["population"], item["row"]["city"]),
    )
    population_rank_lookup: Dict[Tuple[str, str], int] = {}
    for index, item in enumerate(matched_sorted, start=1):
        row = item["row"]
        province_norm = normalize_province(row["province"])
        for city_norm in normalize_city_variants(row["city"]):
            population_rank_lookup[(province_norm, city_norm)] = index

    features: List[Dict[str, Any]] = []
    for item in matched_sorted:
        row = item["row"]
        boundary_props = item["feature"]["properties"]
        province_norm = normalize_province(row["province"])
        city_variants = normalize_city_variants(row["city"])
        rank: Optional[int] = None
        for city_norm in city_variants:
            rank = population_rank_lookup.get((province_norm, city_norm))
            if rank is not None:
                break
        properties = {
            "name": row["city"],
            "province": row["province"],
            "adm_code": format_adm_code(boundary_props.get("区划码")),
            "population_2020": int(row["population"]),
            "rank_2020": int(rank) if rank is not None else None,
            "unit": "人",
        }
        for keep in ("地级类", "省级类", "省级", "地级"):
            if keep in boundary_props and boundary_props[keep] not in (None, ""):
                properties[keep] = boundary_props[keep]
        geometry = item["feature"]["geometry"]
        if geometry.get("type") == "Polygon":
            geometry = {
                "type": "MultiPolygon",
                "coordinates": [geometry["coordinates"]],
            }
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": geometry,
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "全国地级市 2020 七普人口数据.xlsx + 七普地级市等级.shp",
            "unit": "人",
            "year": 2020,
        },
    }


def verify_top20(geojson: Dict[str, Any], expected_top: List[Tuple[str, int]]) -> List[Dict[str, Any]]:
    """Return a list of any mismatches against the expected Top-N list."""
    features_by_name = {
        str(feature["properties"].get("name") or ""): feature
        for feature in geojson["features"]
    }
    issues: List[Dict[str, Any]] = []
    for index, (expected_name, expected_population) in enumerate(expected_top, start=1):
        feature = features_by_name.get(expected_name)
        if feature is None:
            issues.append(
                {
                    "rank": index,
                    "name": expected_name,
                    "expected_population": expected_population,
                    "issue": "feature_missing",
                }
            )
            continue
        actual_population = feature["properties"].get("population_2020")
        actual_rank = feature["properties"].get("rank_2020")
        if actual_population != expected_population:
            issues.append(
                {
                    "rank": index,
                    "name": expected_name,
                    "expected_population": expected_population,
                    "actual_population": actual_population,
                    "issue": "population_mismatch",
                }
            )
        if actual_rank != index:
            issues.append(
                {
                    "rank": index,
                    "name": expected_name,
                    "expected_rank": index,
                    "actual_rank": actual_rank,
                    "issue": "rank_mismatch",
                }
            )
    return issues


def derive_expected_top(geojson: Dict[str, Any], limit: int = 20) -> List[Tuple[str, int]]:
    sorted_features = sorted(
        geojson["features"],
        key=lambda feature: (
            -float(feature["properties"].get("population_2020") or 0),
            str(feature["properties"].get("name") or ""),
        ),
    )
    return [
        (
            str(feature["properties"].get("name") or ""),
            int(feature["properties"].get("population_2020") or 0),
        )
        for feature in sorted_features[:limit]
    ]


def main() -> int:
    population_rows = load_population_rows(XLSX_PATH)
    boundary_features = load_boundary_features(SHP_PATH)
    matched, unmatched_population = join_population_to_features(
        population_rows, boundary_features
    )
    geojson = build_geojson(matched)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(geojson, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[build_prefecture_population_2020] wrote {OUTPUT_PATH}")
    print(
        f"[build_prefecture_population_2020] matched {len(matched)} / "
        f"{len(population_rows)} population rows, {len(boundary_features)} boundary features"
    )
    if unmatched_population:
        print("[build_prefecture_population_2020] unmatched population rows:")
        for row in unmatched_population:
            print(f"  - {row['province']} / {row['city']} ({row['population']})")

    expected_top20 = derive_expected_top(geojson, 20)
    issues = verify_top20(geojson, expected_top20)
    if issues:
        print("[build_prefecture_population_2020] Top-20 verification FAILED:")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    print("[build_prefecture_population_2020] Top-20 verification PASSED")
    print("[build_prefecture_population_2020] Top-20 (from data):")
    for index, (name, population) in enumerate(expected_top20, start=1):
        print(f"  {index:>2}. {name} {population:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
