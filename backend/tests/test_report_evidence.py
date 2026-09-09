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


def test_projected_question_without_responses_is_not_reported_as_zero_percent(tmp_path: Path):
    service = ReportService(AppConfig(root_dir=tmp_path))
    text = service.render_markdown({
        "questions": [{"text": "比较人口密度", "collection_mode": "student_response", "response_count": 0, "options": ["甲", "乙"], "option_counts": [0, 0], "correct_rate": None}],
        "observations": {},
    }, {"text": "未采集", "generator": "rules"})
    assert "本题未采集作答数据" in text
    assert "0 人作答" not in text
    assert "（0%）" not in text


def test_preset_homework_survives_title_and_partial_class_without_invented_answers(tmp_path):
    from backend.app.models import LessonRecord
    lesson = LessonRecord.create(title="人口分布：上海到世界", stages=[
        {"stage_id": "shanghai", "questions": []}, {"stage_id": "world", "questions": []}],
        plan={"homework": {"basic": ["核查上海人口与面积资料的年份和单位。"],
                           "inquiry": ["查找上海一个区的城市功能资料，说明地图局限。"]}})
    service = ReportService(AppConfig(root_dir=tmp_path))
    statistics = {"lesson_title": "旧人口课标题", "response_data_collected": False,
                  "stages": [{"stage_id": "shanghai"}, {"stage_id": "shanghai"}]}
    result = service.build_practice_recommendations(statistics, lesson)
    assert [r["prompt"] for r in result] == lesson.plan["homework"]["basic"] + lesson.plan["homework"]["inquiry"]
    assert all(r["answer_points"] == [] and r["suggested_minutes"] is None for r in result)
    assert all("1/2" in r["evidence_basis"] and "不代表完成学习" in r["evidence_basis"] for r in result)
    assert "缺少开课快照" in result[0]["evidence_basis"]
    statistics["lesson_snapshot_available"] = True
    assert "来自开课时保存的教案" in service.build_practice_recommendations(statistics, lesson)[0]["evidence_basis"]
    statistics.pop("lesson_snapshot_available")
    assert "Top20" not in str(result) and "胡焕庸线" not in str(result)
    lesson.title = "城市空间结构"
    assert service.build_practice_recommendations(statistics, lesson) == result
    markdown = service.render_markdown(statistics, {"text": "", "generator": "rules"}, result)
    assert "None 分钟" not in markdown and "答案要点：" not in markdown


def test_low_sample_question_prioritized_but_homework_preserved(tmp_path):
    from backend.app.models import LessonRecord
    lesson = LessonRecord.create(title="上海人口", stages=[{"stage_id": "s", "questions": [
        {"question_id": "q", "text": "人口多必然密度高吗？", "options": ["是", "否"], "answer_index": 1}
    ]}], plan={"homework": {"basic": ["整理思维导图。"]}})
    stats = {"response_data_collected": True, "questions": [{"question_id": "q", "text": "人口多必然密度高吗？",
        "response_count": 2, "correct_rate": .5, "options": ["是", "否"], "answer_index": 1}]}
    result = ReportService(AppConfig(root_dir=tmp_path)).build_practice_recommendations(stats, lesson)
    assert result[0]["prompt"] == "整理思维导图。"
    assert len(result) == 2
    assert "2 份" in result[1]["evidence_basis"] and "50%" in result[1]["evidence_basis"]
    assert "不据少量记录推断全班" in result[1]["evidence_basis"]
    assert result[1]["answer_points"] == ["B. 否"]
    stats["questions"][0]["correct_rate"] = 1
    assert len(ReportService(AppConfig(root_dir=tmp_path)).build_practice_recommendations(stats, lesson)) == 1


