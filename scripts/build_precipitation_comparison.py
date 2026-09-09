"""Build a 400 mm/year isohyet from DWD/GPCC 1991-2020 monthly normals.

Run: python scripts/build_precipitation_comparison.py [--download]
Requires numpy, scipy and contourpy only for rebuilding, not at app runtime.
The original gzip stays in the ignored _cache directory. No administrative
boundary, station positions or population data are used to infer the contour.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

import contourpy
import numpy as np
from scipy.io import netcdf_file

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend/app/data/builtin/one_map"
NAME = "gpcc_precipitation_analysis_climatology_1991_2020_v2025_025.nc.gz"
URL = "https://opendata.dwd.de/climate_environment/GPCC/GPCC_Precipitation_Analysis_Climatology/Version_2025/" + NAME
SOURCE_URL = "https://opendata.dwd.de/climate_environment/GPCC/html/gpcc_precipitation_analysis_climatology_v2025_doi_download.html"
SHA256 = "3bd80d05df52572f6409b594ae26b43e9045147cb3c25254cddb5a934c16e5c5"
# The checksum published beside the original archive (downloaded and checked).
MD5 = "d701c717e08ce6ad457c9f4004984d65"
DATASET_ID = "china_precipitation_400mm"
BOUNDS = (73.0, 18.0, 136.0, 55.0)  # Regional window; not a national boundary.


def annual_total(monthly: np.ndarray) -> np.ma.MaskedArray:
    """Monthly totals add to annual precipitation, never average or fill gaps."""
    data = np.ma.asarray(monthly, dtype=np.float64)
    if data.ndim != 3 or data.shape[0] != 12:
        raise ValueError("Expected all twelve monthly climatological totals")
    bad = np.ma.getmaskarray(data) | ~np.isfinite(data.data) | (data.data < 0)
    return np.ma.array(np.where(bad, 0, data.data).sum(axis=0), mask=bad.any(axis=0))


def contour_lines(lon: np.ndarray, lat: np.ndarray, annual: np.ma.MaskedArray) -> list:
    if annual.shape != (len(lat), len(lon)):
        raise ValueError("Coordinate axes do not match precipitation grid")
    # GPCC numeric latitudes are north-positive and ordered north to south,
    # despite the file's misleading degrees_south attribute. Use coordinates.
    ix, iy = np.argsort(lon), np.argsort(lat)
    generator = contourpy.contour_generator(
        x=lon[ix], y=lat[iy], z=annual[np.ix_(iy, ix)],
        name="serial", corner_mask=False, line_type="Separate",
    )
    return [segment.tolist() for segment in generator.lines(400.0) if len(segment) >= 2]


def build(download: bool = False) -> dict:
    cache = DATA / "_cache/gpcc" / NAME
    if not cache.exists():
        if not download:
            raise FileNotFoundError("Source archive absent; use --download to fetch the official GPCC archive")
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(URL, timeout=60) as response:
            content = response.read(40_000_001)
        if len(content) > 40_000_000 or hashlib.sha256(content).hexdigest() != SHA256:
            raise ValueError("Source archive size/checksum mismatch; nothing installed")
        cache.write_bytes(content)
    content = cache.read_bytes()
    if hashlib.sha256(content).hexdigest() != SHA256:
        raise ValueError("Source archive checksum mismatch")
    with netcdf_file(io.BytesIO(gzip.decompress(content)), mmap=False) as ds:
        precip = ds.variables["gpcc_precip"]
        if precip.units != b"mm/month" or not np.array_equal(ds.variables["time"].data, np.arange(12)):
            raise ValueError("Unexpected GPCC units/months")
        lon = ds.variables["lon"].data.copy()
        lat = ds.variables["lat"].data.copy()
        x = (lon >= BOUNDS[0]) & (lon <= BOUNDS[2])
        y = (lat >= BOUNDS[1]) & (lat <= BOUNDS[3])
        annual = annual_total(precip.data[:, y][:, :, x].copy())
        segments = contour_lines(lon[x], lat[y], annual)
    if not segments:
        raise ValueError("No 400 mm contour in the selected regional window")
    metadata = {
        "source_name": "DWD / GPCC Precipitation Analysis Climatology V2025",
        "source_url": SOURCE_URL, "download_url": URL,
        "doi": "10.5676/DWD_GPCC/CLIMAT_V2025_025",
        "source_sha256": SHA256, "source_md5": MD5,
        "period": "1991-2020", "resolution_degrees": 0.25,
        "units": "mm/year", "isohyet_mm": 400,
        "license": "CC BY 4.0", "license_url": "https://www.dwd.de/EN/service/legal_notice/legal_notice.html",
        "attribution": "Source: Deutscher Wetterdienst (DWD), GPCC; Rustemeier, Finger, Schirmeister & Ziese (2025). Modified by GeoBot: monthly sum, regional subset and 400 mm contour extraction.",
        "method": "Sum 12 monthly normals, exclude cells with any missing/negative/nonfinite month, linear contour interpolation on grid centres; retain every branch and closed loop. No smoothing, no manual alignment to Hu line.",
        "bounds": list(BOUNDS),
        "limitations": ["雨量站资料插值的气候平均值，非2020年实测降水边界", "0.25度网格只支持区域对照，不支持街区判断", "范围为中国及周边矩形窗口，不作为国界", "局部闭合曲线与多分支保留，不强行拼成一条人口分界线", "未加雨量计系统误差校正；插值与资料覆盖存在不确定性"],
    }
    features = [{"type": "Feature", "properties": {
        "name": "400毫米年降水量线", "annual_precip_mm": 400,
        "period": "1991-2020", "resolution": "0.25°", "source": "DWD / GPCC V2025",
        "__strokeColor": "#8b3db0", "__strokeWidth": 3, "__lineDash": [9, 5], "__hideLabel": True,
    }, "geometry": {"type": "LineString", "coordinates": np.round(segment, 6).tolist()}} for segment in segments]
    payload = {"type": "FeatureCollection", "metadata": metadata, "features": features}
    target = DATA / "climate/china_precipitation_400mm.geojson"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return {"features": len(features), "vertices": sum(len(f["geometry"]["coordinates"]) for f in features), "bytes": target.stat().st_size, "source_sha256": SHA256}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    print(json.dumps(build(parser.parse_args().download)))
