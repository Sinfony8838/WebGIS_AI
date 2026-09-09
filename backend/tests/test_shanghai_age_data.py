import json
from copy import deepcopy
import unittest
from scripts.build_shanghai_age_layer import build_features, SOURCE, BASE, OUTPUT

class ShanghaiAgeDataTest(unittest.TestCase):
    def test_archived_table_and_generated_layer_preserve_census_units_and_boundaries(self):
        table = json.loads(SOURCE.read_text(encoding="utf-8"))
        source_geometry = json.loads(BASE.read_text(encoding="utf-8"))
        built = build_features(table, source_geometry)
        self.assertEqual(built, json.loads(OUTPUT.read_text(encoding="utf-8")))
        self.assertEqual(table["census_date"], "2020-11-01")
        self.assertEqual(table["unit"], "万人")
        features = {f["properties"]["name"]: f for f in built["features"]}
        # Independently checked against official table2.12, not unrounded density denominators.
        self.assertEqual(features["崇明区"]["properties"]["age_60_plus_pct"], 39.7)
        self.assertEqual(features["青浦区"]["properties"]["age_60_plus_pct"], 16.6)
        self.assertEqual(features["浦东新区"]["properties"]["60岁及以上（万人）"], 122.89)
        self.assertNotIn("density", features["浦东新区"]["properties"])
        for original in source_geometry["features"]:
            self.assertEqual(features[original["properties"]["name"]]["geometry"], original["geometry"])
        bad = deepcopy(table)
        bad["rows"][0][0] = "未核验区名"
        with self.assertRaises(ValueError):
            build_features(bad, source_geometry)
        bad = deepcopy(table)
        bad["rows"][0][4] = 900
        with self.assertRaises(ValueError):
            build_features(bad, source_geometry)
