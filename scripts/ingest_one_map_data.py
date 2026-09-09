"""Build first-pass built-in datasets for the "one map" data catalog.

The script is intentionally dependency-light: it uses only the Python
standard library and already bundled GeoJSON files. Heavy raster downloads
are recorded in ``missing_data_requirements.md`` until the runtime has an
operator-approved data cache location.
"""
from __future__ import annotations

import csv
import json
import math
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
BUILTIN = ROOT / "backend" / "app" / "data" / "builtin"
ONE_MAP = BUILTIN / "one_map"
CACHE = ONE_MAP / "_cache"

NATURAL_EARTH_ADMIN0 = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_admin_0_countries.geojson"
)
NATURAL_EARTH_CITIES = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_110m_populated_places.geojson"
)
NATURAL_EARTH_PORTS = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_10m_ports.geojson"
)
DATAV_SHANGHAI = "https://geo.datav.aliyun.com/areas_v3/bound/310000_full.json"

EARTH_RADIUS_KM = 6371.0088

SPECIAL_REGION_POPULATION = {
    # Population values are census/statistical-yearbook benchmark values used
    # to prevent blank Taiwan/HK/Macao records in classroom choropleths.
    710000: {
        "population": 23561236,
        "source_year": "2020",
        "source_name": "Taiwan household registration statistics",
        "source_url": "https://www.ris.gov.tw/",
    },
    810000: {
        "population": 7413070,
        "source_year": "2021",
        "source_name": "Hong Kong 2021 Population Census",
        "source_url": "https://www.census2021.gov.hk/",
    },
    820000: {
        "population": 682070,
        "source_year": "2021",
        "source_name": "Macao 2021 Population Census",
        "source_url": "https://www.dsec.gov.mo/",
    },
}

SHANGHAI_DISTRICT_STATS = {
    # Population: https://tjj.sh.gov.cn/tjnj/2020rktjnj/fu02.pdf
    # Area (2020): https://tjj.sh.gov.cn/tjnj/2021tjnj/C0202.htm
    # Density is calculated from census population, NOT the year-end density column.
    "310101": (662030, 20.46),
    "310104": (1113078, 54.76),
    "310105": (693051, 38.30),
    "310106": (975707, 36.88),
    "310107": (1239800, 54.83),
    "310109": (757498, 23.48),
    "310110": (1242548, 60.73),
    "310112": (2653489, 370.75),
    "310113": (2235218, 270.99),
    "310114": (1834258, 464.20),
    "310115": (5681512, 1210.41),
    "310116": (822776, 586.05),
    "310117": (1909713, 605.64),
    "310118": (1271424, 670.14),
    "310120": (1140872, 687.39),
    "310151": (637921, 1185.49),
}


