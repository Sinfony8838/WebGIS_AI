"""Shapefile ZIP acceptance samples: CRS sidecars, encodings, safety guards."""
from __future__ import annotations

import pytest

import sample_factory
from backend.app.services import datasets
from backend.tests.dataset_integrity.helpers import upload_files


class TestShapefileCrs:
    def test_wgs84_prj_no_warning(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "zip_wgs84_prj.zip", sample_factory.valid_shapefile_zip())
        assert result["crs"]["detection_method"] == "shapefile_prj"
        assert result["crs"]["source_crs"] == "EPSG:4326"
        assert result["crs"]["reprojected"] is False
        assert result["crs"]["warnings"] == []
        assert result["layer"]["metadata"]["feature_count"] == 3

    def test_no_prj_warns_but_imports(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "zip_no_prj.zip", sample_factory.valid_shapefile_zip(prj_wkt=None))
        codes = [w["code"] for w in result["crs"]["warnings"]]
        assert "SHAPEFILE_NO_PRJ" in codes
        assert result["crs"]["detection_method"] == "shapefile_no_prj_assumed_wgs84"
        assert result["layer"]["metadata"]["feature_count"] == 3

    def test_utm50_prj_reprojected(self, service_env, pyproj_available):
        _service, _store, project_id, _config = service_env
        zip_bytes = sample_factory.shapefile_zip_bytes(
            "utm50",
            [(500000.0, 4500000.0)],
            [["UTM 站"]],
            [("名称", "C", 40, 0)],
            extra_members={"utm50.prj": sample_factory.WKT_UTM50N},
        )
        result = _service.import_upload(project_id, "zip_utm50_prj.zip", zip_bytes)
        coords = result["layer"]["data"]["features"][0]["geometry"]["coordinates"]
        if pyproj_available:
            assert result["crs"]["reprojected"] is True
            assert coords[0] == pytest.approx(117.0, abs=0.01)
        else:
            assert result["crs"]["reprojected"] is False
            assert tuple(coords) == (500000.0, 4500000.0)
            assert [w["code"] for w in result["crs"]["warnings"]] == ["PYPROJ_UNAVAILABLE"]

    def test_cgcs2000_4547_central_meridian_invariant(self, service_env, pyproj_available):
        """On-CM control point: easting 500000 m in EPSG:4547 → lon = 114° exactly.

        Tolerance 1e-7° (≈1 cm); derived from the Gauss-Kruger definition
        (scale factor 1, false easting 500000 m at the central meridian).
        """
        _service, _store, project_id, _config = service_env
        zip_bytes = sample_factory.shapefile_zip_bytes(
            "cgcs_cm",
            [(500000.0, 2559263.5)],
            [["中央经线点"]],
            [("名称", "C", 40, 0)],
            extra_members={"cgcs_cm.prj": sample_factory.WKT_4547},
        )
        result = _service.import_upload(project_id, "zip_cgcs_cm.zip", zip_bytes)
        if not pyproj_available:
            pytest.skip("pyproj not installed")
        coords = result["layer"]["data"]["features"][0]["geometry"]["coordinates"]
        assert result["crs"]["source_crs"] == "EPSG:4547"
        assert coords[0] == pytest.approx(114.0, abs=1e-7)

    def test_utm50_without_pyproj_hidden_with_honest_label(self, service_env, no_pyproj):
        _service, _store, project_id, _config = service_env
        zip_bytes = sample_factory.shapefile_zip_bytes(
            "utm50",
            [(500000.0, 4500000.0)],
            [["UTM 站"]],
            [("名称", "C", 40, 0)],
            extra_members={"utm50.prj": sample_factory.WKT_UTM50N},
        )
        result = _service.import_upload(project_id, "zip_utm_nopyproj.zip", zip_bytes)
        assert result["layer"]["metadata"]["stored_crs"] == "EPSG:32650"
        assert result["layer"]["metadata"]["crs_converted"] is False
        assert result["layer"]["visible"] is False


