from pathlib import Path

from backend.app.config import AppConfig
from backend.app.services.reports import ReportService


def test_no_observations_cannot_imply_normal_understanding(tmp_path: Path) -> None:
    service = ReportService(AppConfig(root_dir=tmp_path))
    result = service.compose_diagnosis({
        "response_data_collected": False,
        "questions": [{"text": "建筑高度能否代表密度？"}],
        "observations": {"verdict_counts": {}, "misconception_tags": []},
        "stages": [{"actual_minutes": 2, "planned_minutes": 8}],
    })
    assert result["generator"] == "rules"
    assert "不足以判断学生掌握情况" in result["text"]
    assert "理解情况总体正常" not in result["text"]
    assert "未记录不等于" in result["text"]


def test_teacher_misconception_evidence_remains_actionable(tmp_path: Path) -> None:
    service = ReportService(AppConfig(root_dir=tmp_path))
    result = service.compose_diagnosis({
        "response_data_collected": False,
        "observations": {"verdict_counts": {"misconception": 2}, "misconception_tags": [["总量与密度混淆", 2]]},
    })
    assert "总量与密度混淆" in result["text"]
    assert "设计一道对比辨析题" in result["text"]
    assert "正确率" not in result["text"]
