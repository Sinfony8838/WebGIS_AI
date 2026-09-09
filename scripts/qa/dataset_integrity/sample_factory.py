"""Programmatic sample factory for dataset-import integrity QA.

Every sample used by the acceptance tests and the QA scripts is generated
here from deterministic inputs — no binary fixtures live in the repo. The
module only depends on the standard library plus ``pyshp`` (for Shapefile
ZIP samples; guarded so the module imports without it).

Sample kinds
------------
* GeoJSON (FeatureCollection / single Feature / feature list / malformed)
* CSV (UTF-8, UTF-8 BOM, GB18030, UTF-16; Chinese headers; broken rows)
* Shapefile ZIP (with/without .prj, CGCS2000, UTM, GBK DBF, bombs, traversal)
* Image overlays (valid PNG bytes + bound variants)

Each generator returns raw ``bytes`` ready for ``import_upload`` or a
multipart POST. ``build_catalog()`` lists every named sample together with
its expected outcome so docs and the sample generator CLI stay in sync.
"""
from __future__ import annotations

import io
import json
import struct
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# WKT CRS strings used by shapefile .prj sidecars
# ---------------------------------------------------------------------------

WKT_4326 = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]'
)

WKT_4490 = (
    'GEOGCS["CGCS2000",DATUM["China_Geodetic_Coordinate_System_2000",'
    'SPHEROID["CGCS2000",6378137,298.257222101,AUTHORITY["EPSG","1024"]],'
    'AUTHORITY["EPSG","6322"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4490"]]'
)

WKT_3857 = (
    'PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
    'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]],'
    'PROJECTION["Mercator_1SP"],PARAMETER["central_meridian",0],'
    'PARAMETER["scale_factor",1],PARAMETER["false_easting",0],'
    'PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AUTHORITY["EPSG","3857"]]'
)

WKT_UTM50N = (
    'PROJCS["WGS 84 / UTM zone 50N",'
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
    'PARAMETER["central_meridian",117],PARAMETER["scale_factor",0.9996],'
    'PARAMETER["false_easting",500000],PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","32650"]]'
)

# CGCS2000 / 3-degree Gauss-Kruger CM 114E (false easting 500000).
WKT_4547 = (
    'PROJCS["CGCS2000 / 3-degree Gauss-Kruger CM 114E",'
    'GEOGCS["CGCS2000",DATUM["China_Geodetic_Coordinate_System_2000",'
    'SPHEROID["CGCS2000",6378137,298.257222101,AUTHORITY["EPSG","1024"]],'
    'AUTHORITY["EPSG","6322"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
    'PARAMETER["central_meridian",114],PARAMETER["scale_factor",1],'
    'PARAMETER["false_easting",500000],PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","4547"]]'
)

WKT_NO_AUTHORITY = (
    'PROJCS["Custom Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]]],'
    'PROJECTION["Mercator_1SP"],UNIT["metre",1]]'
)


# ---------------------------------------------------------------------------
# GeoJSON
# ---------------------------------------------------------------------------