class TestShapefileAttributes:
    def test_gbk_dbf_chinese_intact(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "zip_gbk_dbf.zip", sample_factory.gbk_dbf_zip())
        feature = result["layer"]["data"]["features"][0]
        assert feature["properties"]["名称"] == "中文站点名称"
        assert result["layer"]["metadata"]["dbf_encoding"] == "gb18030"

    def test_null_shapes_skipped_not_crash(self, service_env):
        """Regression: pyshp raises on NULL shapes; they must be counted."""
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "zip_null_shapes.zip", sample_factory.null_shape_zip())
        report = result["feature_report"]
        assert report["imported_features"] == 2
        assert report["skipped_features"] == 1
        assert report["skip_reasons"] == {"空几何（NULL Shape）": 1}
        names = [f["properties"]["名称"] for f in result["layer"]["data"]["features"]]
        assert names == ["有效点", "第二个有效点"]

    def test_nested_directory_layer_found(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(project_id, "zip_nested_dir.zip", sample_factory.nested_dir_zip())
        assert result["layer"]["metadata"]["feature_count"] == 1
        assert result["layer"]["data"]["features"][0]["properties"]["名称"] == "北京"

    def test_sibling_geojson_written_after_success(self, service_env):
        _service, _store, project_id, config = service_env
        _service.import_upload(project_id, "zip_wgs84_prj.zip", sample_factory.valid_shapefile_zip())
        assert upload_files(config, project_id) == ["zip_wgs84_prj.geojson", "zip_wgs84_prj.zip"]


class TestShapefileSafety:
    @pytest.fixture(autouse=True)
    def _simulate_missing_pyshp(self, monkeypatch):
        real_find_spec = datasets.importlib.util.find_spec

        def find_spec(name, *args, **kwargs):
            if name == "shapefile":
                return None
            return real_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(datasets.importlib.util, "find_spec", find_spec)

    def test_multi_layer_zip_rejected_as_ambiguous(self, service_env):
        _service, _store, project_id, config = service_env
        with pytest.raises(ValueError, match="多个 Shapefile") as exc_info:
            _service.import_upload(project_id, "zip_multi_layer.zip", sample_factory.multi_layer_zip())
        assert "layer_a.shp" in str(exc_info.value)
        assert "layer_b.shp" in str(exc_info.value)
        assert upload_files(config, project_id) == []

    def test_missing_shx_rejected_with_friendly_hint(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match=r"缺少配套文件.*\.shx"):
            _service.import_upload(project_id, "zip_missing_shx.zip", sample_factory.missing_sidecar_zip())

    def test_zip_without_shp_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="未找到 .shp"):
            _service.import_upload(project_id, "zip_no_shp.zip", sample_factory.empty_zip())

    def test_path_traversal_entry_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="Unsafe ZIP entry"):
            _service.import_upload(project_id, "zip_traversal.zip", sample_factory.traversal_zip())

    def test_backslash_path_traversal_entry_rejected(self, service_env):
        import io
        import zipfile

        _service, _store, project_id, _config = service_env
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as archive:
            archive.writestr("..\\escape.shp", b"bad")
        with pytest.raises(ValueError, match="Unsafe ZIP entry"):
            _service.import_upload(project_id, "zip_traversal_backslash.zip", raw.getvalue())

    def test_entry_count_bomb_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="条目数超过安全上限"):
            _service.import_upload(project_id, "zip_bomb.zip", sample_factory.zip_bomb_bytes())

    def test_no_temp_debris_after_failed_zip(self, service_env):
        """Failed zip imports leave no extraction dirs anywhere."""
        import tempfile
        from pathlib import Path

        _service, _store, project_id, config = service_env
        with pytest.raises(ValueError):
            _service.import_upload(project_id, "zip_multi_layer.zip", sample_factory.multi_layer_zip())
        system_temp = Path(tempfile.gettempdir())
        debris = [p.name for p in system_temp.glob("webgis_shpzip_*")]
        assert debris == []
        assert upload_files(config, project_id) == []
