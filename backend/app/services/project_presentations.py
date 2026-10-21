"""Project-owned static presentations. Existing lesson exports are read, never migrated."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from threading import RLock
from uuid import uuid4

from PIL import Image

from . import resource_access
from .bounded_executor import ExecutorBusy
from .ppt_renderer import PptRenderError, render_pptx_to_images

RENDER_VERSION = "powerpoint-png-v1"


class ProjectPresentations:
    def __init__(self, config, store, knowledge=None):
        self.config, self.store, self.knowledge = config, store, knowledge
        self.lock = RLock()
        self.tasks = {}
        self.verified = {}

    def _project(self, project_id):
        project = self.store.get_project(project_id)
        if project is None:
            raise KeyError("项目不存在")
        return project

    def _registry(self, project_id):
        # IDs come from an authorized project record, never a filesystem argument.
        self._project(project_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
            raise ValueError("项目编号无效")
        path = self.config.outputs_dir / project_id / "presentations" / "library.json"
        if not resource_access.path_within(path, self.config.outputs_dir):
            raise ValueError("项目课件目录无效")
        return path

    def _read(self, project_id):
        path = self._registry(project_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _write(self, project_id, rows):
        path = self._registry(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def _owned_path(self, project_id, url, *, kb=False):
        path = resource_access.resolve_public_reference(self.config, url)
        roots = resource_access.project_grant_roots(self.config, project_id)
        if kb:
            roots += (self.config.uploads_dir / "kb_materials",)
        if path is None or not any(resource_access.path_within(path, root) for root in roots):
            raise ValueError("课件文件不属于此项目")
        if not path.is_file():
            raise ValueError("课件文件已失效")
        return path

    def _verify_slides(self, project_id, slides, *, expected, hashes=None):
        if not slides or len(slides) != expected:
            raise ValueError("课件页数不完整")
        dimensions = None
        for index, slide in enumerate(slides):
            if slide["index"] != index:
                raise ValueError("课件页面顺序无效")
            path = self._owned_path(project_id, slide["image_url"])
            fingerprint = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
            expected_hash = hashes[index] if hashes else None
            verified = self.verified.get(fingerprint)
            if not (isinstance(verified, tuple) and verified[1:] == (slide["width"], slide["height"])
                    and (expected_hash is None or verified[0] == expected_hash)):
                if expected_hash and hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                    raise ValueError("课件页面校验失败")
                with Image.open(path) as image:
                    image.load()
                    width, height = image.size
                if min(width, height) <= 0 or (width * 9525, height * 9525) != (slide["width"], slide["height"]):
                    raise ValueError("课件页面尺寸无效")
                self.verified[fingerprint] = (expected_hash, slide["width"], slide["height"])
            pair = (slide["width"], slide["height"])
            if dimensions and dimensions != pair:
                raise ValueError("课件页面比例不一致")
            dimensions = pair

    def _lesson_rows(self, project_id):
        project = self._project(project_id)
        rows = {}
        for lesson in self.store.list_lessons():
            meta = lesson.metadata or {}
            if meta.get("project_id") != project_id or not meta.get("source_file_name", "").lower().endswith((".ppt", ".pptx")):
                continue
            if lesson.owner_user_id != project.owner_user_id:
                continue
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", lesson.lesson_id):
                continue
            row = {"id": f"lesson_{lesson.lesson_id}", "title": lesson.title,
                   "file_name": meta["source_file_name"], "source_url": meta.get("source_url", ""),
                   "source_hash": meta.get("source_sha256", ""), "renderer": meta.get("preview_renderer", ""),
                   "status": "ready", "slides": [], "job_id": "", "error": "", "render_version": RENDER_VERSION}
            try:
                source = self._owned_path(project_id, row["source_url"])
                manifest = json.loads((source.parent / "render_manifest.json").read_text(encoding="utf-8"))
                source_key = (str(source), source.stat().st_mtime_ns, source.stat().st_size)
                if self.verified.get(source_key) != row["source_hash"]:
                    if hashlib.sha256(source.read_bytes()).hexdigest() != row["source_hash"]:
                        raise ValueError("课件原文件校验失败")
                    self.verified[source_key] = row["source_hash"]
                if manifest["source_sha256"] != row["source_hash"]:
                    raise ValueError("课件与预览来源不一致")
                for index, page in enumerate(manifest["slides"]):
                    relative = Path(page["file"])
                    if relative.is_absolute() or ".." in relative.parts or page["number"] != index + 1:
                        raise ValueError("课件页面顺序无效")
                    path = source.parent / relative
                    with Image.open(path) as image:
                        width, height = image.size
                    row["slides"].append({"index": index, "image_url": self.config.public_url_for_path(path),
                                          "width": width * 9525, "height": height * 9525})
                self._verify_slides(project_id, row["slides"], expected=manifest["slide_count"],
                                    hashes=[page["sha256"] for page in manifest["slides"]])
                if manifest["slide_count"] != meta.get("slide_count"):
                    raise ValueError("课件页数不一致")
            except (OSError, ValueError, KeyError, TypeError):
                row.update(status="failed", slides=[], error="已导入课件的页面或来源校验失败，请重新导入。")
            rows[row["id"]] = row
        return rows

    def _linked_rows(self, project_id):
        if self.knowledge is None:
            return {}
        project = self._project(project_id)
        sets = project.metadata.get("lesson_resource_sets", [])
        item_ids = {x for group in sets for x in group.get("item_ids", [])}
        material_ids = {x for group in sets for x in group.get("material_ids", [])}
        rows = {}
        manifest = self.knowledge.get_manifest(owner_user_id=project.owner_user_id, include_all=False)
        for item in manifest.get("items", []):
            for material in item.get("materials", []):
                if item["id"] not in item_ids and material["id"] not in material_ids:
                    continue
                if not material.get("url", "").lower().endswith((".ppt", ".pptx")):
                    continue
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", material["id"]):
                    continue
                try:
                    path = self._owned_path(project_id, material["url"], kb=True)
                except ValueError:
                    continue
                key = f"material_{material['id']}"
                rows[key] = {"id": key, "title": material["title"], "file_name": path.name,
                             "source_url": material["url"], "status": "pending", "slides": [],
                             "renderer": "", "job_id": "", "error": "", "render_version": RENDER_VERSION}
        return rows

    def _rows(self, project_id):
        rows = {**self._linked_rows(project_id), **self._lesson_rows(project_id), **self._read(project_id)}
        for row in rows.values():
            if row.get("render_version") != RENDER_VERSION:
                row.update(status="pending", slides=[], render_version=RENDER_VERSION)
            if row["status"] == "ready":
                try:
                    self._verify_slides(project_id, row["slides"], expected=len(row["slides"]))
                except (OSError, ValueError):
                    row.update(status="failed", slides=[], error="课件页面已失效，请点击重试准备课件。")
            if row["status"] in {"queued", "running"} and (project_id, row["id"]) not in self.tasks:
                row.update(status="failed", error="课件转换已中断，请点击重试。")
        return rows

    def list(self, project_id):
        with self.lock:
            result = []
            for row in self._rows(project_id).values():
                item = {k: v for k, v in row.items() if k not in {"slides", "source_url", "request_ids"}}
                item["page_count"] = len(row["slides"])
                item["cover_url"] = row["slides"][0]["image_url"] if row["slides"] else ""
                result.append(item)
            return {"items": result}

    def get(self, project_id, presentation_id):
        with self.lock:
            row = self._rows(project_id).get(presentation_id)
            if row is None:
                raise KeyError("课件不存在")
            if row["status"] == "ready":
                try:
                    self._verify_slides(project_id, row["slides"], expected=len(row["slides"]))
                except (OSError, ValueError):
                    row.update(status="failed", slides=[], error="课件页面已失效，请重新准备课件。")
            return {k: deepcopy(v) for k, v in row.items() if k not in {"source_url", "request_ids"}}

    def import_file(self, project_id, name, raw, request_id):
        suffix = Path(name).suffix.lower()
        if suffix not in {".ppt", ".pptx"} or not raw:
            raise ValueError("请选择非空的 .ppt 或 .pptx 课件")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
            raise ValueError("导入编号无效")
        digest = hashlib.sha256(raw).hexdigest()
        key = "ppt_" + digest
        with self.lock:
            rows = self._read(project_id)
            for row in rows.values():
                if request_id in row.get("request_ids", [row.get("import_request_id")]) and row.get("source_hash") != digest:
                    raise ValueError("导入编号已用于另一份课件")
            if key not in rows:
                source = self.config.uploads_dir / project_id / "presentations" / key / ("source" + suffix)
                if not resource_access.path_within(source, self.config.uploads_dir):
                    raise ValueError("项目课件目录无效")
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(raw)
                rows[key] = {"id": key, "title": Path(name).stem, "file_name": Path(name).name,
                             "source_url": self.config.public_url_for_path(source), "source_hash": digest,
                             "status": "pending", "slides": [], "renderer": "", "job_id": "", "error": "",
                             "render_version": RENDER_VERSION, "import_request_id": request_id, "request_ids": [request_id]}
                self._write(project_id, rows)
            elif rows[key].get("import_request_id") != request_id:
                rows[key]["import_request_id"] = request_id
                rows[key].setdefault("request_ids", []).append(request_id)
                self._write(project_id, rows)
            return key

    def start(self, project_id, presentation_id, executor, *, retry=False):
        with self.lock:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", presentation_id):
                raise KeyError("课件不存在")
            key = (project_id, presentation_id)
            row = self._rows(project_id).get(presentation_id)
            if row is None:
                raise KeyError("课件不存在")
            if key in self.tasks or row["status"] == "ready" or (row["status"] == "failed" and not retry):
                return self.get(project_id, presentation_id)
            if len(self.tasks) >= 2:
                raise ExecutorBusy("课件转换繁忙，请稍后准备课件。")
            source = self._owned_path(project_id, row["source_url"], kb=presentation_id.startswith("material_"))
            rows = self._read(project_id)
            row.update(status="queued", job_id="ppt_job_" + uuid4().hex, error="")
            row["source_hash"] = hashlib.sha256(source.read_bytes()).hexdigest()
            rows[presentation_id] = row
            self._write(project_id, rows)
            task = asyncio.create_task(self._render(project_id, presentation_id, source, executor))
            self.tasks[key] = task
            return self.get(project_id, presentation_id)

    async def _render(self, project_id, presentation_id, source, executor):
        changes = {"status": "failed", "error": "课件转换已中断，请点击重试。"}
        try:
            with self.lock:
                rows = self._read(project_id)
                row = rows[presentation_id]
                row["status"] = "running"
                self._write(project_id, rows)
            result = await executor.run(
                lambda: render_pptx_to_images(self.config, row["file_name"], source.read_bytes(),
                                             powerpoint_only=True,
                                             output_root=self.config.outputs_dir / project_id / "presentations" / presentation_id)
            )
            self._verify_slides(project_id, result["slides"], expected=len(result["slides"]))
            changes = {"status": "ready", "slides": result["slides"], "renderer": result["renderer"], "error": "",
                       "font_dependencies": result.get("font_dependencies", [])}
        except asyncio.CancelledError:
            changes = {"status": "failed", "error": "课件转换已中断，请点击重试。"}
        except Exception as error:
            message = error.message if isinstance(error, PptRenderError) else str(error) if isinstance(error, ExecutorBusy) else "课件转换或页面校验失败，请检查原文件后重试。"
            changes = {"status": "failed", "error": message}
        finally:
            try:
                with self.lock:
                    rows = self._read(project_id)
                    rows[presentation_id].update(changes)
                    self._write(project_id, rows)
            finally:
                with self.lock:
                    self.tasks.pop((project_id, presentation_id), None)

    async def close(self):
        if self.tasks:
            await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)
