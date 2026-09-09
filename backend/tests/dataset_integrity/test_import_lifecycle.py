"""Import lifecycle: persistence ordering, cleanup, duplicate naming, contract."""
from __future__ import annotations

import pytest

from backend.app.services.datasets import CrsAssumptionError

import sample_factory
from backend.tests.dataset_integrity.helpers import upload_files


class TestPersistenceOrdering:
    def test_failed_geojson_leaves_zero_files(self, service_env):
        _service, store, project_id, config = service_env
        with pytest.raises(ValueError):
            _service.import_upload(project_id, "geojson_malformed.geojson", sample_factory.malformed_json_geojson())
        assert upload_files(config, project_id) == []
        assert store.get_project(project_id).layers == []

    def test_failed_csv_leaves_zero_files(self, service_env):
        _service, store, project_id, config = service_env
        with pytest.raises(CrsAssumptionError):
            _service.import_upload(project_id, "csv_projected.csv", sample_factory.projected_csv())
        assert upload_files(config, project_id) == []
        assert store.get_project(project_id).layers == []

    def test_failed_zip_leaves_zero_files(self, service_env):
        _service, store, project_id, config = service_env
        with pytest.raises(ValueError):
            _service.import_upload(project_id, "zip_no_shp.zip", sample_factory.empty_zip())
        assert upload_files(config, project_id) == []
        assert store.get_project(project_id).layers == []

    def test_successful_csv_persists_upload_and_sibling(self, service_env):
        _service, _store, project_id, config = service_env
        result = _service.import_upload(project_id, "csv_utf8.csv", sample_factory.valid_points_csv())
        assert result["artifact"]["path"].endswith("csv_utf8.csv")
        assert upload_files(config, project_id) == ["csv_utf8.csv", "csv_utf8.geojson"]

    def test_unsupported_type_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="不支持的文件类型"):
            _service.import_upload(project_id, "notes.txt", b"hello")


class TestDuplicateImports:
    def test_second_import_renamed_with_suffix(self, service_env):
        _service, store, project_id, _config = service_env
        raw = sample_factory.valid_points_geojson(1)
        first = _service.import_upload(project_id, "same.geojson", raw)
        second = _service.import_upload(project_id, "same.geojson", raw)
        assert first["layer"]["name"] == "same"
        assert second["layer"]["name"] == "same (2)"
        assert second["layer"]["metadata"]["duplicate_import"] is True
        assert second["layer"]["metadata"]["renamed_from"] == "same"
        assert len(store.get_project(project_id).layers) == 2

    def test_third_import_suffix_increments(self, service_env):
        _service, store, project_id, _config = service_env
        raw = sample_factory.valid_points_geojson(1)
        _service.import_upload(project_id, "same.geojson", raw)
        _service.import_upload(project_id, "same.geojson", raw)
        third = _service.import_upload(project_id, "same.geojson", raw)
        assert third["layer"]["name"] == "same (3)"
        assert len(store.get_project(project_id).layers) == 3

    def test_explicit_dataset_name_collision_renamed(self, service_env):
        _service, _store, project_id, _config = service_env
        _service.import_upload(project_id, "a.geojson", sample_factory.valid_points_geojson(1), dataset_name="我的数据")
        other = _service.import_upload(project_id, "b.geojson", sample_factory.valid_points_geojson(1), dataset_name="我的数据")
        assert other["layer"]["name"] == "我的数据 (2)"
        assert "已命名为“我的数据 (2)”" in other["message"]

    def test_both_duplicate_files_kept_on_disk(self, service_env):
        _service, _store, project_id, config = service_env
        _service.import_upload(project_id, "same.geojson", sample_factory.valid_points_geojson(1))
        _service.import_upload(project_id, "same.geojson", sample_factory.valid_points_geojson(1))
        files = upload_files(config, project_id)
        assert files == ["same.geojson", "same_x.geojson"] or len(files) == 2
        assert all(name.endswith(".geojson") for name in files)


class TestResultContract:
    def test_result_payload_keys(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "csv_utf8.csv", sample_factory.valid_points_csv())
        for key in ("layer", "artifact", "crs", "message", "row_report"):
            assert key in result
        metadata = result["layer"]["metadata"]
        for key in ("source_crs", "stored_crs", "crs_converted", "feature_count"):
            assert key in metadata
        assert metadata["source_crs"] == "EPSG:4326"
        assert metadata["stored_crs"] == "EPSG:4326"
        assert metadata["crs_converted"] is False

    def test_recent_action_recorded_on_success(self, service_env):
        _service, store, project_id, _config = service_env
        result = _service.import_upload(project_id, "geojson_valid.geojson", sample_factory.valid_points_geojson(1))
        actions = store.get_project(project_id).recent_actions
        assert any(
            action.get("title") == "导入教学数据" and result["layer"]["name"] in action.get("detail", "")
            for action in actions
        )

    def test_zip_and_geojson_report_feature_counts(self, service_env):
        _service, _store, project_id, _config = service_env
        zip_result = _service.import_upload(project_id, "z.zip", sample_factory.valid_shapefile_zip())
        assert zip_result["feature_report"]["imported_features"] == 3
        geo_result = _service.import_upload(project_id, "g.geojson", sample_factory.valid_points_geojson(2))
        assert geo_result["feature_report"]["total_features"] == 2
