from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from backend.app.config import AppConfig
from backend.app.runtime import WebGISRuntime
from backend.app.services.population_lesson_prep import lesson_content_fingerprint
from backend.app.store import RuntimeStore


BUILTIN_LESSON_ID = "lesson_builtin_population_distribution"


class PopulationTeachingTest(unittest.TestCase):
    def build_runtime(self) -> tuple[WebGISRuntime, RuntimeStore, str]:
        temp_dir = tempfile.TemporaryDirectory()
        root_dir = Path(__file__).resolve().parents[2]
        config = AppConfig(root_dir=root_dir)
        config.data_dir = Path(temp_dir.name) / "backend" / "data"
        config.state_dir = config.data_dir / "state"
        config.uploads_dir = config.data_dir / "uploads"
        config.outputs_dir = config.data_dir / "outputs"
        config.state_file = config.state_dir / "runtime.json"
        config.ensure_dirs()
        store = RuntimeStore(config.state_file)
        runtime = WebGISRuntime(config=config, store=store)
        project_id = runtime.create_project()["project_id"]
        self.addCleanup(temp_dir.cleanup)
        return runtime, store, project_id

    def wait_for_job(self, store: RuntimeStore, job_id: str):
        for _ in range(300):
            job = store.get_job(job_id)
            if job is not None and job.status in {"completed", "failed"}:
                return job
            time.sleep(0.01)
        self.fail(f"job did not finish: {job_id}")

    def test_population_sources_are_versioned_traceable_and_drift_aware(self) -> None:
        runtime, store, project_id = self.build_runtime()

        payload = runtime.list_population_sources(project_id=project_id)

        self.assertEqual(payload["version"], "1.0.0")
        self.assertGreaterEqual(len(payload["items"]), 10)
        self.assertEqual(len(payload["pack_fingerprint"]), 64)
        density = next(item for item in payload["items"] if item["id"] == "population_density_china_2020")
        for field in (
            "source_name",
            "source_year",
            "spatial_scale",
            "field_unit",
            "license",
            "status",
            "fingerprint",
            "teaching_usage",
            "limitations",
        ):
            self.assertTrue(density[field], field)
        self.assertEqual(density["field_unit"], "人/平方千米")

        drift = runtime.get_population_source(
            density["id"],
            project_id=project_id,
            expected_fingerprint="outdated",
        )
        self.assertTrue(drift["drifted"])

        activated = runtime.activate_population_source_version(project_id, "1.0.0")
        self.assertEqual(activated["active_version"], "1.0.0")
        project = store.get_project(project_id)
        self.assertEqual(project.metadata["active_population_source_version"], "1.0.0")  # type: ignore[union-attr]

        comparison = runtime.compare_population_source_versions("0.9.0", "1.0.0")
        self.assertIn("china_aging_rate_2020", comparison["added"])
        self.assertIn("population_density_china_2020", comparison["unchanged"])
        rolled_back = runtime.activate_population_source_version(project_id, "0.9.0")
        self.assertEqual(rolled_back["active_version"], "0.9.0")
        restored = runtime.activate_population_source_version(project_id, "1.0.0")
        self.assertEqual(restored["active_version"], "1.0.0")

    def test_population_source_unknown_version_does_not_change_project(self) -> None:
        runtime, store, project_id = self.build_runtime()

        with self.assertRaises(KeyError):
            runtime.activate_population_source_version(project_id, "9.9.9")

        project = store.get_project(project_id)
        self.assertNotIn("active_population_source_version", project.metadata)  # type: ignore[union-attr]

    def test_population_prep_builds_grounded_draft_without_mutating_lesson(self) -> None:
        runtime, store, project_id = self.build_runtime()
        lesson = store.get_lesson(BUILTIN_LESSON_ID)
        before = lesson_content_fingerprint(lesson)  # type: ignore[arg-type]

        accepted = runtime.classroom.submit_population_lesson_prep(
            project_id,
            {
                "lesson_id": BUILTIN_LESSON_ID,
                "objective": "运用人口密度图和胡焕庸线解释中国人口分布格局",
                "duration_minutes": 15,
            },
        )
        job = self.wait_for_job(store, accepted["job_id"])

        self.assertEqual(job.status, "completed", job.error)
        self.assertEqual(lesson_content_fingerprint(store.get_lesson(BUILTIN_LESSON_ID)), before)  # type: ignore[arg-type]
        result = job.result
        self.assertEqual(result["capability"], "population_lesson_prep")
        self.assertEqual(result["rehearsal"]["status"], "passed")
        self.assertEqual(result["change_set"]["status"], "pending")
        proposed = result["change_set"]["proposed_lesson"]
        self.assertEqual(sum(stage["minutes"] for stage in proposed["stages"]), 15)
        self.assertTrue(result["evidence_refs"])
        for stage in proposed["stages"]:
            self.assertTrue(stage["evidence_refs"], stage["stage_id"])
            self.assertTrue(stage["teacher_guidance"], stage["stage_id"])
            for question in stage["questions"]:
                self.assertTrue(question["evidence_refs"], question["question_id"])
                self.assertGreaterEqual(len(question["argument_chain"]), 3)
        s4 = next(stage for stage in proposed["stages"] if stage["stage_id"] == "s4")
        self.assertEqual(s4["scene"]["globe"]["themes"], ["density_fill", "hu_line"])

    def test_population_prep_applies_only_teacher_selected_stages(self) -> None:
        runtime, store, project_id = self.build_runtime()
        accepted = runtime.classroom.submit_population_lesson_prep(
            project_id,
            {"lesson_id": BUILTIN_LESSON_ID, "duration_minutes": 40},
        )
        job = self.wait_for_job(store, accepted["job_id"])
        self.assertEqual(job.status, "completed", job.error)

        resolved = runtime.classroom.resolve_population_lesson_prep(
            job.job_id,
            "apply",
            accepted_stage_ids=["s4"],
        )

        self.assertEqual(resolved["applied_stage_ids"], ["s4"])
        updated = store.get_lesson(BUILTIN_LESSON_ID)
        self.assertTrue(updated.find_stage("s4")["teacher_guidance"])  # type: ignore[union-attr]
        self.assertEqual(updated.find_stage("s5")["teacher_guidance"], {})  # type: ignore[union-attr]
        self.assertEqual(updated.metadata["population_source_version"], "1.0.0")  # type: ignore[union-attr]
        with self.assertRaisesRegex(ValueError, "already been resolved"):
            runtime.classroom.resolve_population_lesson_prep(job.job_id, "apply", ["s5"])

    def test_population_prep_reject_keeps_lesson_unchanged(self) -> None:
        runtime, store, project_id = self.build_runtime()
        before = lesson_content_fingerprint(store.get_lesson(BUILTIN_LESSON_ID))  # type: ignore[arg-type]
        accepted = runtime.classroom.submit_population_lesson_prep(
            project_id,
            {"lesson_id": BUILTIN_LESSON_ID},
        )
        job = self.wait_for_job(store, accepted["job_id"])

        rejected = runtime.classroom.resolve_population_lesson_prep(job.job_id, "reject")

        self.assertEqual(rejected["decision"], "reject")
        self.assertEqual(lesson_content_fingerprint(store.get_lesson(BUILTIN_LESSON_ID)), before)  # type: ignore[arg-type]

    def test_population_prep_rejects_non_population_lesson(self) -> None:
        runtime, _store, project_id = self.build_runtime()
        lesson = runtime.classroom.create_lesson(
            {
                "title": "农业区位",
                "objectives": ["分析农业区位因素"],
                "stages": [{"stage_id": "s1", "title": "农业导入", "scene": {}}],
            }
        )

        with self.assertRaisesRegex(ValueError, "仅支持人口地理"):
            runtime.classroom.submit_population_lesson_prep(
                project_id,
                {"lesson_id": lesson["lesson_id"], "objective": "分析农业区位"},
            )

    def test_population_prep_refuses_to_reuse_answers_for_unavailable_year(self) -> None:
        runtime, store, project_id = self.build_runtime()
        accepted = runtime.classroom.submit_population_lesson_prep(
            project_id,
            {"lesson_id": BUILTIN_LESSON_ID, "years": ["2010"]},
        )

        job = self.wait_for_job(store, accepted["job_id"])

        self.assertEqual(job.status, "failed")
        self.assertIn("不能沿用其他年份", job.error)
