"""Download three bounded OSM building samples; output stays ODbL, never census data."""
import json, re, urllib.request, urllib.parse
from pathlib import Path

BOXES = {"lujiazui": [31.23,121.49,31.244,121.512], "central": [31.225,121.465,31.235,121.48], "songjiang": [31.023,121.218,31.036,121.235]}
ENDPOINT = "https://overpass-api.de/api/interpreter"

def number(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(?:m)?", str(value or "").strip())
    return float(match[1]) if match else None

def convert(data):
    features=[]
    for item in data["elements"]:
        tags=item.get("tags", {})
        ring=[[point["lon"],point["lat"]] for point in item.get("geometry", [])]
        if len(ring)<4 or ring[0]!=ring[-1]: continue
        height=number(tags.get("height"))
        levels=number(tags.get("building:levels"))
        if height is not None and 0<height<1000: basis="osm_height"
        elif levels is not None and 0<levels<200: height=levels*3; basis="levels_estimate"
        else: height=0; basis="unknown"
        properties={"osm_id":item["id"],"name":tags.get("name:zh",tags.get("name", "")),"height_m":height,"height_basis":basis,"height_tag":tags.get("height"),"levels_tag":tags.get("building:levels"),"building":tags.get("building"),"source_url":f'https://www.openstreetmap.org/way/{item["id"]}'}
        features.append({"type":"Feature","id":item["id"],"properties":properties,"geometry":{"type":"Polygon","coordinates":[ring]}})
    return {"type":"FeatureCollection","license":"ODbL-1.0","attribution":"© OpenStreetMap contributors","source":ENDPOINT,"snapshot":data.get("osm3s",{}).get("timestamp_osm_base"),"bounds":BOXES,"features":features}

if __name__=="__main__":
    query='[out:json][timeout:25];('+''.join('way["building"]('+','.join(map(str,box))+');' for box in BOXES.values())+');out geom;'
    request=urllib.request.Request(ENDPOINT,data=urllib.parse.urlencode({"data":query}).encode(),headers={"User-Agent":"WebGIS-Education/1.0"})
    data=json.load(urllib.request.urlopen(request,timeout=55))
    result=convert(data)
    if not result["features"]: raise ValueError("No usable buildings returned")
    path=Path(__file__).resolve().parents[1]/"frontend/public/data/shanghai-buildings.geojson"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    from collections import Counter
    print(len(result["features"]),dict(Counter(f["properties"]["height_basis"] for f in result["features"])),result["snapshot"])
