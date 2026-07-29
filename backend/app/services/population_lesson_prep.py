from __future__ import annotations

import copy
import hashlib
import json
import threading
from typing import Any, Dict, List

from ..models import LessonRecord, build_dynamic_stages, utc_now
from ..store import RuntimeStore
from .lessons import LessonService
from .population_sources import PopulationSourceRegistryService


PREP_STAGE_KEYS = (
    "objective",
    "sources",
    "inquiry",
    "rehearsal",
    "draft",
)

ALLOWED_GLOBE_THEME_IDS = {
    "population_columns",
    "density_fill",
    "density_3d",
    "hu_line",
    "climate_zones",
    "migration_flows",
}

POPULATION_KEYWORDS = (
    "人口",
    "population",
    "胡焕庸",
    "密度",
    "迁移",
    "城镇化",
    "老龄",
    "年龄结构",
)

STAGE_SOURCE_HINTS: Dict[str, List[str]] = {
    "s1": ["population_density_china_2020", "kb_population_pattern"],
    "s2": ["population_density_china_2020", "kb_population_density"],
    "s3": ["population_density_china_2020", "lesson_population_distribution_v4"],
    "s4": ["population_density_china_2020", "hu_line_1935", "kb_hu_line"],
    "s5": [
        "population_density_china_2020",
        "china_climate_types",
        "china_terrain_steps",
        "china_major_rivers",
        "china_vegetation_zones",
        "china_gdp_per_capita",
    ],
    "s6": ["shanghai_population_density_2020", "china_aging_rate_2020"],
    "s7": ["population_density_china_2020", "hu_line_1935", "kb_population_pattern"],
    "s8": ["population_density_china_2020", "kb_population_pattern"],
}

