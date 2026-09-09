import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("buildings_import",ROOT/"scripts/fetch_shanghai_buildings.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_height_provenance_and_no_fabricated_missing_heights():
    def item(id,tags):
        return {"id":id,"tags":tags,"geometry":[{"lon":121,"lat":31},{"lon":122,"lat":31},{"lon":122,"lat":32},{"lon":121,"lat":31}]}
    data=module.convert({"elements":[item(1,{"height":"42 m"}),item(2,{"building:levels":"8"}),item(3,{}),item(4,{"height":"9999","building:levels":"bad"})]})
    assert [(f["properties"]["height_m"],f["properties"]["height_basis"]) for f in data["features"]]==[(42,"osm_height"),(24,"levels_estimate"),(0,"unknown"),(0,"unknown")]

def test_bundled_buildings_are_bounded_and_attributable():
    data=json.loads((ROOT/"frontend/public/data/shanghai-buildings.geojson").read_text(encoding="utf8"))
    assert data["license"]=="ODbL-1.0"
    assert len(data["features"])==1448
    for feature in data["features"]:
        props=feature["properties"]
        ring=feature["geometry"]["coordinates"][0]
        assert ring[0]==ring[-1]
        assert all(121<lon<122 and 31<lat<32 for lon,lat in ring)
        assert props["source_url"].endswith(str(props["osm_id"]))
        if props["height_basis"]=="unknown": assert props["height_m"]==0
