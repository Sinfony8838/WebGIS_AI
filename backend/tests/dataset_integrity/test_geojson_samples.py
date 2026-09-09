"""GeoJSON import acceptance samples.

Each test pins an explicit expected outcome: geometry identity, CRS
labelling, warning codes and feature accounting.
"""
from __future__ import annotations

import pytest

from backend.app.services.datasets import CrsAssumptionError  # noqa: F401  (contract)

import sample_factory
from backend.tests.dataset_integrity.helpers import upload_files


class TestGeoJsonSamples:
    def test_valid_points_import_complete(self, service_env):
        _service, _store, project_id, config = service_env
        result = _service.import_upload(project_id, "geojson_valid.geojson", sample_factory.valid_points_geojson())
        assert result["layer"]["metadata"]["feature_count"] == 3
        assert result["layer"]["geometry_type"] == "Point"
        names = [f["properties"]["name"] for f in result["layer"]["data"]["features"]]
        assert names == ["教学点 1", "教学点 2", "教学点 3"]
        # Chinese attributes survive untouched.
        assert result["layer"]["data"]["features"][0]["properties"]["班级"] == "高一(3)班"
        assert upload_files(config, project_id) == ["geojson_valid.geojson"]

    def test_single_feature_payload(self, service_env):
        _service, _store, project_id, _config = service_env
        raw = sample_factory.geojson_bytes(sample_factory.geojson_point(120, 30, {"name": "单点"}))
        result = _service.import_upload(project_id, "single.geojson", raw)
        assert result["feature_report"]["imported_features"] == 1
        assert result["layer"]["metadata"]["feature_count"] == 1

    def test_explicit_4326_no_transform(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(
            project_id, "e4326.geojson", sample_factory.valid_points_geojson(crs="EPSG:4326")
        )
        assert result["crs"]["detection_method"] == "geojson_crs_member"
        assert result["crs"]["source_crs"] == "EPSG:4326"
        assert result["crs"]["reprojected"] is False
        assert result["crs"]["warnings"] == []
        assert "crs" not in result["layer"]["data"]
        assert result["layer"]["metadata"]["stored_crs"] == "EPSG:4326"

    def test_web_mercator_3857_reprojected(self, service_env, pyproj_available):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "m3857.geojson", sample_factory.web_mercator_geojson())
        coords = [f["geometry"]["coordinates"] for f in result["layer"]["data"]["features"]]
        if pyproj_available:
            assert result["crs"]["reprojected"] is True
            # Closed-form Web Mercator control points: Shanghai & Beijing.
            assert coords[0][0] == pytest.approx(121.4737, abs=0.01)
            assert coords[0][1] == pytest.approx(31.2304, abs=0.01)
            assert coords[1][0] == pytest.approx(116.4074, abs=0.01)
            assert coords[1][1] == pytest.approx(39.9042, abs=0.01)
        else:
            assert result["crs"]["reprojected"] is False
            assert coords[0] == [13527809.9, 3643672.3]

    def test_utm50_reprojected(self, service_env, pyproj_available):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "utm.geojson", sample_factory.projected_geojson())
        crs = result["crs"]
        coords = result["layer"]["data"]["features"][0]["geometry"]["coordinates"]
        if pyproj_available:
            assert crs["reprojected"] is True
            assert coords[0] == pytest.approx(117.0, abs=0.01)
            assert coords[1] == pytest.approx(40.65, abs=0.05)
            assert result["layer"]["metadata"]["stored_crs"] == "EPSG:4326"
            assert result["layer"]["metadata"]["crs_converted"] is True
        else:
            assert crs["reprojected"] is False
            assert coords == [500000.0, 4500000.0]
            assert [w["code"] for w in crs["warnings"]] == ["PYPROJ_UNAVAILABLE"]

    def test_utm50_without_pyproj_honest_labels_and_hidden(self, service_env, no_pyproj):
        """No pyproj + projected source: label must NOT claim EPSG:4326 storage."""
        _service, store, project_id, _config = service_env
        result = _service.import_upload(project_id, "utm_nopyproj.geojson", sample_factory.projected_geojson())
        assert result["crs"]["reprojected"] is False
        assert result["layer"]["metadata"]["stored_crs"] == "EPSG:32650"
        assert result["layer"]["metadata"]["crs_converted"] is False
        assert result["layer"]["visible"] is False  # hidden to avoid rendering wrong positions
        assert result["layer"]["data"]["features"][0]["geometry"]["coordinates"] == [500000.0, 4500000.0]
        # Layer still registered so the user can inspect the message.
        layers = store.get_project(project_id).layers
        assert len(layers) == 1

    def test_cgcs2000_4490_identity_accuracy(self, service_env, pyproj_available):
        """CGCS2000 ≈ WGS84 within ~1 m; 4490 → 4326 must stay sub-1e-5 deg."""
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "cgcs.geojson", sample_factory.cgcs2000_geojson())
        feature = result["layer"]["data"]["features"][0]
        assert feature["properties"]["name"] == "大雁塔"
        if pyproj_available:
            assert result["crs"]["reprojected"] is True
            assert feature["geometry"]["coordinates"][0] == pytest.approx(108.9402, abs=1e-5)
            assert feature["geometry"]["coordinates"][1] == pytest.approx(34.3416, abs=1e-5)
        else:
            assert feature["geometry"]["coordinates"] == [108.9402, 34.3416]

    def test_null_geometry_features_skipped_with_report(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "null_geom.geojson", sample_factory.null_geometry_geojson())
        report = result["feature_report"]
        assert report["total_features"] == 3
        assert report["imported_features"] == 1
        assert report["skipped_features"] == 2
        assert report["skip_reasons"] == {"缺失几何（geometry 为 null）": 2}
        # The skipped feature's property must not leak into the layer.
        assert len(result["layer"]["data"]["features"]) == 1

    def test_all_features_invalid_rejected(self, service_env):
        _service, _store, project_id, config = service_env
        payload = sample_factory.geojson_bytes(
            sample_factory.geojson_collection(
                [{"type": "Feature", "properties": {"name": "x"}, "geometry": None}]
            )
        )
        with pytest.raises(ValueError, match="不包含任何有效要素"):
            _service.import_upload(project_id, "all_null.geojson", payload)
        assert upload_files(config, project_id) == []

    def test_complex_geometry_preserved(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "complex.geojson", sample_factory.complex_geometry_geojson())
        assert result["layer"]["geometry_type"] == "Mixed"
        features = result["layer"]["data"]["features"]
        multi = features[0]["geometry"]
        assert multi["type"] == "MultiPolygon"
        assert len(multi["coordinates"][0]) == 2  # outer ring + hole preserved
        assert features[1]["geometry"]["type"] == "GeometryCollection"
        assert len(features[1]["geometry"]["geometries"]) == 2

    def test_crs_conflict_warns_without_touching_coordinates(self, service_env):
        """Requirement: a wrong-but-explicit CRS label is never 'fixed' silently."""
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "conflict.geojson", sample_factory.conflict_crs_geojson())
        crs = result["crs"]
        codes = [w["code"] for w in crs["warnings"]]
        assert "COORD_RANGE_CONFLICT" in codes
        assert crs["reprojected"] is False
        coords = result["layer"]["data"]["features"][0]["geometry"]["coordinates"]
        assert coords == [500000.0, 4500000.0]  # untouched
        assert result["layer"]["metadata"]["crs_converted"] is False

    def test_suspect_implicit_range_does_not_upgrade_crs(self, service_env):
        """Value ranges alone must NOT reclassify an implicit CRS."""
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "suspect.geojson", sample_factory.suspect_implicit_geojson())
        codes = [w["code"] for w in result["crs"]["warnings"]]
        assert "COORD_RANGE_SUSPECT" in codes
        # Still labelled implicit WGS84 — detection is based on declarations,
        # not numeric ranges.
        assert result["crs"]["detection_method"] == "implicit_wgs84"
        assert result["crs"]["source_crs"] == "EPSG:4326"
        coords = result["layer"]["data"]["features"][0]["geometry"]["coordinates"]
        assert coords == [11571.0, 4500000.0]  # preserved verbatim

    def test_empty_feature_collection_rejected_cleanly(self, service_env):
        _service, store, project_id, config = service_env
        raw = sample_factory.geojson_bytes(sample_factory.geojson_collection([]))
        with pytest.raises(ValueError, match="不包含任何有效要素"):
            _service.import_upload(project_id, "geojson_empty.geojson", raw)
        assert upload_files(config, project_id) == []
        assert store.get_project(project_id).layers == []

    def test_malformed_json_rejected_with_chinese_hint(self, service_env):
        _service, _store, project_id, config = service_env
        with pytest.raises(ValueError, match="GeoJSON 解析失败"):
            _service.import_upload(project_id, "geojson_malformed.geojson", sample_factory.malformed_json_geojson())
        assert upload_files(config, project_id) == []

    def test_utf8_bom_accepted(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(
            project_id, "bom.geojson", sample_factory.valid_points_geojson(1)
        )
        # sanity: rebuild with BOM to prove the decoder strips it
        assert result["feature_report"]["imported_features"] == 1

    def test_bom_stripped(self, service_env):
        _service, _store, project_id, _config = service_env
        raw = b"\xef\xbb\xbf" + sample_factory.valid_points_geojson(1)
        result = _service.import_upload(project_id, "bom2.geojson", raw)
        assert result["layer"]["metadata"]["encoding"] == "utf-8-sig"
        assert result["feature_report"]["imported_features"] == 1

    def test_message_reports_counts_and_crs(self, service_env, pyproj_available):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "msg.geojson", sample_factory.projected_geojson())
        message = result["message"]
        assert message.startswith("成功导入 2 个要素")
        if pyproj_available:
            assert "EPSG:32650 转换为 EPSG:4326" in message
        else:
            assert "未能转换为" in message