GLOBE_BINDINGS: Dict[str, Dict[str, Any]] = {
    "s4": {
        "enabled": True,
        "themes": ["density_fill", "hu_line"],
        "camera": {"lon": 103.8, "lat": 36.0, "altitudeMeters": 7200000.0, "pitchDeg": -90.0},
    },
    "s5": {
        "enabled": True,
        "themes": ["density_fill", "climate_zones"],
        "camera": {"lon": 104.0, "lat": 8.0, "altitudeMeters": 4800000.0, "pitchDeg": -48.0},
    },
    "s7": {
        "enabled": True,
        "themes": ["density_3d", "hu_line"],
        "camera": {"lon": 105.0, "lat": 9.0, "altitudeMeters": 5200000.0, "pitchDeg": -50.0},
    },
}


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def lesson_content_fingerprint(lesson: LessonRecord | Dict[str, Any]) -> str:
    raw = lesson.to_dict() if isinstance(lesson, LessonRecord) else dict(lesson)
    payload = {
        key: raw.get(key)
        for key in ("lesson_id", "title", "subject", "grade", "objectives", "stages", "source", "metadata")
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


class PopulationLessonPrepService:
    """Teacher-facing, source-grounded population lesson preparation pipeline."""

    def __init__(
        self,
        store: RuntimeStore,
        lessons: LessonService,
        sources: PopulationSourceRegistryService,
    ):
        self.store = store
        self.lessons = lessons
        self.sources = sources

    def submit(self, project_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.store.get_project(project_id) is None:
            raise KeyError(f"Unknown project: {project_id}")
        lesson_id = str(payload.get("lesson_id") or "").strip()
        lesson = self.lessons.get_lesson(lesson_id)
        request = self._normalize_request(lesson, payload)
        self._require_population_scope(lesson, request)
        job = self.store.create_job(
            project_id=project_id,
            job_type="population_lesson_prep",
            title=f"人口专题智能备课：{lesson.title}",
            workflow_type="population_lesson_prep",
            request=request,
            stages=build_dynamic_stages(list(PREP_STAGE_KEYS)),
        )
        threading.Thread(target=self._run, args=(job.job_id,), daemon=True).start()
        return {
            "status": "accepted",
            "capability": "population_lesson_prep",
            "job_id": job.job_id,
            "project_id": project_id,
            "lesson_id": lesson_id,
        }

    def resolve_change_set(
        self,
        job_id: str,
        decision: str,
        accepted_stage_ids: Any = None,
    ) -> Dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None or job.job_type != "population_lesson_prep":
            raise KeyError(f"Unknown population lesson prep change set: {job_id}")
        if job.status != "completed":
            raise ValueError("Population lesson prep job has not completed")
        result = copy.deepcopy(job.result or {})
        change_set = dict(result.get("change_set") or {})
        if not change_set:
            raise ValueError("Population lesson prep job produced no change set")
        if str(change_set.get("status") or "") != "pending":
            raise ValueError("Population lesson prep change set has already been resolved")

        normalized_decision = "reject" if str(decision).strip().lower() == "reject" else "apply"
        if normalized_decision == "reject":
            change_set["status"] = "rejected"
            change_set["resolved_at"] = utc_now()
            result["change_set"] = change_set
            self.store.set_job_status(job_id, "completed", result=result)
            return {
                "status": "success",
                "decision": "reject",
                "change_set_id": change_set["change_set_id"],
            }

        lesson_id = str(change_set.get("lesson_id") or "")
        lesson = self.lessons.get_lesson(lesson_id)
        current_fingerprint = lesson_content_fingerprint(lesson)
        if current_fingerprint != str(change_set.get("base_lesson_fingerprint") or ""):
            raise ValueError("Lesson changed after the draft was generated; regenerate before applying")

        proposed = dict(change_set.get("proposed_lesson") or {})
        proposed_stages = [item for item in proposed.get("stages") or [] if isinstance(item, dict)]
        proposed_ids = {str(item.get("stage_id") or "") for item in proposed_stages}
        requested_ids = {
            str(item)
            for item in (accepted_stage_ids if isinstance(accepted_stage_ids, list) else proposed_ids)
            if str(item)
        }
        accepted = proposed_ids.intersection(requested_ids)
        if not accepted:
            raise ValueError("Select at least one proposed stage to apply")

        replacements = {
            str(item.get("stage_id") or ""): item
            for item in proposed_stages
            if str(item.get("stage_id") or "") in accepted
        }
        merged_stages: List[Dict[str, Any]] = []
        seen = set()
        for existing in lesson.stages:
            stage_id = str(existing.get("stage_id") or "")
            merged_stages.append(copy.deepcopy(replacements.get(stage_id, existing)))
            seen.add(stage_id)
        for stage_id, stage in replacements.items():
            if stage_id not in seen:
                merged_stages.append(copy.deepcopy(stage))

        metadata = {
            **lesson.metadata,
            **dict(proposed.get("metadata") or {}),
            "last_population_prep_change_set_id": change_set["change_set_id"],
            "last_population_prep_applied_at": utc_now(),
        }
        updated = self.lessons.update_lesson(
            lesson_id,
            {
                "objectives": proposed.get("objectives") or lesson.objectives,
                "stages": merged_stages,
                "metadata": metadata,
            },
        )
        change_set["status"] = "applied"
        change_set["resolved_at"] = utc_now()
        change_set["applied_stage_ids"] = sorted(accepted)
        change_set["applied_lesson_fingerprint"] = lesson_content_fingerprint(updated)
        result["change_set"] = change_set
        self.store.set_job_status(job_id, "completed", result=result)
        return {
            "status": "success",
            "decision": "apply",
            "change_set_id": change_set["change_set_id"],
            "applied_stage_ids": sorted(accepted),
            "lesson": updated.to_dict(),
        }

    def _run(self, job_id: str) -> None:
        current_stage = "objective"
        try:
            job = self.store.get_job(job_id)
            if job is None:
                return
            request = dict(job.request or {})
            lesson = self.lessons.get_lesson(str(request.get("lesson_id") or ""))
            self.store.set_job_status(job_id, "running")

            self.store.update_job_stage(job_id, current_stage, "running", "正在校验人口专题目标与课时约束。")
            self._require_population_scope(lesson, request)
            self.store.update_job_stage(job_id, "objective", "success", "已确认教师端人口地理备课范围。")

            current_stage = "sources"
            self.store.update_job_stage(job_id, current_stage, "running", "正在装配版本化人口来源与地图证据。")
            source_pack = self.sources.list_sources(
                project_id=job.project_id,
                version=str(request.get("source_version") or ""),
            )
            selected_cards = self._select_sources(source_pack["items"], request.get("source_ids"))
            self._validate_requested_years(request, selected_cards)
            self.store.update_job_stage(
                job_id,
                "sources",
                "success",
                f"已锁定 {len(selected_cards)} 条来源，版本 {source_pack['version']}。",
            )

            current_stage = "inquiry"
            self.store.update_job_stage(job_id, current_stage, "running", "正在生成题—图—证据探究链。")
            proposed_lesson = self._build_proposed_lesson(lesson, request, source_pack, selected_cards)
            changes = self._build_changes(lesson, proposed_lesson)
            self.store.update_job_stage(
                job_id,
                "inquiry",
                "success",
                f"已形成 {len(proposed_lesson['stages'])} 个教师教学环节。",
            )

            current_stage = "rehearsal"
            self.store.update_job_stage(job_id, current_stage, "running", "正在检查来源、图层、年份、题图证据和三维场景。")
            rehearsal = self._rehearse(proposed_lesson, selected_cards)
            if rehearsal["errors"]:
                raise ValueError("备课预演未通过：" + "；".join(rehearsal["errors"]))
            self.store.update_job_stage(
                job_id,
                "rehearsal",
                "success",
                f"预演通过，{len(rehearsal['warnings'])} 条教学提示待教师查看。",
            )

            current_stage = "draft"
            self.store.update_job_stage(job_id, current_stage, "running", "正在生成教师确认式变更草稿。")
            source_refs = [self.sources.reference_for(card) for card in selected_cards]
            change_set = {
                "change_set_id": job_id,
                "status": "pending",
                "lesson_id": lesson.lesson_id,
                "base_lesson_fingerprint": lesson_content_fingerprint(lesson),
                "source_version": source_pack["version"],
                "source_pack_fingerprint": source_pack["pack_fingerprint"],
                "source_refs": source_refs,
                "changes": changes,
                "proposed_lesson": proposed_lesson,
                "created_at": utc_now(),
            }
            result = {
                "status": "success",
                "capability": "population_lesson_prep",
                "job_id": job_id,
                "stage": "draft",
                "progress": 1.0,
                "outputs": [
                    {
                        "type": "lesson_change_set",
                        "change_set_id": job_id,
                        "stage_count": len(proposed_lesson["stages"]),
                    }
                ],
                "evidence_refs": source_refs,
                "warnings": rehearsal["warnings"],
                "rehearsal": rehearsal,
                "change_set_id": job_id,
                "change_set": change_set,
                "generator": "population_grounded_pipeline",
                "stages": self.store.get_job(job_id).stages,
            }
            self.store.update_job_stage(job_id, "draft", "success", "备课草稿已生成，等待教师逐环节确认。")
            result["stages"] = self.store.get_job(job_id).stages
            self.store.set_job_status(job_id, "completed", result=result)
        except Exception as exc:  # pragma: no cover - exercised through public failure state
            job = self.store.get_job(job_id)
            if job is not None:
                self.store.update_job_stage(job_id, current_stage, "error", str(exc))
                self.store.set_job_status(job_id, "failed", error=str(exc))

    def _normalize_request(self, lesson: LessonRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
        objective = str(payload.get("objective") or "").strip()
        if not objective:
            objective = "；".join(lesson.objectives) or lesson.title
        years = [str(item) for item in payload.get("years") or [] if str(item)]
        source_ids = [str(item) for item in payload.get("source_ids") or [] if str(item)]
        duration = payload.get("duration_minutes")
        if not isinstance(duration, int) or isinstance(duration, bool):
            duration = int((lesson.metadata or {}).get("duration_minutes") or sum(int(stage.get("minutes") or 0) for stage in lesson.stages) or 40)
        return {
            "lesson_id": lesson.lesson_id,
            "objective": objective[:1000],
            "grade": str(payload.get("grade") or lesson.grade),
            "duration_minutes": max(10, min(int(duration), 180)),
            "region": str(payload.get("region") or "中国"),
            "years": years or ["2020"],
            "source_ids": source_ids,
            "source_version": str(payload.get("source_version") or ""),
        }

    def _require_population_scope(self, lesson: LessonRecord, request: Dict[str, Any]) -> None:
        haystack = " ".join(
            [
                lesson.title,
                " ".join(lesson.objectives),
                str(request.get("objective") or ""),
            ]
        ).lower()
        if not any(keyword.lower() in haystack for keyword in POPULATION_KEYWORDS):
            raise ValueError("当前示范范围仅支持人口地理教学单元")

    def _select_sources(self, cards: List[Dict[str, Any]], requested: Any) -> List[Dict[str, Any]]:
        by_id = {card["id"]: card for card in cards}
        requested_ids = [str(item) for item in requested or [] if str(item)]
        if requested_ids:
            missing = [source_id for source_id in requested_ids if source_id not in by_id]
            if missing:
                raise ValueError("未知人口来源：" + "、".join(missing))
            return [by_id[source_id] for source_id in requested_ids]
        return list(cards)

    def _validate_requested_years(self, request: Dict[str, Any], cards: List[Dict[str, Any]]) -> None:
        requested = {str(item) for item in request.get("years") or [] if str(item)}
        available = {
            str(card.get("source_year") or "")
            for card in cards
            if str(card.get("source_year") or "").isdigit() and len(str(card.get("source_year") or "")) == 4
        }
        missing = sorted(requested - available)
        if missing:
            raise ValueError(
                "当前来源包没有请求年份的数据："
                + "、".join(missing)
                + "；不能沿用其他年份的题目答案"
            )

    def _build_proposed_lesson(
        self,
        lesson: LessonRecord,
        request: Dict[str, Any],
        source_pack: Dict[str, Any],
        selected_cards: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        selected_by_id = {card["id"]: card for card in selected_cards}
        fallback_cards = selected_cards[:2]
        stages: List[Dict[str, Any]] = []
        for raw_stage in lesson.stages:
            stage = copy.deepcopy(raw_stage)
            stage_id = str(stage.get("stage_id") or "")
            hinted = [selected_by_id[source_id] for source_id in STAGE_SOURCE_HINTS.get(stage_id, []) if source_id in selected_by_id]
            stage_cards = hinted or fallback_cards
            evidence_refs = [self.sources.reference_for(card) for card in stage_cards]
            stage["evidence_refs"] = evidence_refs
            stage["teacher_guidance"] = self._teacher_guidance(stage, stage_cards)
            scene = dict(stage.get("scene") or {})
            if stage_id in GLOBE_BINDINGS:
                scene["globe"] = copy.deepcopy(GLOBE_BINDINGS[stage_id])
            stage["scene"] = scene
            for question in stage.get("questions") or []:
                if not isinstance(question, dict):
                    continue
                question["evidence_refs"] = evidence_refs
                expected = [str(item) for item in question.get("expected_points") or [] if str(item)]
                question["argument_chain"] = [
                    "确认图名、图例、统计年份和空间尺度",
                    "定位并比较题目要求的区域",
                    expected[0] if expected else "引用至少一条地图证据",
                    expected[-1] if len(expected) > 1 else "由证据形成地理结论",
                ]
                misconception = next(
                    (
                        str(item.get("description") or item.get("tag") or "")
                        for item in question.get("misconceptions") or []
                        if isinstance(item, dict)
                    ),
                    "",
                )
                question["remediation_task"] = (
                    f"重新显示本题证据图层，让学生按“区域—现象—原因”复述。{misconception}"
                ).strip()
            stages.append(stage)

        self._rebalance_minutes(stages, int(request["duration_minutes"]))
        metadata = {
            **lesson.metadata,
            "population_topic": True,
            "population_prep_objective": request["objective"],
            "population_source_version": source_pack["version"],
            "population_source_pack_fingerprint": source_pack["pack_fingerprint"],
            "population_source_refs": [self.sources.reference_for(card) for card in selected_cards],
            "population_data_years": list(request.get("years") or []),
            "population_prep_generated_at": utc_now(),
        }
        return {
            "lesson_id": lesson.lesson_id,
            "title": lesson.title,
            "subject": lesson.subject,
            "grade": request["grade"],
            "objectives": list(lesson.objectives) or [request["objective"]],
            "stages": stages,
            "source": lesson.source,
            "metadata": metadata,
        }

    def _teacher_guidance(self, stage: Dict[str, Any], cards: List[Dict[str, Any]]) -> Dict[str, Any]:
        questions = [item for item in stage.get("questions") or [] if isinstance(item, dict)]
        first_question = questions[0] if questions else {}
        expected = [str(item) for item in first_question.get("expected_points") or [] if str(item)]
        misconceptions = [
            str(item.get("tag") or "")
            for item in first_question.get("misconceptions") or []
            if isinstance(item, dict) and str(item.get("tag") or "")
        ]
        return {
            "observation_prompt": f"观察“{stage.get('title', '')}”场景，先找图例、年份和空间差异。",
            "evidence_points": [str(card.get("title") or "") for card in cards],
            "oral_question": str(first_question.get("text") or "请用地图证据描述你观察到的人口地理现象。"),
            "expected_response": "；".join(expected[:3]) or "能指出区域差异，并引用图中证据说明。",
            "misconception_cue": "、".join(misconceptions[:3]) or "注意避免只报结论、不引用地图证据。",
            "closing": f"用“区域—证据—解释”收束{stage.get('title', '本环节')}。",
            "fallback": "若三维场景加载异常，立即使用同环节二维专题图和教师串联语继续教学。",
        }

    def _rebalance_minutes(self, stages: List[Dict[str, Any]], target: int) -> None:
        if not stages:
            return
        current = sum(max(1, int(stage.get("minutes") or 1)) for stage in stages)
        if current == target:
            return
        raw = [max(1, int(stage.get("minutes") or 1)) * target / current for stage in stages]
        allocated = [max(1, int(value)) for value in raw]
        while sum(allocated) < target:
            index = max(range(len(raw)), key=lambda idx: raw[idx] - allocated[idx])
            allocated[index] += 1
        while sum(allocated) > target:
            candidates = [idx for idx, value in enumerate(allocated) if value > 1]
            if not candidates:
                break
            index = min(candidates, key=lambda idx: raw[idx] - allocated[idx])
            allocated[index] -= 1
        for stage, minutes in zip(stages, allocated):
            stage["minutes"] = minutes

    def _build_changes(self, lesson: LessonRecord, proposed: Dict[str, Any]) -> List[Dict[str, Any]]:
        before = {str(stage.get("stage_id") or ""): stage for stage in lesson.stages}
        changes = []
        for stage in proposed["stages"]:
            stage_id = str(stage.get("stage_id") or "")
            previous = before.get(stage_id, {})
            change_types = ["证据引用", "标准论证链", "教师环节指导"]
            if stage_id in GLOBE_BINDINGS:
                change_types.append("三维教学场景")
            changes.append(
                {
                    "stage_id": stage_id,
                    "title": str(stage.get("title") or ""),
                    "change_types": change_types,
                    "before_fingerprint": hashlib.sha256(_canonical_json(previous)).hexdigest(),
                    "after_fingerprint": hashlib.sha256(_canonical_json(stage)).hexdigest(),
                    "evidence_count": len(stage.get("evidence_refs") or []),
                    "question_count": len(stage.get("questions") or []),
                }
            )
        return changes

    def _rehearse(self, proposed: Dict[str, Any], cards: List[Dict[str, Any]]) -> Dict[str, Any]:
        errors: List[str] = []
        warnings: List[str] = []
        source_ids = {str(card.get("id") or "") for card in cards}
        for card in cards:
            source_id = str(card.get("id") or "")
            for field, label in (("source_year", "年份"), ("license", "许可证")):
                if not str(card.get(field) or ""):
                    errors.append(f"{source_id} 缺少{label}")
            status = str(card.get("status") or "")
            if status in {"schematic", "estimated"}:
                warnings.append(f"{card.get('title', source_id)} 为{status}数据，课堂必须显示限制说明。")
            if not str(card.get("source_url") or ""):
                warnings.append(f"{card.get('title', source_id)} 未提供在线来源链接，请保留来源名称与限制说明。")

        for stage in proposed.get("stages") or []:
            stage_id = str(stage.get("stage_id") or "")
            refs = [str(item.get("source_id") or "") for item in stage.get("evidence_refs") or [] if isinstance(item, dict)]
            if not refs:
                errors.append(f"{stage_id} 没有地图或知识证据")
            missing = [source_id for source_id in refs if source_id not in source_ids]
            if missing:
                errors.append(f"{stage_id} 引用了未选来源：{'、'.join(missing)}")
            globe = dict((stage.get("scene") or {}).get("globe") or {})
            if globe.get("enabled"):
                unknown = [theme for theme in globe.get("themes") or [] if str(theme) not in ALLOWED_GLOBE_THEME_IDS]
                if unknown:
                    errors.append(f"{stage_id} 包含未知三维主题：{'、'.join(str(item) for item in unknown)}")
                camera = dict(globe.get("camera") or {})
                if not all(key in camera for key in ("lon", "lat", "altitudeMeters", "pitchDeg")):
                    errors.append(f"{stage_id} 三维相机参数不完整")
            for question in stage.get("questions") or []:
                question_id = str(question.get("question_id") or "")
                if not question.get("evidence_refs"):
                    errors.append(f"{question_id} 没有题图证据")
                if len(question.get("argument_chain") or []) < 3:
                    errors.append(f"{question_id} 没有完整标准论证链")

        return {
            "status": "passed" if not errors else "failed",
            "errors": errors,
            "warnings": list(dict.fromkeys(warnings)),
            "checks": {
                "population_scope": True,
                "source_count": len(cards),
                "stage_count": len(proposed.get("stages") or []),
                "question_count": sum(len(stage.get("questions") or []) for stage in proposed.get("stages") or []),
                "duration_minutes": sum(int(stage.get("minutes") or 0) for stage in proposed.get("stages") or []),
            },
        }
