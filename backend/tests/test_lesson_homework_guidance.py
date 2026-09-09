from copy import deepcopy
import json
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.models import LessonRecord
from backend.app.services.lesson_homework import homework_guidance
from backend.app.services.reports import ReportService
from backend.app.services.practice_export import PracticeExportService


def homework():
    path = Path(__file__).resolve().parents[1] / "app/data/builtin/lessons/population_shanghai_world_lesson.json"
    return json.loads(path.read_text(encoding="utf-8"))["plan"]["homework"]


def test_edited_or_ambiguous_prompt_does_not_inherit_teacher_answer():
    data = homework()
    prompt = data["basic"][0]
    assert homework_guidance(data, prompt)["answer_points"]
    assert homework_guidance(data, prompt + "改为比较其他区") == {}
    data["teacher_guidance"].append(deepcopy(data["teacher_guidance"][0]))
    assert homework_guidance(data, prompt) == {}


def test_recommendations_use_attached_guidance_without_claiming_student_diagnosis(tmp_path):
    data = homework()
    lesson = LessonRecord.create(title="人口分布", stages=[], plan={"homework": data})
    service = ReportService(AppConfig(root_dir=tmp_path))
    result = service.build_practice_recommendations({"response_data_collected": False, "lesson_snapshot_available": True}, lesson)
    assert [r["title"] for r in result] == ["上海公共服务布局", "上海内部人口变化", "用反例完善解释"]
    assert [r["suggested_minutes"] for r in result] == [8, 10, 10]
    assert all(r["answer_points"] and "没有足够证据" in r["evidence_basis"] for r in result)
    lesson.plan["homework"]["basic"][0] += "改题"
    changed = service.build_practice_recommendations({}, lesson)[0]
    assert changed["answer_points"] == [] and changed["suggested_minutes"] is None


def test_teacher_rubrics_never_leak_into_student_document(tmp_path):
    from docx import Document
    data = homework()
    prompt = data["basic"][1]
    guide = homework_guidance(data, prompt)
    items = [{"kind": "task", "origin": "lesson_homework_basic", "text": prompt, "teacher_guidance": guide}]
    service = object.__new__(PracticeExportService)
    for teacher in (False, True):
        path = tmp_path / ("teacher.docx" if teacher else "student.docx")
        service._write_paper(path, "上海人口", items, [], [], teacher=teacher)
        text = "\n".join(p.text for p in Document(path).paragraphs)
        assert prompt in text
        for point in guide["answer_points"]:
            assert (point in text) == teacher
        assert ("教师评分参考" in text) == teacher