def geojson_point(
    lon: float,
    lat: float,
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "type": "Feature",
        "properties": dict(properties or {}),
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def geojson_collection(
    features: Sequence[Dict[str, Any]],
    crs: Optional[str] = None,
) -> Dict[str, Any]:
    collection: Dict[str, Any] = {"type": "FeatureCollection", "features": list(features)}
    if crs:
        collection["crs"] = {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{crs.split(':')[1]}"}}
    return collection


def geojson_bytes(
    collection: Dict[str, Any],
    *,
    encoding: str = "utf-8",
    bom: bool = False,
    indent: Optional[int] = None,
) -> bytes:
    text = json.dumps(collection, ensure_ascii=False, indent=indent)
    payload = text.encode(encoding)
    if bom and encoding.lower().startswith("utf-8"):
        payload = b"\xef\xbb\xbf" + payload
    return payload


def valid_points_geojson(count: int = 3, crs: Optional[str] = None) -> bytes:
    """Chinese-named teaching points around Guangzhou (valid WGS84 lon/lat)."""
    base = (113.264, 23.129)
    features = [
        geojson_point(
            base[0] + 0.01 * index,
            base[1] + 0.008 * index,
            {"name": f"教学点 {index + 1}", "班级": "高一(3)班", "人数": 40 + index},
        )
        for index in range(count)
    ]
    return geojson_bytes(geojson_collection(features, crs=crs), indent=2)


def projected_geojson() -> bytes:
    """Explicit UTM50N member with projected meter coordinates."""
    features = [
        geojson_point(500000.0, 4500000.0, {"name": "UTM 点 A"}),
        geojson_point(505000.0, 4501000.0, {"name": "UTM 点 B"}),
    ]
    return geojson_bytes(geojson_collection(features, crs="EPSG:32650"))


def cgcs2000_geojson() -> bytes:
    """Explicit EPSG:4490 (CGCS2000) geographic coordinates near Xi'an."""
    features = [
        geojson_point(108.9402, 34.3416, {"name": "大雁塔", "坐标系": "CGCS2000"}),
        geojson_point(108.9480, 34.2225, {"name": "长安街"}),
    ]
    return geojson_bytes(geojson_collection(features, crs="EPSG:4490"))


def web_mercator_geojson() -> bytes:
    """Explicit EPSG:3857 meter coordinates for Shanghai & Beijing.

    Meter values are produced with the analytic spherical-Web-Mercator
    inverse (R = 6378137), so the acceptance test can compare the service's
    EPSG:3857→4326 output against known degree control points.
    """
    import math

    radius = 6378137.0

    def to_meters(lon: float, lat: float) -> Tuple[float, float]:
        x = math.radians(lon) * radius
        y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * radius
        return round(x, 1), round(y, 1)

    controls = [
        ((121.4737, 31.2304), "上海"),
        ((116.4074, 39.9042), "北京"),
    ]
    features = [
        geojson_point(*to_meters(lon, lat), {"name": name})
        for (lon, lat), name in controls
    ]
    return geojson_bytes(geojson_collection(features, crs="EPSG:3857"))


def null_geometry_geojson() -> bytes:
    """Collection mixing valid points with null-geometry features."""
    features: List[Dict[str, Any]] = [
        geojson_point(113.26, 23.13, {"name": "正常点"}),
        {"type": "Feature", "properties": {"name": "无几何点"}, "geometry": None},
        {"type": "Feature", "properties": {"name": "缺失几何点"}},
    ]
    return geojson_bytes(geojson_collection(features))


def complex_geometry_geojson() -> bytes:
    """MultiPolygon with a hole + GeometryCollection, valid WGS84."""
    outer = [
        [113.0, 23.0],
        [113.5, 23.0],
        [113.5, 23.4],
        [113.0, 23.4],
        [113.0, 23.0],
    ]
    hole = [
        [113.15, 23.1],
        [113.3, 23.1],
        [113.3, 23.25],
        [113.15, 23.25],
        [113.15, 23.1],
    ]
    multi_polygon = {
        "type": "Feature",
        "properties": {"name": "双环面"},
        "geometry": {"type": "MultiPolygon", "coordinates": [[outer, hole], [outer]]},
    }
    geometry_collection = {
        "type": "Feature",
        "properties": {"name": "几何集合"},
        "geometry": {
            "type": "GeometryCollection",
            "geometries": [
                {"type": "Point", "coordinates": [113.2, 23.5]},
                {"type": "LineString", "coordinates": [[113.1, 23.5], [113.4, 23.6]]},
            ],
        },
    }
    return geojson_bytes(geojson_collection([multi_polygon, geometry_collection]))


def conflict_crs_geojson() -> bytes:
    """Declares EPSG:4326 but carries projected-scale coordinates."""
    features = [geojson_point(500000.0, 4500000.0, {"name": "冲突点"})]
    return geojson_bytes(geojson_collection(features, crs="EPSG:4326"))


def suspect_implicit_geojson() -> bytes:
    """No crs member, coordinates out of lon/lat range (projected-like)."""
    features = [geojson_point(3857.0 * 3, 4500000.0, {"name": "可疑点"})]
    return geojson_bytes(geojson_collection(features))


def malformed_json_geojson() -> bytes:
    return b'{"type":"FeatureCollection","features":[{"type":"Feature",'


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def csv_bytes(
    header: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    encoding: str = "utf-8",
    bom: bool = False,
    delimiter: str = ",",
    line_terminator: str = "\r\n",
) -> bytes:
    import csv as _csv

    buffer = io.StringIO(newline="")
    writer = _csv.writer(buffer, delimiter=delimiter, lineterminator=line_terminator)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    payload = buffer.getvalue().encode(encoding)
    if bom and encoding.lower().startswith("utf-8"):
        payload = b"\xef\xbb\xbf" + payload
    return payload


def valid_points_csv(encoding: str = "utf-8", bom: bool = False, count: int = 3) -> bytes:
    header = ["名称", "经度", "纬度", "人数"]
    rows = [
        [f"调查点 {i + 1}", round(113.264 + 0.01 * i, 4), round(23.129 + 0.008 * i, 4), 35 + i]
        for i in range(count)
    ]
    return csv_bytes(header, rows, encoding=encoding, bom=bom)


def mixed_validity_csv(valid: int = 980, invalid: int = 20) -> bytes:
    """Large-ish file: ``valid`` good rows + a tail of broken rows.

    Broken rows cycle through the three failure classes: missing value,
    non-numeric value, out-of-range value.
    """
    header = ["name", "lon", "lat", "value"]
    rows: List[List[Any]] = [
        [f"site {i}", round(113.2 + (i % 50) * 0.01, 5), round(22.8 + (i % 40) * 0.01, 5), i]
        for i in range(valid)
    ]
    for j in range(invalid):
        mode = j % 3
        if mode == 0:
            rows.append([f"bad {j}", "", 23.0, j])
        elif mode == 1:
            rows.append([f"bad {j}", "N/A", 23.0, j])
        else:
            rows.append([f"bad {j}", 181.5, 23.0, j])
    return csv_bytes(header, rows)


def swapped_lonlat_csv() -> bytes:
    """Columns filled the wrong way round: the “lon” column holds latitudes."""
    header = ["name", "lon", "lat"]
    rows = [
        ["A", 23.129, 113.264],
        ["B", 22.55, 113.88],
        ["C", 23.05, 113.75],
    ]
    return csv_bytes(header, rows)


def projected_csv() -> bytes:
    return csv_bytes(
        ["name", "lon", "lat"],
        [["A", 500000, 4500000], ["B", 510000, 4510000]],
    )


def out_of_range_csv() -> bytes:
    return csv_bytes(
        ["name", "lon", "lat"],
        [["A", 200.5, 23.0], ["B", 113.2, 97.0]],
    )


def empty_csv() -> bytes:
    return b""


def header_only_csv() -> bytes:
    return csv_bytes(["name", "lon", "lat"], [])


def quoted_fields_csv() -> bytes:
    return csv_bytes(
        ["名称", "lon", "lat", "备注"],
        [["图书馆, 总馆", 113.264, 23.129, '含"引号"'],
         ["体育馆", 113.301, 23.115, "含\r\n换行"]],
    )


# ---------------------------------------------------------------------------
# Shapefile ZIP
# ---------------------------------------------------------------------------


def shapefile_zip_bytes(
    stem: str,
    points: Sequence[Tuple[float, float]],
    records: Sequence[Sequence[Any]],
    fields: Sequence[Tuple[str, str, int, int]],
    *,
    prj_wkt: Optional[str] = None,
    encoding: str = "utf-8",
    include: Iterable[str] = ("shp", "shx", "dbf"),
    arc_prefix: str = "",
    extra_members: Optional[Dict[str, bytes]] = None,
) -> bytes:
    """Build a zipped single-layer shapefile (requires pyshp)."""
    import shapefile  # type: ignore

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="webgis_factory_") as tmp:
        tmp_path = Path(tmp)
        writer = shapefile.Writer(str(tmp_path / stem), shapeType=shapefile.POINT, encoding=encoding)
        for name, field_type, size, decimals in fields:
            writer.field(name, field_type, size=size, decimal=decimals)
        for (lon, lat), record in zip(points, records):
            writer.point(lon, lat)
            writer.record(*record)
        writer.close()

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for suffix in include:
                path = tmp_path / f"{stem}.{suffix}"
                if path.exists():
                    arcname = f"{arc_prefix}{stem}.{suffix}" if arc_prefix else f"{stem}.{suffix}"
                    archive.write(path, arcname=arcname)
            for name, content in (extra_members or {}).items():
                archive.writestr(name, content)
        return buffer.getvalue()


def valid_shapefile_zip(prj_wkt: Optional[str] = WKT_4326, count: int = 3) -> bytes:
    points = [(113.264 + 0.01 * i, 23.129 + 0.008 * i) for i in range(count)]
    records = [[f"站点 {i + 1}", 20 + i] for i in range(count)]
    fields = [("名称", "C", 40, 0), ("等级", "N", 10, 0)]
    extra = {f"points.prj": prj_wkt} if prj_wkt else None
    return shapefile_zip_bytes("points", points, records, fields, extra_members=extra)


def cgcs2000_projected_zip() -> bytes:
    """EPSG:4547 (CGCS2000 3° Gauss-Kruger CM 114E) meters near Guangzhou."""
    # 113.264E, 23.129N ≈ (500724.5, 2559263.5) m in CM 114E zone.
    points = [(500724.5, 2559263.5), (502000.0, 2560000.0)]
    records = [["控制点 1", "二等"], ["控制点 2", "三等"]]
    fields = [("点名", "C", 40, 0), ("等级", "C", 16, 0)]
    return shapefile_zip_bytes(
        "cgcs_points", points, records, fields, prj_wkt=WKT_4547,
        extra_members={"cgcs_points.prj": WKT_4547},
    )


def gbk_dbf_zip() -> bytes:
    """Shapefile whose DBF text is GBK-encoded (ArcGIS 中文经典写法)."""
    return shapefile_zip_bytes(
        "gbk_points",
        [(113.264, 23.129)],
        [["中文站点名称"]],
        [("名称", "C", 60, 0)],
        encoding="gbk",
        extra_members={"gbk_points.prj": WKT_4326},
    )


def multi_layer_zip() -> bytes:
    """Two independent layers inside one archive — must be rejected as ambiguous."""
    first = shapefile_zip_bytes(
        "layer_a", [(113.2, 23.1)], [["A"]], [("名称", "C", 20, 0)], prj_wkt=WKT_4326,
        extra_members={"layer_a.prj": WKT_4326},
    )
    second = shapefile_zip_bytes(
        "layer_b", [(114.2, 22.5)], [["B"]], [("名称", "C", 20, 0)], prj_wkt=WKT_4326,
        extra_members={"layer_b.prj": WKT_4326},
    )
    inner_a = zipfile.ZipFile(io.BytesIO(first))
    inner_b = zipfile.ZipFile(io.BytesIO(second))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as merged:
        for name in inner_a.namelist():
            merged.writestr(name, inner_a.read(name))
        for name in inner_b.namelist():
            merged.writestr(name, inner_b.read(name))
    return buffer.getvalue()


def missing_sidecar_zip() -> bytes:
    """Shapefile archive missing .shx (only .shp + .dbf)."""
    return shapefile_zip_bytes(
        "nosx", [(113.2, 23.1)], [["A"]], [("名称", "C", 20, 0)],
        include=("shp", "dbf"), extra_members={"nosx.prj": WKT_4326},
    )


def traversal_zip() -> bytes:
    """Entry escaping the extraction directory (zip-slip)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.shp", b"bad")
    return buffer.getvalue()


def empty_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "no shapefile here")
    return buffer.getvalue()


def zip_bomb_bytes(entry_count: int = 2100) -> bytes:
    """More entries than MAX_ZIP_ENTRIES — every entry is tiny."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for index in range(entry_count):
            archive.writestr(f"pad/file_{index:05d}.txt", b"x")
    return buffer.getvalue()


def null_shape_zip() -> bytes:
    """Shapefile mixing valid points with NULL shapes."""
    import shapefile  # type: ignore

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="webgis_factory_") as tmp:
        tmp_path = Path(tmp)
        writer = shapefile.Writer(str(tmp_path / "with_null"), shapeType=shapefile.POINT)
        writer.field("名称", "C", size=40)
        writer.point(113.264, 23.129)
        writer.record("有效点")
        writer.null()
        writer.record("空点")
        writer.point(113.301, 23.115)
        writer.record("第二个有效点")
        writer.close()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for suffix in ("shp", "shx", "dbf"):
                archive.write(tmp_path / f"with_null.{suffix}", arcname=f"with_null.{suffix}")
            archive.writestr("with_null.prj", WKT_4326)
        return buffer.getvalue()


