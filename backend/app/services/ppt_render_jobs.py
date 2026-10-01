"""Async PPT render jobs with a per-user, content-hash cache.

``start_render_job`` registers a job, spawns a daemon thread and returns
immediately; the thread renders page 1 first (PowerPoint per-slide export or
LibreOffice PDF page-by-page rasterization) and appends further slides as they
finish, so the frontend can poll ``get_render_job`` and show pages early.

Successful results are cached on disk under
``outputs/ppt_previews/cache/v1/<render_id>`` where ``render_id`` is derived
from the user id and the file content hash, so re-opening the same file is
instant and survives API restarts. Cache entries expire after
``CACHE_MAX_AGE_SECONDS`` and the cache is capped at ``CACHE_MAX_TOTAL_BYTES``.

This is sized for the local single-machine deployment: one render at a time,
one active job per user. COM automation stays in the ppt_renderer_worker
subprocess (Microsoft does not support unattended in-process Office
automation).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..config import AppConfig
from . import ppt_renderer
from .ppt_renderer import DEFAULT_EXPORT_WIDTH, EMU_PER_PX, PptRenderError

CACHE_VERSION = "v1"
CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
CACHE_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
CLEANUP_MIN_INTERVAL_SECONDS = 60
POLL_INTERVAL_SECONDS = 0.25
NO_PROGRESS_TIMEOUT_SECONDS = 60
TOTAL_TIMEOUT_SECONDS = 300

STATUS_QUEUED = "queued"
STATUS_RENDERING = "rendering"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"


@dataclass
class PptRenderJob:
    render_id: str
    user_id: str
    cache_dir: Path
    file_name: str
    expected_slides: int = 0
    status: str = STATUS_QUEUED
    renderer: str = ""
    slide_width_px: int = 0
    slide_height_px: int = 0
    slides: List[Dict[str, Any]] = field(default_factory=list)
    error: Dict[str, Any] | None = None
    attempts: List[Dict[str, str]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    done_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)


_jobs: Dict[str, PptRenderJob] = {}
_registry_lock = threading.Lock()
_render_semaphore = threading.Semaphore(1)
_cleanup_lock = threading.Lock()
_last_cleanup = 0.0


def start_render_job(config: AppConfig, user_id: str, filename: str, raw_bytes: bytes) -> Dict[str, Any]:
    if not raw_bytes:
        raise PptRenderError("EMPTY_PPTX", "Uploaded PPT file is empty.", status_code=400)
    safe_name = ppt_renderer._safe_filename(filename or "presentation.pptx")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".pptx", ".ppt"}:
        raise PptRenderError("UNSUPPORTED_PPT_FORMAT", "Only .pptx and .ppt files can be rendered.", status_code=400)

    file_hash = hashlib.sha256(raw_bytes).hexdigest()
    render_id = _render_id_for(user_id, file_hash)
    cache_dir = _cache_dir_for(config, render_id)

    _maybe_cleanup_cache(config)

    with _registry_lock:
        existing = _jobs.get(render_id)
        if existing is not None and not existing.done_event.is_set():
            return job_payload(config, existing, cached=False)

    cached = _load_cached_payload(config, render_id, user_id)
    if cached is not None:
        return cached

    job = PptRenderJob(
        render_id=render_id,
        user_id=user_id,
        cache_dir=cache_dir,
        file_name=safe_name,
        expected_slides=_count_slides(raw_bytes, suffix),
    )
    with _registry_lock:
        existing = _jobs.get(render_id)
        if existing is not None and not existing.done_event.is_set():
            return job_payload(config, existing, cached=False)
        _jobs[render_id] = job

    thread = threading.Thread(
        target=_run_job,
        args=(config, job, raw_bytes),
        name=f"ppt-render-{render_id}",
        daemon=True,
    )
    thread.start()
    return job_payload(config, job, cached=False)


def get_render_job(config: AppConfig, user_id: str, render_id: str, is_admin: bool = False) -> Dict[str, Any]:
    with _registry_lock:
        job = _jobs.get(render_id)
    if job is not None:
        if not _user_may_access(job.user_id, user_id, is_admin):
            raise PptRenderError("PPT_RENDER_FORBIDDEN", "This render belongs to another user.", status_code=403)
        return job_payload(config, job, cached=False)

    cached = _load_cached_payload(config, render_id, user_id, is_admin=is_admin)
    if cached is not None:
        return cached
    raise PptRenderError(
        "PPT_RENDER_NOT_FOUND",
        "Unknown render id (the render may have expired or the service was restarted).",
        status_code=404,
    )


def job_payload(config: AppConfig, job: PptRenderJob, cached: bool = False) -> Dict[str, Any]:
    with job.lock:
        status = job.status
        file_name = job.file_name
        renderer = job.renderer
        slide_width = int(job.slide_width_px * EMU_PER_PX) if job.slide_width_px else 0
        slide_height = int(job.slide_height_px * EMU_PER_PX) if job.slide_height_px else 0
        expected = job.expected_slides
        error = dict(job.error) if job.error else None
        attempts = [dict(attempt) for attempt in job.attempts]
        slides = [
            {
                "index": slide["index"],
                "image_url": config.public_url_for_path(job.cache_dir / str(slide["file"])),
                "width": int(slide["width_px"] * EMU_PER_PX),
                "height": int(slide["height_px"] * EMU_PER_PX),
            }
            for slide in job.slides
        ]
    return {
        "render_id": job.render_id,
        "status": status,
        "cached": cached,
        "file_name": file_name,
        "renderer": renderer,
        "slide_width": slide_width,
        "slide_height": slide_height,
        "expected_slides": expected,
        "slides": slides,
        "error": error,
        "attempts": attempts,
    }


def _render_id_for(user_id: str, file_hash: str) -> str:
    key = f"{CACHE_VERSION}|{user_id}|{file_hash}".encode("utf-8")
    return f"pptj_{hashlib.sha256(key).hexdigest()[:24]}"


def _cache_root(config: AppConfig) -> Path:
    return config.outputs_dir / "ppt_previews" / "cache" / CACHE_VERSION


def _cache_dir_for(config: AppConfig, render_id: str) -> Path:
    return _cache_root(config) / render_id


def _user_may_access(owner_user_id: str, user_id: str, is_admin: bool = False) -> bool:
    # Empty user_id means the auth layer is disabled (local single-user run).
    if not user_id or is_admin:
        return True
    return user_id == owner_user_id


def _count_slides(raw_bytes: bytes, suffix: str) -> int:
    if suffix != ".pptx":
        return 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
            return len([name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)])
    except Exception:
        return 0


def _run_job(config: AppConfig, job: PptRenderJob, raw_bytes: bytes) -> None:
    try:
        _set_job(job, status=STATUS_RENDERING)
        job.cache_dir.mkdir(parents=True, exist_ok=True)
        source_path = job.cache_dir / f"source_{job.file_name}"
        source_path.write_bytes(raw_bytes)
        raw_bytes = b""

        result: Dict[str, Any] | None = None
        with _render_semaphore:
            if sys.platform.startswith("win"):
                result = _render_with_powerpoint(config, job, source_path)
            if result is None:
                result = _render_with_libreoffice(config, job, source_path)

        if result is None:
            raise PptRenderError(
                "PPT_RENDERER_UNAVAILABLE",
                "No available PPT renderer succeeded. Install Microsoft PowerPoint or LibreOffice for high-fidelity previews.",
                {"attempts": list(job.attempts)},
                status_code=503,
            )
        _finish_job(config, job, result)
    except PptRenderError as exc:
        _fail_job(job, exc.to_dict())
    except Exception as exc:  # defensive: a crashed worker thread must not stay "rendering"
        _fail_job(job, {"code": "PPT_RENDER_INTERNAL", "message": str(exc)[:300], "details": {}})


def _fail_job(job: PptRenderJob, error: Dict[str, Any]) -> None:
    with job.lock:
        job.status = STATUS_FAILED
        job.error = error
    job.done_event.set()


def _set_job(job: PptRenderJob, **changes: Any) -> None:
    with job.lock:
        for key, value in changes.items():
            setattr(job, key, value)


def _finish_job(config: AppConfig, job: PptRenderJob, result: Dict[str, Any]) -> None:
    with job.lock:
        job.status = STATUS_COMPLETE
        job.renderer = str(result.get("renderer") or job.renderer)
        job.slide_width_px = int(result.get("width_px") or job.slide_width_px or DEFAULT_EXPORT_WIDTH)
        job.slide_height_px = int(result.get("height_px") or job.slide_height_px or round(DEFAULT_EXPORT_WIDTH * 9 / 16))
        manifest = {
            "status": STATUS_COMPLETE,
            "render_id": job.render_id,
            "user_id": job.user_id,
            "file_name": job.file_name,
            "renderer": job.renderer,
            "slide_width_px": job.slide_width_px,
            "slide_height_px": job.slide_height_px,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "slides": [dict(slide) for slide in job.slides],
        }
    (job.cache_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    job.done_event.set()


def _load_cached_payload(config: AppConfig, render_id: str, user_id: str, is_admin: bool = False) -> Dict[str, Any] | None:
    cache_dir = _cache_dir_for(config, render_id)
    manifest_path = cache_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(manifest, dict) or manifest.get("status") != STATUS_COMPLETE:
        return None
    if manifest.get("render_id") != render_id:
        return None
    if not _user_may_access(str(manifest.get("user_id") or ""), user_id, is_admin):
        return None

    slides: List[Dict[str, Any]] = []
    for slide in manifest.get("slides") or []:
        file_name = str(slide.get("file") or "")
        if not file_name or not (cache_dir / file_name).is_file():
            return None
        slides.append(
            {
                "index": int(slide.get("index") or len(slides)),
                "file": file_name,
                "width_px": int(slide.get("width_px") or DEFAULT_EXPORT_WIDTH),
                "height_px": int(slide.get("height_px") or 0),
            }
        )
    if not slides:
        return None

    width_px = int(manifest.get("slide_width_px") or slides[0]["width_px"])
    height_px = int(manifest.get("slide_height_px") or slides[0]["height_px"])
    return {
        "render_id": render_id,
        "status": STATUS_COMPLETE,
        "cached": True,
        "file_name": str(manifest.get("file_name") or ""),
        "renderer": str(manifest.get("renderer") or "cache"),
        "slide_width": int(width_px * EMU_PER_PX),
        "slide_height": int(height_px * EMU_PER_PX),
        "expected_slides": len(slides),
        "slides": [
            {
                "index": slide["index"],
                "image_url": config.public_url_for_path(cache_dir / slide["file"]),
                "width": int(slide["width_px"] * EMU_PER_PX),
                "height": int(slide["height_px"] * EMU_PER_PX),
            }
            for slide in slides
        ],
        "error": None,
        "attempts": [],
    }


def _render_with_powerpoint(config: AppConfig, job: PptRenderJob, source_path: Path) -> Dict[str, Any] | None:
    attempts = job.attempts
    worker_python = ppt_renderer._find_powerpoint_worker_python(attempts)
    if not worker_python:
        return None

    export_dir = job.cache_dir / "powerpoint_png"
    export_dir.mkdir(parents=True, exist_ok=True)
    progress_path = job.cache_dir / "powerpoint_progress.json"
    result_path = job.cache_dir / "powerpoint_result.json"

    command = [
        worker_python,
        "-m",
        "backend.app.services.ppt_renderer_worker",
        str(source_path),
        str(export_dir),
        str(result_path),
        str(progress_path),
    ]
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(Path(__file__).resolve().parents[3]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as exc:
        attempts.append({"renderer": "powerpoint-incremental", "status": "failed", "detail": str(exc)})
        return None

    last_done = 0
    last_progress_at = time.monotonic()
    started_at = time.monotonic()
    timeout_reason = ""
    while proc.poll() is None:
        time.sleep(POLL_INTERVAL_SECONDS)
        progress = _read_json(progress_path)
        done = _progress_done(progress)
        if done > last_done:
            last_done = done
            last_progress_at = time.monotonic()
            _apply_powerpoint_progress(job, progress)
        now = time.monotonic()
        if now - last_progress_at > NO_PROGRESS_TIMEOUT_SECONDS:
            timeout_reason = f"no progress for {NO_PROGRESS_TIMEOUT_SECONDS}s"
            break
        if now - started_at > TOTAL_TIMEOUT_SECONDS:
            timeout_reason = f"total render exceeded {TOTAL_TIMEOUT_SECONDS}s"
            break

    if timeout_reason:
        ppt_renderer._terminate_process_tree(proc)
        attempts.append({"renderer": "powerpoint-incremental", "status": "timeout", "detail": timeout_reason})
        return None

    try:
        stdout, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        ppt_renderer._terminate_process_tree(proc)
        stdout, stderr = "", ""

    progress = _read_json(progress_path)
    done = _progress_done(progress)
    if done > last_done:
        _apply_powerpoint_progress(job, progress)
        last_done = done

    if last_done > 0:
        with job.lock:
            width_px = job.slide_width_px
            height_px = job.slide_height_px
        return {
            "renderer": "powerpoint-incremental",
            "width_px": width_px,
            "height_px": height_px,
        }

    detail = "\n".join(part.strip() for part in (stdout, stderr) if part and part.strip())
    attempts.append(
        {"renderer": "powerpoint-incremental", "status": "failed", "detail": detail[:1200] or f"exit code {proc.returncode}"}
    )
    return None


def _read_json(path: Path) -> Dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _progress_done(progress: Dict[str, Any] | None) -> int:
    if not isinstance(progress, dict):
        return 0
    try:
        return int(progress.get("done") or 0)
    except (TypeError, ValueError):
        return 0


def _apply_powerpoint_progress(job: PptRenderJob, progress: Dict[str, Any] | None) -> None:
    if not isinstance(progress, dict):
        return
    width_px = int(progress.get("slide_width_px") or 0)
    height_px = int(progress.get("slide_height_px") or 0)
    slides: List[Dict[str, Any]] = []
    for index, raw_path in enumerate(progress.get("image_paths") or []):
        path = Path(str(raw_path))
        try:
            relative = path.resolve().relative_to(job.cache_dir.resolve()).as_posix()
        except (ValueError, OSError):
            relative = path.name
        slides.append(
            {
                "index": index,
                "file": relative,
                "width_px": width_px or DEFAULT_EXPORT_WIDTH,
                "height_px": height_px or round(DEFAULT_EXPORT_WIDTH * 9 / 16),
            }
        )
    with job.lock:
        if int(progress.get("total") or 0):
            job.expected_slides = int(progress["total"])
        if width_px:
            job.slide_width_px = width_px
            job.slide_height_px = height_px
        job.renderer = "powerpoint-incremental"
        job.slides = slides
        if len(slides):
            job.status = STATUS_RENDERING


def _render_with_libreoffice(config: AppConfig, job: PptRenderJob, source_path: Path) -> Dict[str, Any] | None:
    attempts = job.attempts
    soffice = ppt_renderer._find_soffice()
    if not soffice:
        attempts.append({"renderer": "libreoffice", "status": "unavailable", "detail": "soffice executable not found"})
        return None

    pdf_dir = job.cache_dir / "libreoffice_pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_result = ppt_renderer._run_command(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(source_path)],
        timeout=180,
    )
    pdf_path = ppt_renderer._first_file(pdf_dir, ".pdf") if pdf_result.returncode == 0 else None
    if pdf_path is not None:
        raster = _rasterize_pdf_incrementally(job, pdf_path)
        if raster is not None:
            attempts.append(
                {"renderer": raster["renderer"], "status": "success", "detail": f"{len(job.slides)} slide images"}
            )
            return raster
    attempts.append({"renderer": "libreoffice-pdf", "status": "failed", "detail": ppt_renderer._command_detail(pdf_result)})

    png_dir = job.cache_dir / "libreoffice_png"
    png_dir.mkdir(parents=True, exist_ok=True)
    png_result = ppt_renderer._run_command(
        [soffice, "--headless", "--convert-to", "png", "--outdir", str(png_dir), str(source_path)],
        timeout=180,
    )
    images = ppt_renderer._collect_pngs(png_dir)
    if png_result.returncode == 0 and images and (job.expected_slides <= 1 or len(images) >= job.expected_slides):
        width_px = DEFAULT_EXPORT_WIDTH
        height_px = round(DEFAULT_EXPORT_WIDTH * 9 / 16)
        with job.lock:
            job.renderer = "libreoffice-png"
            job.slide_width_px = width_px
            job.slide_height_px = height_px
            job.slides = [
                {
                    "index": index,
                    "file": path.relative_to(job.cache_dir).as_posix(),
                    "width_px": width_px,
                    "height_px": height_px,
                }
                for index, path in enumerate(images)
            ]
        return {"renderer": "libreoffice-png", "width_px": width_px, "height_px": height_px}
    attempts.append({"renderer": "libreoffice-png", "status": "failed", "detail": ppt_renderer._command_detail(png_result)})
    return None


def _rasterize_pdf_incrementally(job: PptRenderJob, pdf_path: Path) -> Dict[str, Any] | None:
    """Rasterize the converted PDF page by page so pages stream out early."""
    try:
        import fitz  # type: ignore
    except Exception:
        return _rasterize_pdf_with_pdftoppm(job, pdf_path)

    image_dir = job.cache_dir / "pymupdf_png"
    image_dir.mkdir(parents=True, exist_ok=True)
    width_px = 0
    height_px = 0
    try:
        document = fitz.open(str(pdf_path))
    except Exception:
        return _rasterize_pdf_with_pdftoppm(job, pdf_path)
    try:
        for index, page in enumerate(document):
            scale = DEFAULT_EXPORT_WIDTH / max(1, page.rect.width)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image_path = image_dir / f"slide_{index + 1:03d}.png"
            pixmap.save(str(image_path))
            if index == 0:
                width_px = int(pixmap.width)
                height_px = int(pixmap.height)
            _update_job_slides(job, "libreoffice-pdf-pymupdf", image_dir, width_px, height_px, index + 1)
    finally:
        document.close()
    if not width_px:
        return None
    return {
        "renderer": "libreoffice-pdf-pymupdf",
        "width_px": width_px,
        "height_px": height_px,
    }


def _rasterize_pdf_with_pdftoppm(job: PptRenderJob, pdf_path: Path) -> Dict[str, Any] | None:
    job.attempts.append({"renderer": "pymupdf", "status": "unavailable", "detail": "PyMuPDF is not installed"})
    exe = shutil.which("pdftoppm")
    if not exe:
        job.attempts.append({"renderer": "pdftoppm", "status": "unavailable", "detail": "pdftoppm executable not found"})
        return None
    image_dir = job.cache_dir / "pdftoppm_png"
    image_dir.mkdir(parents=True, exist_ok=True)
    prefix = image_dir / "slide"
    result = ppt_renderer._run_command([exe, "-png", "-r", "160", str(pdf_path), str(prefix)], timeout=180)
    images = ppt_renderer._collect_pngs(image_dir)
    if result.returncode != 0 or not images or (job.expected_slides > 1 and len(images) < job.expected_slides):
        job.attempts.append({"renderer": "pdftoppm", "status": "failed", "detail": ppt_renderer._command_detail(result)})
        return None
    width_px = DEFAULT_EXPORT_WIDTH
    height_px = round(DEFAULT_EXPORT_WIDTH * 9 / 16)
    with job.lock:
        job.renderer = "libreoffice-pdf-pdftoppm"
        job.slide_width_px = width_px
        job.slide_height_px = height_px
        job.slides = [
            {
                "index": index,
                "file": path.relative_to(job.cache_dir).as_posix(),
                "width_px": width_px,
                "height_px": height_px,
            }
            for index, path in enumerate(images)
        ]
    return {"renderer": "libreoffice-pdf-pdftoppm", "width_px": width_px, "height_px": height_px}


def _update_job_slides(
    job: PptRenderJob,
    renderer: str,
    image_dir: Path,
    width_px: int,
    height_px: int,
    count: int,
) -> None:
    images = ppt_renderer._collect_pngs(image_dir)[:count]
    if not images:
        return
    with job.lock:
        job.renderer = renderer
        if width_px:
            job.slide_width_px = width_px
            job.slide_height_px = height_px
        job.slides = [
            {
                "index": index,
                "file": path.relative_to(job.cache_dir).as_posix(),
                "width_px": width_px or DEFAULT_EXPORT_WIDTH,
                "height_px": height_px or round(DEFAULT_EXPORT_WIDTH * 9 / 16),
            }
            for index, path in enumerate(images)
        ]
        job.status = STATUS_RENDERING


def _maybe_cleanup_cache(config: AppConfig) -> None:
    global _last_cleanup
    now = time.monotonic()
    with _cleanup_lock:
        if now - _last_cleanup < CLEANUP_MIN_INTERVAL_SECONDS:
            return
        _last_cleanup = now
    cache_root = _cache_root(config)
    if not cache_root.is_dir():
        return

    with _registry_lock:
        active_dirs = {str(job.cache_dir.resolve()) for job in _jobs.values() if not job.done_event.is_set()}

    entries: List[tuple[Path, float, int]] = []
    total_bytes = 0
    for child in cache_root.iterdir():
        if not child.is_dir():
            continue
        try:
            size = _directory_size(child)
            age_reference = child.stat().st_mtime
            manifest_path = child / "manifest.json"
            if manifest_path.is_file():
                age_reference = manifest_path.stat().st_mtime
            entries.append((child, age_reference, size))
            total_bytes += size
        except OSError:
            continue

    now_ts = time.time()
    for child, age_reference, size in list(entries):
        if str(child.resolve()) in active_dirs:
            continue
        if now_ts - age_reference > CACHE_MAX_AGE_SECONDS:
            shutil.rmtree(child, ignore_errors=True)
            total_bytes -= size

    if total_bytes > CACHE_MAX_TOTAL_BYTES:
        for child, age_reference, size in sorted(entries, key=lambda entry: entry[1]):
            if total_bytes <= CACHE_MAX_TOTAL_BYTES:
                break
            if str(child.resolve()) in active_dirs:
                continue
            if not child.exists():
                continue
            shutil.rmtree(child, ignore_errors=True)
            total_bytes -= size


def _directory_size(directory: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(directory):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total
