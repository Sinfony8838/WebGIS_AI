"""CSV import acceptance samples: encodings, field aliases, row accounting."""
from __future__ import annotations

import pytest

from backend.app.services.datasets import CrsAssumptionError

import sample_factory
from backend.tests.dataset_integrity.helpers import upload_files


class TestCsvEncodings:
    def test_utf8_chinese_fields_autodetected(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "csv_utf8.csv", sample_factory.valid_points_csv())
        row_report = result["row_report"]
        assert row_report["total_rows"] == 3
        assert row_report["imported_rows"] == 3
        assert row_report["skipped_rows"] == 0
        # Chinese aliases 经度/纬度 resolved automatically.
        assert row_report["lat_field"] == "纬度"
        assert row_report["lon_field"] == "经度"
        props = result["layer"]["data"]["features"][0]["properties"]
        assert props["名称"] == "调查点 1"

    def test_utf8_bom_stripped(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "csv_bom.csv", sample_factory.valid_points_csv(bom=True))
        assert result["row_report"]["imported_rows"] == 3
        assert result["layer"]["metadata"]["encoding"] == "utf-8-sig"

    def test_gb18030_chinese_intact(self, service_env):
        _service, _store, project_id, _config = service_env
        raw = sample_factory.valid_points_csv(encoding="gb18030")
        result = _service.import_upload(project_id, "csv_gb18030.csv", raw)
        assert result["row_report"]["imported_rows"] == 3
        assert result["layer"]["data"]["features"][0]["properties"]["名称"] == "调查点 1"
        assert result["layer"]["metadata"]["encoding"] == "gb18030"

    def test_utf16_excel_export(self, service_env):
        _service, _store, project_id, _config = service_env
        payload = sample_factory.csv_bytes(
            ["名称", "经度", "纬度"], [["贝壳点", 113.264, 23.129]], encoding="utf-16"
        )
        result = _service.import_upload(project_id, "csv_utf16.csv", payload)
        assert result["row_report"]["imported_rows"] == 1
        assert result["layer"]["metadata"]["encoding"] == "utf-16"

    def test_quoted_fields_preserved(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "csv_quoted.csv", sample_factory.quoted_fields_csv())
        features = result["layer"]["data"]["features"]
        assert features[0]["properties"]["名称"] == "图书馆, 总馆"
        assert features[1]["properties"]["备注"] == "含\r\n换行"


class TestCsvRowAccounting:
    def test_mixed_validity_full_report(self, service_env):
        """980 valid + 20 broken rows → all stats, nothing silent."""
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "csv_mixed_validity.csv", sample_factory.mixed_validity_csv())
        report = result["row_report"]
        assert report["total_rows"] == 1000
        assert report["imported_rows"] == 980
        assert report["skipped_rows"] == 20
        reasons = report["skip_reasons"]
        assert reasons.get("坐标缺失") == 7
        assert reasons.get("坐标不是有效数字") == 7
        assert reasons.get("坐标超出经纬度范围") == 6
        assert sum(reasons.values()) == 20
        assert result["layer"]["metadata"]["feature_count"] == 980

    def test_message_counts_in_natural_chinese(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "csv_mixed.csv", sample_factory.mixed_validity_csv())
        assert "成功导入 980 条记录" in result["message"]
        assert "20 条被跳过" in result["message"]

    def test_partial_import_keeps_valid_rows(self, service_env):
        """A few broken rows no longer poison the whole file (v1.1 bug)."""
        _service, _store, project_id, _config = service_env
        payload = sample_factory.csv_bytes(
            ["name", "lon", "lat"],
            [["good", 113.2, 23.1], ["bad", "", 23.0], ["good2", 113.3, 23.2]],
        )
        result = _service.import_upload(project_id, "partial.csv", payload)
        assert result["row_report"]["imported_rows"] == 2
        assert result["row_report"]["skip_reasons"] == {"坐标缺失": 1}


class TestCsvRejections:
    def test_swapped_lonlat_rejected_with_hint(self, service_env):
        _service, _store, project_id, config = service_env
        with pytest.raises(ValueError, match="疑似经纬度反置"):
            _service.import_upload(project_id, "csv_swapped.csv", sample_factory.swapped_lonlat_csv())
        assert upload_files(config, project_id) == []

    def test_swapped_rows_mixed_with_valid_are_skipped(self, service_env):
        """Suspected swaps are reported per-row; valid rows still import."""
        _service, _store, project_id, _config = service_env
        payload = sample_factory.csv_bytes(
            ["name", "lon", "lat"],
            [["A", 23.129, 113.264], ["B", 113.264, 23.129]],
        )
        result = _service.import_upload(project_id, "swap_mixed.csv", payload)
        assert result["row_report"]["imported_rows"] == 1
        assert result["row_report"]["skip_reasons"] == {"疑似经纬度反置（纬度/经度列可能填反）": 1}

    def test_projected_coordinates_rejected(self, service_env):
        _service, _store, project_id, config = service_env
        with pytest.raises(CrsAssumptionError, match="EPSG:4326"):
            _service.import_upload(project_id, "csv_projected.csv", sample_factory.projected_csv())
        assert upload_files(config, project_id) == []

    def test_out_of_range_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="坐标超出经纬度范围"):
            _service.import_upload(project_id, "csv_oor.csv", sample_factory.out_of_range_csv())

    def test_empty_file_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="CSV 文件为空"):
            _service.import_upload(project_id, "csv_empty.csv", sample_factory.empty_csv())

    def test_header_only_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="没有数据行"):
            _service.import_upload(project_id, "csv_header.csv", sample_factory.header_only_csv())

    def test_missing_coordinate_columns_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        payload = sample_factory.csv_bytes(["city", "code"], [["广州", "020"]])
        with pytest.raises(ValueError, match="经纬度字段"):
            _service.import_upload(project_id, "csv_nocoord.csv", payload)

    def test_explicit_field_not_in_file(self, service_env):
        _service, _store, project_id, _config = service_env
        payload = sample_factory.csv_bytes(["name", "lon", "lat"], [["A", 113, 23]])
        with pytest.raises(ValueError, match="不存在字段"):
            _service.import_upload(project_id, "csv_badfield.csv", payload, lat_field="north")


class TestCsvFieldHandling:
    def test_explicit_lat_lon_fields(self, service_env):
        _service, _store, project_id, _config = service_env
        payload = sample_factory.csv_bytes(
            ["station", "north_y", "east_x"], [["S1", 23.13, 113.26]]
        )
        result = _service.import_upload(
            project_id, "custom.csv", payload, lat_field="north_y", lon_field="east_x"
        )
        assert result["row_report"]["lat_field"] == "north_y"
        assert result["row_report"]["imported_rows"] == 1

    def test_name_autofill(self, service_env):
        _service, _store, project_id, _config = service_env
        payload = sample_factory.csv_bytes(["lon", "lat"], [[113.2, 23.1], [113.3, 23.2]])
        result = _service.import_upload(project_id, "noname.csv", payload)
        names = [f["properties"]["name"] for f in result["layer"]["data"]["features"]]
        assert names == ["记录 1", "记录 2"]

    def test_coordinates_stored_as_points(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "csv_utf8.csv", sample_factory.valid_points_csv())
        feature = result["layer"]["data"]["features"][0]
        assert feature["geometry"] == {"type": "Point", "coordinates": [113.264, 23.129]}
        assert result["crs"]["source_crs"] == "EPSG:4326"
        assert result["crs"]["detection_method"] == "csv_lonlat_validated"
        assert result["crs"]["reprojected"] is False