def nested_dir_zip() -> bytes:
    """Shapefile stored in a subdirectory (common in downloaded archives)."""
    inner = shapefile_zip_bytes(
        "nested", [(116.407, 39.904)], [["北京"]], [("名称", "C", 20, 0)], prj_wkt=WKT_4326,
        extra_members={"nested.prj": WKT_4326},
    )
    outer = zipfile.ZipFile(io.BytesIO(inner))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in outer.namelist():
            archive.writestr(f"data/2024/{name}", outer.read(name))
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Images (pure-stdlib PNG writer — no Pillow dependency)
# ---------------------------------------------------------------------------


def png_bytes(width: int = 8, height: int = 8, rgba=(66, 181, 209, 255)) -> bytes:
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw_rows = b"".join(
        b"\x00" + bytes(rgba) * width for _ in range(height)
    )
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", ihdr),
            chunk(b"IDAT", zlib.compress(raw_rows)),
            chunk(b"IEND", b""),
        ]
    )


# ---------------------------------------------------------------------------
# Catalog: named samples + expected outcomes (drives generate_samples.py)
# ---------------------------------------------------------------------------

OK = "导入成功"
FAIL = "导入失败"


def build_catalog() -> List[Dict[str, str]]:
    """Named QA samples with the outcome the acceptance contract expects."""
    return [
        # --- GeoJSON -------------------------------------------------------
        {"id": "geojson_valid", "file": "geojson_valid.geojson", "kind": "GeoJSON",
         "expectation": f"{OK}，3 个要素，中文属性完整，implicit_wgs84"},
        {"id": "geojson_explicit_4326", "file": "geojson_explicit_4326.geojson", "kind": "GeoJSON",
         "expectation": f"{OK}，检测到 EPSG:4326，不触发转换"},
        {"id": "geojson_3857", "file": "geojson_3857.geojson", "kind": "GeoJSON",
         "expectation": f"{OK}，EPSG:3857→4326 转换（有 pyproj 时），坐标落在京沪"},
        {"id": "geojson_utm50", "file": "geojson_utm50.geojson", "kind": "GeoJSON",
         "expectation": f"{OK}，EPSG:32650→4326 转换（有 pyproj 时）"},
        {"id": "geojson_cgcs2000", "file": "geojson_cgcs2000.geojson", "kind": "GeoJSON",
         "expectation": f"{OK}，EPSG:4490→4326（亚米级等同），西安点位"},
        {"id": "geojson_null_geometry", "file": "geojson_null_geometry.geojson", "kind": "GeoJSON",
         "expectation": f"{OK}，1/3 要素，跳过 2 个缺失几何并在报告注明"},
        {"id": "geojson_complex", "file": "geojson_complex.geojson", "kind": "GeoJSON",
         "expectation": f"{OK}，MultiPolygon（带洞）+ GeometryCollection 完整保留"},
        {"id": "geojson_crs_conflict", "file": "geojson_crs_conflict.geojson", "kind": "GeoJSON",
         "expectation": f"{OK} + COORD_RANGE_CONFLICT 警告，坐标保持原值不转换"},
        {"id": "geojson_suspect_implicit", "file": "geojson_suspect_implicit.geojson", "kind": "GeoJSON",
         "expectation": f"{OK} + COORD_RANGE_SUSPECT 警告，不得凭数值改判 CRS"},
        {"id": "geojson_empty", "file": "geojson_empty.geojson", "kind": "GeoJSON",
         "expectation": f"{FAIL}（features 为空），磁盘零残留"},
        {"id": "geojson_malformed", "file": "geojson_malformed.geojson", "kind": "GeoJSON",
         "expectation": f"{FAIL}（JSON 语法错误，中文提示），磁盘零残留"},
        # --- CSV -----------------------------------------------------------
        {"id": "csv_utf8", "file": "csv_utf8.csv", "kind": "CSV",
         "expectation": f"{OK}，中文字段自动识别（经度/纬度）"},
        {"id": "csv_bom", "file": "csv_bom.csv", "kind": "CSV",
         "expectation": f"{OK}，UTF-8 BOM 正确剥离"},
        {"id": "csv_gb18030", "file": "csv_gb18030.csv", "kind": "CSV",
         "expectation": f"{OK}，GBK/GB18030 中文不乱码"},
        {"id": "csv_utf16", "file": "csv_utf16.csv", "kind": "CSV",
         "expectation": f"{OK}，Excel UTF-16 导出可读"},
        {"id": "csv_quoted", "file": "csv_quoted.csv", "kind": "CSV",
         "expectation": f"{OK}，含逗号/引号/换行的引用字段完整"},
        {"id": "csv_mixed_validity", "file": "csv_mixed_validity.csv", "kind": "CSV",
         "expectation": f"{OK}，行报告：980 成功 / 20 跳过并按原因分类"},
        {"id": "csv_swapped", "file": "csv_swapped.csv", "kind": "CSV",
         "expectation": f"{FAIL}，提示疑似经纬度反置（不自动纠正）"},
        {"id": "csv_projected", "file": "csv_projected.csv", "kind": "CSV",
         "expectation": f"{FAIL}，CrsAssumptionError，提示先转 WGS84"},
        {"id": "csv_out_of_range", "file": "csv_out_of_range.csv", "kind": "CSV",
         "expectation": f"{FAIL}，提示坐标越界"},
        {"id": "csv_empty", "file": "csv_empty.csv", "kind": "CSV",
         "expectation": f"{FAIL}（空文件）"},
        {"id": "csv_header_only", "file": "csv_header_only.csv", "kind": "CSV",
         "expectation": f"{FAIL}（没有数据行）"},
        # --- Shapefile ZIP ---------------------------------------------------
        {"id": "zip_wgs84_prj", "file": "zip_wgs84_prj.zip", "kind": "Shapefile ZIP",
         "expectation": f"{OK}，.prj=EPSG:4326，无警告"},
        {"id": "zip_no_prj", "file": "zip_no_prj.zip", "kind": "Shapefile ZIP",
         "expectation": f"{OK} + SHAPEFILE_NO_PRJ 警告"},
        {"id": "zip_utm50_prj", "file": "zip_utm50_prj.zip", "kind": "Shapefile ZIP",
         "expectation": f"{OK}，EPSG:32650→4326 转换（有 pyproj 时）"},
        {"id": "zip_cgcs2000_4547", "file": "zip_cgcs2000_4547.zip", "kind": "Shapefile ZIP",
         "expectation": f"{OK}，EPSG:4547→4326，中央经线不变量成立"},
        {"id": "zip_gbk_dbf", "file": "zip_gbk_dbf.zip", "kind": "Shapefile ZIP",
         "expectation": f"{OK}，GBK DBF 中文属性不乱码"},
        {"id": "zip_null_shapes", "file": "zip_null_shapes.zip", "kind": "Shapefile ZIP",
         "expectation": f"{OK}，跳过 NULL Shape 并计数（原实现会崩溃）"},
        {"id": "zip_nested_dir", "file": "zip_nested_dir.zip", "kind": "Shapefile ZIP",
         "expectation": f"{OK}，子目录内 Shapefile 可发现"},
        {"id": "zip_multi_layer", "file": "zip_multi_layer.zip", "kind": "Shapefile ZIP",
         "expectation": f"{FAIL}，多图层歧义，列出全部 .shp"},
        {"id": "zip_missing_shx", "file": "zip_missing_shx.zip", "kind": "Shapefile ZIP",
         "expectation": f"{FAIL}，提示缺少配套文件 .shx"},
        {"id": "zip_no_shp", "file": "zip_no_shp.zip", "kind": "Shapefile ZIP",
         "expectation": f"{FAIL}，提示未找到 .shp"},
        {"id": "zip_traversal", "file": "zip_traversal.zip", "kind": "Shapefile ZIP",
         "expectation": f"{FAIL}，路径逃逸条目被拒绝"},
        {"id": "zip_bomb", "file": "zip_bomb.zip", "kind": "Shapefile ZIP",
         "expectation": f"{FAIL}，条目数超限被拒绝"},
        # --- Image overlay ---------------------------------------------------
        {"id": "image_png_ok", "file": "image_png_ok.png", "kind": "Image",
         "expectation": f"{OK}，bounds=广州范围"},
        {"id": "image_png_reversed", "file": "image_png_reversed.png", "kind": "Image",
         "expectation": f"{FAIL}，西界大于东界"},
    ]


