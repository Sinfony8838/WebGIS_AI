import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.app.models import LayerRecord
from backend.app.runtime import WebGISRuntime
from backend.app.store import RuntimeStore


class LayerPersistenceTest(unittest.TestCase):
    def test_external_features_roundtrip_update_and_reuse_id(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "runtime.json"
            store = RuntimeStore(path)
            project = store.create_project(name="persistence test")

            def make_layer(value):
                return LayerRecord.create(layer_id="same-layer", name="large", kind="vector",
                    source="test", geometry_type="Point", data={"type": "FeatureCollection",
                    "features": [{"type": "Feature", "properties": {"value": value, "text": "x" * 300000},
                                  "geometry": {"type": "Point", "coordinates": [104, 35]}}]})

            layer = make_layer(1)
            store.upsert_layer(project.project_id, layer)
            self.assertIn("features", layer.data)
            self.assertNotIn("features_file", layer.data)
            self.assertLess(path.stat().st_size, 10000)
            restored = RuntimeStore(path)
            self.assertEqual(restored.get_project(project.project_id).layers[0].data["features"], layer.data["features"])
            # Metadata-only changes reuse the existing external file after restart.
            before = sorted((Path(root) / "layer_data").glob("*.json"))
            restored.patch_layer(project.project_id, layer.layer_id, {"opacity": 0.5})
            self.assertEqual(before, sorted((Path(root) / "layer_data").glob("*.json")))
            restored.patch_layer(project.project_id, layer.layer_id, {"data": make_layer(2).data})
            self.assertEqual(RuntimeStore(path).get_project(project.project_id).layers[0].data["features"][0]["properties"]["value"], 2)
            restored.delete_layer(project.project_id, layer.layer_id)
            restored.upsert_layer(project.project_id, make_layer(3))
            self.assertEqual(RuntimeStore(path).get_project(project.project_id).layers[0].data["features"][0]["properties"]["value"], 3)

    def test_project_summary_never_copies_omitted_features(self):
        class Uncopyable(list):
            def __deepcopy__(self, memo):
                raise AssertionError("omitted features must not be copied")
            def __iter__(self):
                raise AssertionError("omitted features must not be traversed")

        with tempfile.TemporaryDirectory() as root:
            store = RuntimeStore(Path(root) / "runtime.json")
            project = store.create_project(name="summary test")
            project.layers.append(LayerRecord.create(name="large", kind="vector", source="test", geometry_type="Point",
                data={"features": Uncopyable()}))
            payload = WebGISRuntime._project_payload(project)
            self.assertEqual(payload["layers"][0]["data"], {})
            self.assertIn("features", project.layers[0].data)

    def test_restored_external_reference_cannot_escape_layer_directory(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "runtime.json"
            store = RuntimeStore(path)
            project = store.create_project(name="reference test")
            layer = LayerRecord.create(name="external", kind="vector", source="test", geometry_type="Point",
                data={"features_file": "../outside.json"})
            store.upsert_layer(project.project_id, layer)
            outside = Path(root) / "outside.json"
            outside.write_text(json.dumps({"features": [{"private": True}]}), encoding="utf-8")
            restored = RuntimeStore(path)
            self.assertNotIn("features", restored.get_project(project.project_id).layers[0].data)