class Builder:
    def __init__(self) -> None:
        self.catalog: List[Dict[str, Any]] = []
        self.missing: List[Dict[str, str]] = []

    def build(self) -> None:
        for subdir in ("boundaries", "population", "transport", "shanghai", "themes", "climate", "economy"):
            (ONE_MAP / subdir).mkdir(parents=True, exist_ok=True)
        CACHE.mkdir(parents=True, exist_ok=True)

        self.build_china_provinces()
        self.build_hu_line()
        self.build_world_countries()
        self.build_world_cities()
        self.build_world_ports()
        self.build_shanghai_districts()
        self.add_deferred_requirements()
        self.write_catalog()
        self.write_missing()
        self.validate_outputs()

    def build_china_provinces(self) -> None:
        source_path = BUILTIN / "population" / "china_provinces.geojson"
        data = read_json(source_path)
        features: List[Dict[str, Any]] = []
        for feature in data.get("features", []):
            props = dict(feature.get("properties") or {})
            adcode = int(props.get("adcode") or 0)
            area = number_or_none(props.get("area") or props.get("area_km2"))
            if adcode in SPECIAL_REGION_POPULATION:
                patch = SPECIAL_REGION_POPULATION[adcode]
                props["population"] = patch["population"]
                props["source_year"] = patch["source_year"]
                props["source_name"] = patch["source_name"]
                props["source_url"] = patch["source_url"]
            else:
                props["source_year"] = "2020"
                props["source_name"] = "China 2020 census, bundled province boundary seed"
                props["source_url"] = "https://data.stats.gov.cn/easyquery.htm?cn=E0103"
            props["adcode"] = adcode
            props["region_code"] = str(adcode)
            props["level"] = props.get("level") or "province"
            props["area"] = area
            props["area_km2"] = area
            pop = number_or_none(props.get("population"))
            props["density"] = round(pop / area, 2) if pop and area else number_or_none(props.get("density"))
            props["license"] = "Bundled classroom boundary seed; statistics source attribution required"
            props["includes_taiwan"] = adcode == 710000
            features.append({"type": "Feature", "properties": props, "geometry": feature.get("geometry")})

        output = {"type": "FeatureCollection", "features": features}
        write_json(ONE_MAP / "boundaries" / "china_provinces.geojson", output)
        write_json(ONE_MAP / "population" / "china_province_population_density.geojson", output)
        self.add_catalog(
            "china_provinces",
            "中国省级行政区边界（含台湾）",
            "boundaries",
            "one_map/boundaries/china_provinces.geojson",
            "geojson",
            ["name", "adcode", "region_code", "population", "area", "area_km2", "density"],
            "China province-level",
            "2020",
            "Bundled province boundary seed + China/Taiwan/HK/Macao population statistics",
            "https://data.stats.gov.cn/easyquery.htm?cn=E0103",
            "attribution required",
            True,
            "ready",
            "MultiPolygon",
            "population_choropleth",
        )
        self.add_catalog(
            "china_province_population_density",
            "中国省级人口密度（含台湾）",
            "population",
            "one_map/population/china_province_population_density.geojson",
            "geojson",
            ["name", "population", "area", "density", "adcode", "region_code"],
            "China province-level",
            "2020/2021",
            "China 2020 census; Taiwan/HK/Macao benchmark statistics",
            "https://data.stats.gov.cn/easyquery.htm?cn=E0103",
            "attribution required",
            True,
            "ready",
            "MultiPolygon",
            "population_choropleth",
        )

    def build_hu_line(self) -> None:
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "name": "胡焕庸线",
                        "name_en": "Hu Huanyong Line",
                        "region_code": "CN_HU_LINE",
                        "source_year": "1935",
                        "source_name": "Hu Huanyong demographic dividing line",
                        "source_url": "https://en.wikipedia.org/wiki/Heihe%E2%80%93Tengchong_Line",
                        "license": "derived educational geometry",
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [127.499, 50.249],
                            [98.497, 25.020],
                        ],
                    },
                }
            ],
        }
        write_json(ONE_MAP / "themes" / "hu_huanyong_line.geojson", payload)
        self.add_catalog(
            "hu_huanyong_line",
            "胡焕庸线",
            "themes",
            "one_map/themes/hu_huanyong_line.geojson",
            "geojson",
            ["name", "region_code"],
            "China",
            "1935",
            "Derived classroom line geometry",
            "https://en.wikipedia.org/wiki/Heihe%E2%80%93Tengchong_Line",
            "derived educational geometry",
            True,
            "ready",
            "LineString",
            "",
        )

    def build_world_countries(self) -> None:
        try:
            data = fetch_json(NATURAL_EARTH_ADMIN0, "ne_110m_admin_0_countries.geojson")
        except RuntimeError as exc:
            self.missing_item("世界国家边界", "GeoJSON", "Natural Earth", str(exc), "yes")
            self.missing_item("世界国家人口密度", "GeoJSON/CSV", "Natural Earth POP_EST", "depends on world boundaries", "yes")
            return

        features = []
        rows = []
        includes_taiwan = False
        for feature in data.get("features", []):
            props = feature.get("properties") or {}
            iso3 = clean_code(props.get("ISO_A3") or props.get("ADM0_A3") or props.get("SOV_A3"))
            if not iso3:
                iso3 = clean_code(props.get("ADM0_A3") or props.get("BRK_A3") or props.get("NAME"))
            name = str(props.get("NAME_ZH") or props.get("NAME") or props.get("ADMIN") or iso3)
            name_en = str(props.get("NAME_EN") or props.get("NAME") or props.get("ADMIN") or name)
            population = number_or_none(props.get("POP_EST"))
            area = round(geometry_area_km2(feature.get("geometry")), 2)
            density = round(population / area, 2) if population and area else None
            includes_taiwan = includes_taiwan or iso3 == "TWN" or "Taiwan" in name_en
            out_props = {
                "name": name,
                "name_en": name_en,
                "region_code": iso3,
                "iso_a3": iso3,
                "population": population,
                "area": area,
                "area_km2": area,
                "density": density,
                "gdp_usd_millions": number_or_none(props.get("GDP_MD")),
                "continent": props.get("CONTINENT") or "",
                "source_year": str(props.get("POP_YEAR") or "2019"),
                "source_name": "Natural Earth 110m Admin 0 countries",
                "source_url": NATURAL_EARTH_ADMIN0,
                "license": "public domain",
            }
            features.append({"type": "Feature", "properties": out_props, "geometry": feature.get("geometry")})
            rows.append({
                "name": name,
                "name_en": name_en,
                "region_code": iso3,
                "population": population,
                "area": area,
                "density": density,
                "source_year": out_props["source_year"],
                "source_name": out_props["source_name"],
            })

        world = {"type": "FeatureCollection", "features": features}
        write_json(ONE_MAP / "boundaries" / "world_countries.geojson", world)
        write_json(ONE_MAP / "population" / "world_population_density.geojson", world)
        write_csv(
            ONE_MAP / "population" / "world_population_by_country.csv",
            ["name", "name_en", "region_code", "population", "area", "density", "source_year", "source_name"],
            rows,
        )
        self.add_catalog(
            "world_countries",
            "世界国家边界",
            "boundaries",
            "one_map/boundaries/world_countries.geojson",
            "geojson",
            ["name", "name_en", "region_code", "population", "area", "density"],
            "World country-level",
            "2019",
            "Natural Earth",
            NATURAL_EARTH_ADMIN0,
            "public domain",
            includes_taiwan,
            "ready",
            "MultiPolygon",
            "population_choropleth",
        )
        self.add_catalog(
            "world_population_density",
            "世界国家人口密度",
            "population",
            "one_map/population/world_population_density.geojson",
            "geojson",
            ["name", "population", "area", "density", "region_code"],
            "World country-level",
            "2019",
            "Natural Earth POP_EST",
            NATURAL_EARTH_ADMIN0,
            "public domain",
            includes_taiwan,
            "ready",
            "MultiPolygon",
            "population_choropleth",
        )
        self.add_catalog(
            "world_population_by_country",
            "世界主要国家人口总量 CSV",
            "population",
            "one_map/population/world_population_by_country.csv",
            "csv",
            ["name", "population", "area", "density", "region_code"],
            "World country-level",
            "2019",
            "Natural Earth POP_EST",
            NATURAL_EARTH_ADMIN0,
            "public domain",
            includes_taiwan,
            "ready",
            "",
            "",
        )
        self.catalog[-1]["geometry_source"] = "world_countries"
        self.catalog[-1]["join_key"] = "region_code"

    def build_world_cities(self) -> None:
        try:
            data = fetch_json(NATURAL_EARTH_CITIES, "ne_110m_populated_places.geojson")
        except RuntimeError as exc:
            self.missing_item("世界主要城市点", "GeoJSON", "Natural Earth populated places", str(exc), "yes")
            return
        features = []
        for feature in data.get("features", []):
            props = feature.get("properties") or {}
            out_props = {
                "name": props.get("NAME_ZH") or props.get("NAME") or props.get("name") or "",
                "name_en": props.get("NAME") or props.get("name") or "",
                "region_code": clean_code(props.get("ADM0_A3") or props.get("ISO_A3") or props.get("SOV_A3")),
                "population": number_or_none(props.get("POP_MAX") or props.get("POP_MIN")),
                "source_year": str(props.get("POP_YEAR") or ""),
                "source_name": "Natural Earth populated places",
                "source_url": NATURAL_EARTH_CITIES,
                "license": "public domain",
            }
            features.append({"type": "Feature", "properties": out_props, "geometry": feature.get("geometry")})
        write_json(ONE_MAP / "transport" / "world_major_cities.geojson", {"type": "FeatureCollection", "features": features})
        self.add_catalog(
            "world_major_cities",
            "世界主要城市点",
            "transport",
            "one_map/transport/world_major_cities.geojson",
            "geojson",
            ["name", "name_en", "region_code", "population"],
            "World",
            "Natural Earth latest repo snapshot",
            "Natural Earth",
            NATURAL_EARTH_CITIES,
            "public domain",
            True,
            "ready",
            "Point",
            "",
        )

    def build_world_ports(self) -> None:
        try:
            data = fetch_json(NATURAL_EARTH_PORTS, "ne_10m_ports.geojson")
        except RuntimeError as exc:
            self.missing_item("世界港口点", "GeoJSON", "Natural Earth ports", str(exc), "no")
            return
        features = []
        for feature in data.get("features", []):
            props = feature.get("properties") or {}
            out_props = {
                "name": props.get("name") or props.get("NAME") or "",
                "region_code": clean_code(props.get("natlscale") or props.get("adm0_a3") or props.get("ADM0_A3")),
                "source_name": "Natural Earth ports",
                "source_url": NATURAL_EARTH_PORTS,
                "license": "public domain",
            }
            features.append({"type": "Feature", "properties": out_props, "geometry": feature.get("geometry")})
        write_json(ONE_MAP / "transport" / "world_ports.geojson", {"type": "FeatureCollection", "features": features})
        self.add_catalog(
            "world_ports",
            "世界主要港口点",
            "transport",
            "one_map/transport/world_ports.geojson",
            "geojson",
            ["name", "region_code"],
            "World",
            "Natural Earth latest repo snapshot",
            "Natural Earth",
            NATURAL_EARTH_PORTS,
            "public domain",
            True,
            "ready",
            "Point",
            "",
        )

    def build_shanghai_districts(self) -> None:
        try:
            data = fetch_json(DATAV_SHANGHAI, "datav_shanghai_310000_full.json")
        except RuntimeError as exc:
            self.missing_item("上海区县边界", "GeoJSON", "Datav Aliyun 310000_full", str(exc), "yes")
            self.missing_item("上海人口密度 GeoJSON", "GeoJSON", "上海区县边界 + 2020 人口", "depends on Shanghai boundary", "yes")
            return

        features = []
        for feature in data.get("features", []):
            props = dict(feature.get("properties") or {})
            adcode = str(props.get("adcode") or "")
            population, area = SHANGHAI_DISTRICT_STATS.get(adcode, (None, None))
            density = round(population / area, 2) if population and area else None
            out_props = {
                "name": props.get("name") or "",
                "adcode": adcode,
                "region_code": adcode,
                "level": "district",
                "population": population,
                "area": area,
                "area_km2": area,
                "density": density,
                "center": props.get("center") or [],
                "source_year": "2020",
                "source_name": "上海统计局七普第二号公报（人口）与上海统计年鉴2021表2.2（2020年面积）；Datav边界",
                "source_url": "https://tjj.sh.gov.cn/tjnj/2020rktjnj/fu02.pdf",
                "area_source_url": "https://tjj.sh.gov.cn/tjnj/2021tjnj/C0202.htm",
                "boundary_source_url": DATAV_SHANGHAI,
                "density_method": "2020年11月1日七普常住人口 / 2020年行政区划面积；非年末密度",
                "license": "source attribution required; review before redistribution",
            }
            features.append({"type": "Feature", "properties": out_props, "geometry": feature.get("geometry")})
        payload = {"type": "FeatureCollection", "features": features}
        write_json(ONE_MAP / "boundaries" / "shanghai_districts.geojson", payload)
        write_json(ONE_MAP / "shanghai" / "shanghai_population_density.geojson", payload)
        self.add_catalog(
            "shanghai_districts",
            "上海区县边界",
            "boundaries",
            "one_map/boundaries/shanghai_districts.geojson",
            "geojson",
            ["name", "adcode", "region_code", "population", "area", "density"],
            "Shanghai district-level",
            "2020",
            "上海统计局七普第二号公报（人口）与上海统计年鉴2021表2.2（2020年面积）；Datav边界",
            "https://tjj.sh.gov.cn/tjnj/2020rktjnj/fu02.pdf",
            "source attribution required; review before redistribution",
            False,
            "ready",
            "MultiPolygon",
            "population_choropleth",
        )
        self.add_catalog(
            "shanghai_population_density",
            "上海人口密度 GeoJSON",
            "shanghai",
            "one_map/shanghai/shanghai_population_density.geojson",
            "geojson",
            ["name", "population", "area", "density", "adcode", "region_code"],
            "Shanghai district-level",
            "2020",
            "上海统计局七普第二号公报（人口）与上海统计年鉴2021表2.2（2020年面积）；Datav边界",
            "https://tjj.sh.gov.cn/tjnj/2020rktjnj/fu02.pdf",
            "source attribution required; review before redistribution",
            False,
            "ready",
            "MultiPolygon",
            "population_choropleth",
        )

    def add_deferred_requirements(self) -> None:
        deferred = [
            ("中国市级/县级边界", "GeoJSON", "geoBoundaries CHN ADM2 or official MNR/NBS boundary", "large/needs source quality review", "no"),
            ("中国城市人口数据", "CSV/GeoJSON", "国家数据主要城市年度数据 or city statistical yearbooks", "not reliably exportable without manual source confirmation", "yes"),
            ("中国年降水量数据", "GeoJSON/COG/TIF", "WorldClim v2.1 precipitation zonal stats", "large raster; not bundled in first pass", "no"),
            ("中国 1 月/7 月平均气温数据", "GeoJSON/COG/TIF", "WorldClim v2.1 monthly tavg zonal stats", "large raster; not bundled in first pass", "no"),
            ("中国省级 GDP 数据", "CSV/GeoJSON", "国家数据分省年度 GDP", "requires confirmed NBS export table", "yes"),
            ("中国主要交通线数据", "GeoJSON", "OSM/official railway-road network", "license/source choice needs confirmation", "no"),
            ("世界年降水量数据", "GeoJSON/COG/TIF", "WorldClim v2.1 precipitation by country", "large raster; generate by zonal_stats when cached", "no"),
            ("世界气温数据", "GeoJSON/COG/TIF", "WorldClim v2.1 tavg by country", "large raster; generate by zonal_stats when cached", "no"),
            ("世界夜间灯光数据", "GeoJSON/COG/TIF", "EOG VIIRS annual VNL", "large raster and download policy review required", "no"),
            ("上海市 GDP 数据", "CSV/GeoJSON", "上海统计年鉴/国家数据", "requires official table export", "yes"),
            ("上海轨道交通或中心城区范围", "GeoJSON", "上海开放数据/OSM", "source/license not selected", "no"),
        ]
        for item in deferred:
            self.missing_item(*item)

    def add_catalog(
        self,
        dataset_id: str,
        name: str,
        category: str,
        source: str,
        fmt: str,
        fields: List[str],
        coverage: str,
        source_year: str,
        source_name: str,
        source_url: str,
        license_name: str,
        includes_taiwan: bool,
        status: str,
        geometry_type: str,
        recommended_template: str,
    ) -> None:
        required_population_fields = ["name", "population", "area", "density"]
        self.catalog.append({
            "id": dataset_id,
            "name": name,
            "category": category,
            "source": f"builtin:{source}",
            "format": fmt,
            "fields": fields,
            "coverage": coverage,
            "source_year": source_year,
            "source_name": source_name,
            "source_url": source_url,
            "license": license_name,
            "includes_taiwan": includes_taiwan,
            "status": status,
            "geometry_type": geometry_type,
            "recommended_template": recommended_template,
            "population_fields": required_population_fields if all(field in fields for field in required_population_fields) else [],
            "tags": [category, coverage, status],
            "description": f"{coverage} dataset from {source_name}.",
        })

    def missing_item(self, name: str, fmt: str, source: str, reason: str, manual_required: str) -> None:
        key = (name, fmt, source)
        if any((row["name"], row["format"], row["recommended_source"]) == key for row in self.missing):
            return
        self.missing.append({
            "name": name,
            "format": fmt,
            "recommended_source": source,
            "reason": reason,
            "manual_required": manual_required,
        })

    def write_catalog(self) -> None:
        self.catalog.sort(key=lambda item: (item["category"], item["id"]))
        write_json(
            ONE_MAP / "catalog.json",
            {
                "version": "1.0",
                "generated_by": "scripts/ingest_one_map_data.py",
                "items": self.catalog,
            },
        )

    def write_missing(self) -> None:
        lines = [
            "# One Map Missing Data Requirements",
            "",
            "| Data | Target format | Recommended source | Missing reason | Manual required |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in self.missing:
            lines.append(
                "| {name} | {format} | {recommended_source} | {reason} | {manual_required} |".format(
                    **{key: markdown_cell(value) for key, value in row.items()}
                )
            )
        (ONE_MAP / "missing_data_requirements.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def validate_outputs(self) -> None:
        catalog_path = ONE_MAP / "catalog.json"
        payload = read_json(catalog_path)
        items = payload.get("items", [])
        if not items:
            raise RuntimeError("catalog has no items")
        for item in items:
            source = str(item.get("source") or "")
            if not source.startswith("builtin:one_map/"):
                raise RuntimeError(f"bad catalog source: {source}")
            target = BUILTIN / source[len("builtin:"):]
            if not target.exists():
                raise RuntimeError(f"catalog source missing: {target}")
        china = read_json(ONE_MAP / "population" / "china_province_population_density.geojson")
        taiwan = [
            feature for feature in china.get("features", [])
            if int((feature.get("properties") or {}).get("adcode") or 0) == 710000
        ]
        if not taiwan:
            raise RuntimeError("China province dataset is missing Taiwan")
        props = taiwan[0].get("properties") or {}
        for field in ("name", "population", "area", "density", "adcode"):
            if props.get(field) in (None, ""):
                raise RuntimeError(f"Taiwan field is empty: {field}")


def fetch_json(url: str, cache_name: str) -> Dict[str, Any]:
    cache_path = CACHE / cache_name
    if cache_path.exists():
        return read_json(cache_path)
    request = urllib.request.Request(url, headers={"User-Agent": "WebGIS-AI one-map data builder"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"download failed: {url}: {exc}") from exc
    cache_path.write_bytes(body)
    return json.loads(body.decode("utf-8"))


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def number_or_none(value: Any) -> Optional[float]:
    if value in (None, "", "-99"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if number.is_integer():
        return int(number)
    return number


def clean_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "-99":
        return ""
    return text


def geometry_area_km2(geometry: Any) -> float:
    if not isinstance(geometry, dict):
        return 0.0
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if geom_type == "Polygon" and isinstance(coords, list):
        return polygon_area_km2(coords)
    if geom_type == "MultiPolygon" and isinstance(coords, list):
        return sum(polygon_area_km2(poly) for poly in coords if isinstance(poly, list))
    return 0.0


def polygon_area_km2(polygon: List[Any]) -> float:
    if not polygon:
        return 0.0
    exterior = abs(ring_area_km2(polygon[0]))
    holes = sum(abs(ring_area_km2(ring)) for ring in polygon[1:] if isinstance(ring, list))
    return max(0.0, exterior - holes)


def ring_area_km2(ring: List[Any]) -> float:
    points: List[Tuple[float, float]] = []
    for point in ring:
        if isinstance(point, list) and len(point) >= 2:
            try:
                points.append((math.radians(float(point[0])), math.radians(float(point[1]))))
            except (TypeError, ValueError):
                continue
    if len(points) < 3:
        return 0.0
    if points[0] != points[-1]:
        points.append(points[0])
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(points, points[1:]):
        dlon = lon2 - lon1
        if dlon > math.pi:
            dlon -= 2 * math.pi
        elif dlon < -math.pi:
            dlon += 2 * math.pi
        total += dlon * (2 + math.sin(lat1) + math.sin(lat2))
    return total * EARTH_RADIUS_KM * EARTH_RADIUS_KM / 2.0


def markdown_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> int:
    try:
        Builder().build()
    except Exception as exc:
        print(f"one-map ingest failed: {exc}", file=sys.stderr)
        return 1
    print(f"one-map catalog written to {ONE_MAP / 'catalog.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