def test_only_misconception_tags_and_question_linked_observations_drive_review(tmp_path):
    from backend.app.models import LessonRecord
    service = ReportService(AppConfig(root_dir=tmp_path))
    observations = service._observation_stats([
        {"type": "teacher_observation", "payload": {"verdict": "correct", "tag": "总量与密度", "question_id": "q"}},
        {"type": "teacher_observation", "payload": {"verdict": "partial", "tag": "缺少单位", "question_id": "q"}},
        {"type": "teacher_observation", "payload": {"verdict": "misconception", "tag": "把总量当密度", "question_id": "q"}},
    ])
    assert observations["misconception_tags"] == [("把总量当密度", 1)]
    assert len(observations["records"]) == 3
    lesson = LessonRecord.create(title="测试", plan={"homework": {"basic": ["原作业"]}})
    result = service.build_practice_recommendations({"response_data_collected": False,
        "questions": [{"question_id": "q", "text": "比较两区密度"}], "observations": observations}, lesson)
    assert len(result) == 2
    assert "缺少单位" in result[1]["evidence_basis"]
    assert "未采集" in result[1]["evidence_basis"] and "正确率" not in str(result)
    assert result[1]["answer_points"] == []


def test_missing_lesson_or_homework_does_not_create_population_pack(tmp_path):
    service = ReportService(AppConfig(root_dir=tmp_path))
    result = service.build_practice_recommendations({"lesson_title": "人口分布"}, None)
    assert result[0]["level"] == "教师待确认"
    assert "先补充教学目标" in result[0]["prompt"]
    assert "胡焕庸线" not in str(result) and "上海" not in str(result)


def test_open_responses_are_collected_without_invented_correctness(tmp_path):
    service = ReportService(AppConfig(root_dir=tmp_path))
    text = service.compose_diagnosis({"response_data_collected": True,
        "questions": [{"question_id": "q", "response_count": 3, "correct_rate": None}]})["text"]
    assert "已采集作答" in text and "开放题" in text
    assert "未采集课堂作答" not in text


def test_report_snapshot_references_resolve_registered_project_files(tmp_path):
    from backend.app.models import ArtifactRecord, ClassSessionRecord, LessonRecord
    config = AppConfig(root_dir=tmp_path)
    service = ReportService(config)
    folder = config.project_output_dir("p1")
    image = folder / "地图 (1).png"
    image.write_bytes(b"test image")
    artifact = ArtifactRecord.create("p1", "j", "map_snapshot", "地图", str(image), {"public_url": "https://untrusted.example/"})
    session = ClassSessionRecord.create("l", "p1", "")
    session.events = [{"type":"snapshot", "timestamp":"2026-09-09T10:00:00", "stage_id":"s", "payload":{
        "artifact_id":artifact.artifact_id, "title":"上海", "stage_id":"forged", "image_url":"https://untrusted.example/"}}]
    lesson = LessonRecord.create(title="人口", stages=[{"stage_id":"s", "title":"看上海"}])
    stats = service.build_statistics(session, lesson, lambda _: artifact)
    reference = stats["snapshots"][0]
    assert reference["available"] is True
    assert reference["stage_title"] == "看上海" and reference["stage_id"] == "s"
    assert reference["image_url"].startswith("/files/outputs/p1/")
    assert "%28" in reference["image_url"] and "untrusted" not in str(reference)
    assert stats["response_data_collected"] is False
    markdown = service.render_markdown(stats, {"text":"", "generator":"rules"})
    assert "查看地图原图" in markdown and "不能单独证明" in markdown
    image.unlink()
    missing = service.build_statistics(session, lesson, lambda _: artifact)
    assert missing["snapshots"][0]["available"] is False
    assert "截图文件不可用" in service.render_markdown(missing, {"text":""})


def test_report_snapshots_do_not_expose_foreign_or_unregistered_artifacts(tmp_path):
    from backend.app.models import ArtifactRecord, ClassSessionRecord
    config = AppConfig(root_dir=tmp_path)
    image = config.project_output_dir("p2") / "foreign.png"
    image.write_bytes(b"test image")
    artifact = ArtifactRecord.create("p2", "j", "map_snapshot", "私有标题", str(image))
    session = ClassSessionRecord.create("l", "p1", "")
    session.events = [{"type":"snapshot", "payload":{"artifact_id":artifact.artifact_id}}]
    service = ReportService(config)
    for resolver in (lambda _: artifact, lambda _: None):
        reference = service.build_statistics(session, None, resolver)["snapshots"][0]
        assert not reference["available"] and reference["image_url"] == ""
        assert "私有标题" not in str(reference) and str(image) not in str(reference)
    artifact.project_id = "p1"  # Still reject an out-of-project file path.
    assert not service.build_statistics(session, None, lambda _: artifact)["snapshots"][0]["available"]
