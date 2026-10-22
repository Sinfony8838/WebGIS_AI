"""Scoped, replay-safe measurement/profile tools over the existing samplers."""
from __future__ import annotations
import json
import re
from pathlib import Path
from uuid import uuid4
from . import map_profiles
from .interaction_run import current_run

class ProfileOperations:
    def __init__(self, runtime):
        self.runtime = runtime

    def _scope(self):
        run = current_run()
        if run is None:
            raise ValueError("剖面操作必须属于助教任务")
        run.check()
        job = self.runtime.store.get_job(run.job_id)
        return run, job, {"project_id": job.project_id, "conversation_id": job.request.get("conversation_id", ""), "actor_user_id": job.request.get("actor_user_id", "")}

    def _save(self, kind, value):
        run, job, scope = self._scope()
        result_id = kind + "_" + uuid4().hex
        value = {**value, "result_id": result_id, "scope": scope}
        if kind == "measurement": value["id"] = result_id
        root = self.runtime.config.project_output_dir(job.project_id) / "assistant_profiles"
        root.mkdir(parents=True, exist_ok=True)
        (root / (result_id + ".json")).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        run.resources[kind] = result_id
        return value

    def _load(self, kind, ref):
        run, job, scope = self._scope()
        ref = str(ref or "current")
        if ref == "current":
            ref = run.resources.get(kind, "")
            if not ref:
                candidates = [o.get("result", {}).get(kind + "_id") for o in run.observations if o.get("status") == "success"]
                ref = next((r for r in reversed(candidates) if r), "")
        if not re.fullmatch(re.escape(kind) + r"_[0-9a-f]{32}", ref):
            raise ValueError("请先创建测线或指定本会话中成功生成的结果")
        path = self.runtime.config.project_output_dir(job.project_id) / "assistant_profiles" / (ref + ".json")
        if not path.exists():
            raise ValueError("结果不存在，请重新生成")
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("scope") != scope:
            raise ValueError("结果不属于当前用户、项目与会话")
        return result

    def execute(self, project_id, action, context):
        run, job, _ = self._scope()
        if job.project_id != project_id:
            raise ValueError("项目作用域不匹配")
        project = self.runtime._require_project(project_id)
        params, tool = action.get("tool_params", {}), action["tool_name"]
        cache = self.runtime.config.data_dir / "cache" / "map_profiles"
        if tool == "create_measurement":
            locations = params["locations"]
            seeds = json.loads((Path(__file__).resolve().parents[1] / "data/builtin/one_map/population/china_province_population_density.geojson").read_text(encoding="utf-8"))
            coordinates, names = [], []
            for name in locations:
                matches = [f["properties"] for f in seeds["features"] if name in {f["properties"].get("name"), f["properties"].get("short_name")}]
                if len(matches) != 1:
                    raise ValueError(f"地名“{name}”未唯一解析，请指定省级城市中心。")
                coordinates.append(matches[0]["center"])
                names.append(matches[0]["name"])
            vertices, distances = map_profiles._line(coordinates)
            record = self._save("measurement", {"coordinates": coordinates, "name": "—".join(names), "totalKm": distances[-1] / 1000,
                "displayCoordinates": [[p["lon"], p["lat"]] for p in map_profiles._sample_points(vertices, distances, 241)],
                "color": "#4f7cff", "coordinate_source": "内置行政中心点（近似位置）", "crs": "EPSG:4326"})
            return {"status": "success", "measurement_id": record["result_id"], "measurement": record,
                "assistant_message": f"已创建{record['name']}测线，约 {record['totalKm']:.2f} 千米。",
                "ui_actions": [{"type": "create_measurement", "record": record}], "artifacts": []}
        record = self._load("measurement", params.get("measurement_id"))
        if tool == "generate_profile":
            kind = params["kind"]
            source = "gpw_2020" if kind == "population" else "mapzen_terrain"
            data = map_profiles.cached_preview(project, record["coordinates"], kind, source, cache)
            result = self._save(kind, {"measurement_id": record["result_id"], "profile": data})
            return {"status": "success" if data["no_data_count"] < len(data["samples"]) else "partial", kind + "_id": result["result_id"],
                "measurement_id": record["result_id"], "source_name": data["source_name"], "source_year": data["source_year"],
                "no_data_count": data["no_data_count"], "assistant_message": f"已采样{data['source_name']}，缺失 {data['no_data_count']} 点。", "artifacts": []}
        population = self._load("population", params.get("population_id"))
        terrain = self._load("terrain", params.get("terrain_id"))
        if any(item["measurement_id"] != record["result_id"] for item in (population, terrain)):
            raise ValueError("人口与地形结果必须来自同一条测线")
        result = self._save("comparison", {**map_profiles.compare_results(population["profile"], terrain["profile"]), "measurement_id": record["result_id"]})
        return {"status": result["status"], "comparison_id": result["result_id"], "measurement_id": record["result_id"],
            "summary": result["summary"], "paired_valid_count": result["paired_valid_count"], "interpretation_note": result["interpretation_note"],
            "assistant_message": f"双曲线已生成，共 {result['paired_valid_count']} 个位置同时具有人口与高程数据。",
            "ui_actions": [{"type": "show_profile_comparison", "record": {**record, "id": record["result_id"]}, "comparison": result}], "artifacts": []}
