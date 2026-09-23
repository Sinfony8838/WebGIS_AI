import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from backend.app.config import AppConfig
from backend.app.models import WorkflowRecord
from backend.app.runtime import _fallback_summary
from backend.app.services.workflow_parameters import prepare_workflow
from backend.app.services.workflow_executor import run_preflight


@pytest.fixture
def dataset(tmp_path):
    config = AppConfig()
    config.data_dir = tmp_path / "data"
    config.uploads_dir = config.data_dir / "uploads"
    config.workflows_dir = config.data_dir / "workflows"
    folder = config.uploads_dir / "p1"
    folder.mkdir(parents=True)
    fixture = Path(__file__).parent / "fixtures/gis/usgs_noto_20240101.geojson"
    (folder / "events.geojson").write_bytes(fixture.read_bytes())
    return config, "upload:p1/events.geojson"


def test_original_usgs_buffer_needs_no_name_alias(dataset):
    config, source = dataset
    preview, match = prepare_workflow(config, "p1", "20 公里缓冲区，合并重叠区域", "facility_buffer", {"dataset": source})
    assert preview["valid"], preview["issues"]
    assert preview["parameters"]["label_field"] == "place"
    assert preview["parameters"]["distance_m"] == 20000
    assert preview["parameter_sources"]["distance_m"] == "message"
    assert run_preflight(config, match.workflow)[0] == []


def test_classify_real_request_uses_requested_parameters(dataset):
    config, source = dataset
    preview, match = prepare_workflow(config, "p1", "对 mag（震级）字段，按等距法 equal 分成 3 级，写入 mag_class，保留全部 35 个点", "classify_field", {"dataset": source})
    assert preview["valid"], preview["issues"]
    assert {key: preview["parameters"][key] for key in ("field", "classes", "method", "output_field")} == {
        "field": "mag", "classes": 3, "method": "equal", "output_field": "mag_class"}
    assert match.workflow["steps"][2]["params"]["field"] == "mag"


def test_manual_overrides_text(dataset):
    config, source = dataset
    preview, _ = prepare_workflow(config, "p1", "mag 字段等距分 3 级", "classify_field",
                                  {"dataset": source, "classes": 4, "method": "quantile"})
    assert preview["valid"]
    assert preview["parameters"]["classes"] == 4
    assert preview["parameters"]["method"] == "quantile"
    assert preview["parameter_sources"]["classes"] == "manual"


def test_ambiguous_buffer_requires_manual_distance(dataset):
    config, source = dataset
    preview, _ = prepare_workflow(config, "p1", "20 公里或 30 公里缓冲", "facility_buffer", {"dataset": source})
    assert not preview["valid"]
    preview, _ = prepare_workflow(config, "p1", "20 公里或 30 公里缓冲", "facility_buffer", {"dataset": source, "distance_m": 20000})
    assert preview["valid"]


@pytest.mark.parametrize("overrides,field", [
    ({}, "field"), ({"field": "missing"}, "field"), ({"field": ["mag"]}, "field"),
    ({"field": "mag", "classes": 3.5}, "classes"),
    ({"field": "mag", "method": "bogus"}, "method"),
    ({"field": "mag", "output_field": "place"}, "output_field"),
])
def test_invalid_classification_blocks_preview(dataset, overrides, field):
    config, source = dataset
    preview, match = prepare_workflow(config, "p1", "字段分级", "classify_field", {"dataset": source, **overrides})
    assert not preview["valid"]
    assert match is None
    assert any(issue["field"] == field for issue in preview["issues"])


def test_cross_project_source_rejected(dataset):
    config, source = dataset
    preview, _ = prepare_workflow(config, "other", "缓冲区", "facility_buffer", {"dataset": source})
    assert not preview["valid"]


def test_chinese_field_and_first_feature_without_field(dataset):
    config, source = dataset
    path = config.uploads_dir / "p1/events.geojson"
    data = json.loads(path.read_text())
    for index, feature in enumerate(data["features"]):
        feature["properties"] = {} if index == 0 else {"震级": feature["properties"]["mag"]}
    path.write_text(json.dumps(data), encoding="utf-8")
    preview, _ = prepare_workflow(config, "p1", "按震级等距分三级", "classify_field", {"dataset": source})
    assert preview["valid"], preview["issues"]
    assert preview["parameters"]["field"] == "震级"
    assert preview["parameters"]["classes"] == 3
    assert preview["parameters"]["output_field"] == "class_id"


def test_unlabelled_buffer_falls_back_to_feature_id(dataset):
    config, source = dataset
    path = config.uploads_dir / "p1/events.geojson"
    data = json.loads(path.read_text())
    for feature in data["features"]:
        feature["properties"] = {"mag": 5}
    path.write_text(json.dumps(data), encoding="utf-8")
    preview, _ = prepare_workflow(config, "p1", "缓冲 20000 米", "facility_buffer", {"dataset": source})
    assert preview["valid"]
    assert preview["parameters"]["label_field"] == ""


def test_summary_uses_total_not_truncated_rows():
    record = WorkflowRecord.create(project_id="p1", user_message="缓冲区", workflow_json={
        "steps": [{"op": "buffer", "params": {"distance": 20000}}]})
    text = _fallback_summary(record, {"all_rows_count": 35, "summary": {"count": 35}, "rows": [{"mag": 5}] * 20})
    assert "共 35 个要素" in text
    assert "前 20 条" in text
    assert "20000 米" in text