def generate_all() -> Dict[str, bytes]:
    """Materialise every catalog sample as ``{filename: bytes}``."""
    utf16_payload = csv_bytes(
        ["名称", "经度", "纬度"],
        [["贝壳点", 113.264, 23.129]],
        encoding="utf-16",
    )
    samples: Dict[str, bytes] = {
        "geojson_valid.geojson": valid_points_geojson(),
        "geojson_explicit_4326.geojson": valid_points_geojson(crs="EPSG:4326"),
        "geojson_3857.geojson": web_mercator_geojson(),
        "geojson_utm50.geojson": projected_geojson(),
        "geojson_cgcs2000.geojson": cgcs2000_geojson(),
        "geojson_null_geometry.geojson": null_geometry_geojson(),
        "geojson_complex.geojson": complex_geometry_geojson(),
        "geojson_crs_conflict.geojson": conflict_crs_geojson(),
        "geojson_suspect_implicit.geojson": suspect_implicit_geojson(),
        "geojson_empty.geojson": geojson_bytes(geojson_collection([])),
        "geojson_malformed.geojson": malformed_json_geojson(),
        "csv_utf8.csv": valid_points_csv(),
        "csv_bom.csv": valid_points_csv(bom=True),
        "csv_gb18030.csv": valid_points_csv(encoding="gb18030"),
        "csv_utf16.csv": utf16_payload,
        "csv_quoted.csv": quoted_fields_csv(),
        "csv_mixed_validity.csv": mixed_validity_csv(),
        "csv_swapped.csv": swapped_lonlat_csv(),
        "csv_projected.csv": projected_csv(),
        "csv_out_of_range.csv": out_of_range_csv(),
        "csv_empty.csv": empty_csv(),
        "csv_header_only.csv": header_only_csv(),
        "zip_wgs84_prj.zip": valid_shapefile_zip(prj_wkt=WKT_4326),
        "zip_no_prj.zip": valid_shapefile_zip(prj_wkt=None),
        "zip_utm50_prj.zip": shapefile_zip_bytes(
            "utm50", [(500000.0, 4500000.0)], [["UTM 站"]],
            [("名称", "C", 40, 0)],
            extra_members={"utm50.prj": WKT_UTM50N},
        ),
        "zip_cgcs2000_4547.zip": cgcs2000_projected_zip(),
        "zip_gbk_dbf.zip": gbk_dbf_zip(),
        "zip_null_shapes.zip": null_shape_zip(),
        "zip_nested_dir.zip": nested_dir_zip(),
        "zip_multi_layer.zip": multi_layer_zip(),
        "zip_missing_shx.zip": missing_sidecar_zip(),
        "zip_no_shp.zip": empty_zip(),
        "zip_traversal.zip": traversal_zip(),
        "zip_bomb.zip": zip_bomb_bytes(),
        "image_png_ok.png": png_bytes(),
        "image_png_reversed.png": png_bytes(),
    }
    return samples
