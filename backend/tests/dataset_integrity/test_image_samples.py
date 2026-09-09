"""Image overlay acceptance samples: bounds validation."""
from __future__ import annotations

import pytest

import sample_factory


class TestImageOverlay:
    def test_valid_bounds_imported(self, service_env):
        _service, _store, project_id, _config = service_env
        result = _service.import_upload(
            project_id,
            "image_png_ok.png",
            sample_factory.png_bytes(),
            image_bounds=[113.0, 22.5, 114.3, 23.9],
        )
        assert result["layer"]["kind"] == "raster"
        assert result["layer"]["metadata"]["bounds"] == [113.0, 22.5, 114.3, 23.9]
        assert result["crs"]["detection_method"] == "image_bounds_assumed_wgs84"
        assert result["message"].startswith("图片叠加已导入")

    def test_missing_bounds_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="四个边界值"):
            _service.import_upload(project_id, "overlay.png", sample_factory.png_bytes())

    def test_reversed_east_west_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="西界必须小于东界"):
            _service.import_upload(
                project_id, "overlay.png", sample_factory.png_bytes(),
                image_bounds=[114.3, 22.5, 113.0, 23.9],
            )

    def test_reversed_north_south_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="南界必须小于北界"):
            _service.import_upload(
                project_id, "overlay.png", sample_factory.png_bytes(),
                image_bounds=[113.0, 23.9, 114.3, 22.5],
            )

    def test_longitude_out_of_range_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="超出经度范围"):
            _service.import_upload(
                project_id, "overlay.png", sample_factory.png_bytes(),
                image_bounds=[-181.0, 22.5, 114.3, 23.9],
            )

    def test_latitude_out_of_range_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="超出纬度范围"):
            _service.import_upload(
                project_id, "overlay.png", sample_factory.png_bytes(),
                image_bounds=[113.0, 22.5, 114.3, 95.0],
            )

    def test_non_numeric_bounds_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="数字"):
            _service.import_upload(
                project_id, "overlay.png", sample_factory.png_bytes(),
                image_bounds=["west", 22.5, 114.3, 23.9],
            )

    def test_degenerate_zero_area_bounds_rejected(self, service_env):
        _service, _store, project_id, _config = service_env
        with pytest.raises(ValueError, match="西界必须小于东界"):
            _service.import_upload(
                project_id, "overlay.png", sample_factory.png_bytes(),
                image_bounds=[113.0, 22.5, 113.0, 23.9],
            )
