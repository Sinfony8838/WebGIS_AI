from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Sequence
from uuid import uuid4

from ..config import AppConfig

EMU_PER_PX = 914400 / 96
DEFAULT_EXPORT_WIDTH = 1920


class PptRenderError(Exception):
    def __init__(self, code: str, message: str, details: Dict[str, Any] | None = None, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


def render_pptx_to_images(config: AppConfig, filename: str, raw_bytes: bytes) -> Dict[str, Any]:
    if not raw_bytes:
        raise PptRenderError("EMPTY_PPTX", "Uploaded PPT file is empty.", status_code=400)

    safe_name = _safe_filename(filename or "presentation.pptx")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".pptx", ".ppt"}:
        raise PptRenderError("UNSUPPORTED_PPT_FORMAT", "Only .pptx and .ppt files can be rendered.", status_code=400)

    config.ensure_dirs()
    render_id = f"ppt_{uuid4().hex}"
    output_dir = config.outputs_dir / "ppt_previews" / render_id
    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = output_dir / safe_name
    source_path.write_bytes(raw_bytes)

    expected_count = _count_ppt_slides(source_path)
    attempts: List[Dict[str, str]] = []
    result: Dict[str, Any] | None = None

    if sys.platform.startswith("win"):
        result = _attempt_powerpoint(source_path, output_dir, attempts)

    if result is None:
        result = _attempt_libreoffice(source_path, output_dir, expected_count, attempts)

    if result is None:
        raise PptRenderError(
            "PPT_RENDERER_UNAVAILABLE",
            "No available PPT renderer succeeded. Install Microsoft PowerPoint or LibreOffice for high-fidelity previews.",
            {"attempts": attempts},
            status_code=503,
        )

    slides = []
    for index, path in enumerate(result["image_paths"]):
        slides.append(
            {
                "index": index,
                "image_url": config.public_url_for_path(path),
                "width": int(result["width_px"] * EMU_PER_PX),
                "height": int(result["height_px"] * EMU_PER_PX),
            }
        )

    return {
        "status": "success",
        "file_name": safe_name,
        "renderer": result["renderer"],
        "slide_width": int(result["width_px"] * EMU_PER_PX),
        "slide_height": int(result["height_px"] * EMU_PER_PX),
        "slides": slides,
        "attempts": attempts,
    }


def _attempt_powerpoint(source_path: Path, output_dir: Path, attempts: List[Dict[str, str]]) -> Dict[str, Any] | None:
    export_dir = output_dir / "powerpoint_worker_png"
    export_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "powerpoint_worker_result.json"
    command = [
        sys.executable,
        "-m",
        "backend.app.services.ppt_renderer_worker",
        str(source_path),
        str(export_dir),
        str(result_path),
    ]
    proc = subprocess.Popen(
        command,
        cwd=str(Path(__file__).resolve().parents[3]),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=100)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        attempts.append({"renderer": "powerpoint-worker", "status": "timeout", "detail": "PowerPoint render worker exceeded 100 seconds"})
        return None

    if result_path.exists():
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception as exc:
            attempts.append({"renderer": "powerpoint-worker", "status": "failed", "detail": f"invalid worker result: {exc}"})
            payload = {}
        for attempt in payload.get("attempts") or []:
            if isinstance(attempt, dict):
                attempts.append({str(k): str(v) for k, v in attempt.items()})
        result = payload.get("result")
        if isinstance(result, dict) and result.get("image_paths"):
            return {
                "renderer": str(result.get("renderer") or "powerpoint-worker"),
                "image_paths": [Path(item) for item in result.get("image_paths") or []],
                "width_px": int(result.get("width_px") or DEFAULT_EXPORT_WIDTH),
                "height_px": int(result.get("height_px") or round(DEFAULT_EXPORT_WIDTH * 9 / 16)),
            }

    detail = "\n".join(part.strip() for part in (stdout, stderr) if part and part.strip())
    attempts.append({"renderer": "powerpoint-worker", "status": "failed", "detail": detail[:1200] or f"exit code {proc.returncode}"})
    return None


def _attempt_powerpoint_pywin32(source_path: Path, output_dir: Path, attempts: List[Dict[str, str]]) -> Dict[str, Any] | None:
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on host Python
        attempts.append({"renderer": "powerpoint-pywin32", "status": "unavailable", "detail": str(exc)})
        return None

    export_dir = output_dir / "powerpoint_pywin32_png"
    export_dir.mkdir(parents=True, exist_ok=True)
    app = None
    presentation = None
    pythoncom.CoInitialize()
    try:
        app = win32com.client.DispatchEx("PowerPoint.Application")
        app.Visible = 1
        presentation = app.Presentations.Open(str(source_path), True, False, False)
        slide_width_pt = float(presentation.PageSetup.SlideWidth)
        slide_height_pt = float(presentation.PageSetup.SlideHeight)
        aspect = slide_width_pt / slide_height_pt if slide_height_pt else 16 / 9
        export_width = DEFAULT_EXPORT_WIDTH
        export_height = max(1, round(export_width / aspect))

        presentation.Export(str(export_dir), "PNG", export_width, export_height)
        images = _collect_pngs(export_dir)
        if not images:
            attempts.append({"renderer": "powerpoint-pywin32", "status": "failed", "detail": "PowerPoint exported no PNG files."})
            return None

        attempts.append({"renderer": "powerpoint-pywin32", "status": "success", "detail": f"{len(images)} slide images"})
        return {
            "renderer": "powerpoint-pywin32",
            "image_paths": images,
            "width_px": export_width,
            "height_px": export_height,
        }
    except Exception as exc:  # pragma: no cover - requires local Office
        attempts.append({"renderer": "powerpoint-pywin32", "status": "failed", "detail": str(exc)})
        return None
    finally:
        try:
            if presentation is not None:
                presentation.Close()
        except Exception:
            pass
        try:
            if app is not None:
                app.Quit()
        except Exception:
            pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _attempt_powerpoint_comtypes(source_path: Path, output_dir: Path, attempts: List[Dict[str, str]]) -> Dict[str, Any] | None:
    try:
        import comtypes  # type: ignore
        import comtypes.client  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on host Python
        attempts.append({"renderer": "powerpoint-comtypes", "status": "unavailable", "detail": str(exc)})
        return None

    export_dir = output_dir / "powerpoint_comtypes_png"
    export_dir.mkdir(parents=True, exist_ok=True)
    app = None
    presentation = None
    comtypes.CoInitialize()
    try:
        app = comtypes.client.CreateObject("PowerPoint.Application")
        app.Visible = 1
        presentation = app.Presentations.Open(str(source_path), True, False, False)
        slide_width_pt = float(presentation.PageSetup.SlideWidth)
        slide_height_pt = float(presentation.PageSetup.SlideHeight)
        aspect = slide_width_pt / slide_height_pt if slide_height_pt else 16 / 9
        export_width = DEFAULT_EXPORT_WIDTH
        export_height = max(1, round(export_width / aspect))

        presentation.Export(str(export_dir), "PNG", export_width, export_height)
        images = _collect_pngs(export_dir)
        if not images:
            attempts.append({"renderer": "powerpoint-comtypes", "status": "failed", "detail": "PowerPoint exported no PNG files."})
            return None

        attempts.append({"renderer": "powerpoint-comtypes", "status": "success", "detail": f"{len(images)} slide images"})
        return {
            "renderer": "powerpoint-comtypes",
            "image_paths": images,
            "width_px": export_width,
            "height_px": export_height,
        }
    except Exception as exc:  # pragma: no cover - requires local Office
        attempts.append({"renderer": "powerpoint-comtypes", "status": "failed", "detail": str(exc)})
        return None
    finally:
        try:
            if presentation is not None:
                presentation.Close()
        except Exception:
            pass
        try:
            if app is not None:
                app.Quit()
        except Exception:
            pass
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass


def _attempt_libreoffice(
    source_path: Path,
    output_dir: Path,
    expected_count: int,
    attempts: List[Dict[str, str]],
) -> Dict[str, Any] | None:
    soffice = _find_soffice()
    if not soffice:
        attempts.append({"renderer": "libreoffice", "status": "unavailable", "detail": "soffice executable not found"})
        return None

    pdf_dir = output_dir / "libreoffice_pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_result = _run_command(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(source_path)],
        timeout=90,
    )
    if pdf_result.returncode == 0:
        pdf_path = _first_file(pdf_dir, ".pdf")
        if pdf_path:
            raster = _rasterize_pdf(pdf_path, output_dir, expected_count, attempts)
            if raster is not None:
                attempts.append({"renderer": "libreoffice-pdf", "status": "success", "detail": f"{len(raster['image_paths'])} slide images"})
                return raster
    attempts.append({"renderer": "libreoffice-pdf", "status": "failed", "detail": _command_detail(pdf_result)})

    png_dir = output_dir / "libreoffice_png"
    png_dir.mkdir(parents=True, exist_ok=True)
    png_result = _run_command(
        [soffice, "--headless", "--convert-to", "png", "--outdir", str(png_dir), str(source_path)],
        timeout=90,
    )
    images = _collect_pngs(png_dir)
    if png_result.returncode == 0 and images and (expected_count <= 1 or len(images) >= expected_count):
        attempts.append({"renderer": "libreoffice-png", "status": "success", "detail": f"{len(images)} slide images"})
        return {
            "renderer": "libreoffice-png",
            "image_paths": images,
            "width_px": DEFAULT_EXPORT_WIDTH,
            "height_px": round(DEFAULT_EXPORT_WIDTH * 9 / 16),
        }
    attempts.append({"renderer": "libreoffice-png", "status": "failed", "detail": _command_detail(png_result)})
    return None


def _rasterize_pdf(
    pdf_path: Path,
    output_dir: Path,
    expected_count: int,
    attempts: List[Dict[str, str]],
) -> Dict[str, Any] | None:
    pymupdf_result = _rasterize_with_pymupdf(pdf_path, output_dir)
    if pymupdf_result is not None:
        return pymupdf_result
    attempts.append({"renderer": "pymupdf", "status": "unavailable", "detail": "PyMuPDF is not installed"})

    pdftoppm_result = _rasterize_with_pdftoppm(pdf_path, output_dir, expected_count)
    if pdftoppm_result is not None:
        return pdftoppm_result
    attempts.append({"renderer": "pdftoppm", "status": "unavailable", "detail": "pdftoppm executable not found or failed"})
    return None


def _rasterize_with_pymupdf(pdf_path: Path, output_dir: Path) -> Dict[str, Any] | None:
    try:
        import fitz  # type: ignore
    except Exception:
        return None

    image_dir = output_dir / "pymupdf_png"
    image_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    width_px = DEFAULT_EXPORT_WIDTH
    height_px = round(DEFAULT_EXPORT_WIDTH * 9 / 16)
    try:
        document = fitz.open(str(pdf_path))
    except Exception:
        return None
    try:
        for index, page in enumerate(document):
            scale = DEFAULT_EXPORT_WIDTH / max(1, page.rect.width)
            matrix = fitz.Matrix(scale, scale)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            path = image_dir / f"slide_{index + 1:03d}.png"
            pixmap.save(str(path))
            paths.append(path)
            if index == 0:
                width_px = int(pixmap.width)
                height_px = int(pixmap.height)
    finally:
        document.close()
    if not paths:
        return None
    return {
        "renderer": "libreoffice-pdf-pymupdf",
        "image_paths": paths,
        "width_px": width_px,
        "height_px": height_px,
    }


def _rasterize_with_pdftoppm(pdf_path: Path, output_dir: Path, expected_count: int) -> Dict[str, Any] | None:
    exe = shutil.which("pdftoppm")
    if not exe:
        return None
    image_dir = output_dir / "pdftoppm_png"
    image_dir.mkdir(parents=True, exist_ok=True)
    prefix = image_dir / "slide"
    result = _run_command([exe, "-png", "-r", "160", str(pdf_path), str(prefix)], timeout=90)
    images = _collect_pngs(image_dir)
    if result.returncode != 0 or not images or (expected_count > 1 and len(images) < expected_count):
        return None
    return {
        "renderer": "libreoffice-pdf-pdftoppm",
        "image_paths": images,
        "width_px": DEFAULT_EXPORT_WIDTH,
        "height_px": round(DEFAULT_EXPORT_WIDTH * 9 / 16),
    }


def _run_command(command: Sequence[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return subprocess.CompletedProcess(list(command), 1, "", str(exc))


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            check=False,
            capture_output=True,
            text=True,
        )
        return
    proc.kill()


def _find_soffice() -> str:
    for env_name in ("WEBGIS_AI_LIBREOFFICE_PATH", "LIBREOFFICE_PATH", "SOFFICE_PATH"):
        value = os.getenv(env_name, "").strip()
        if value and Path(value).exists():
            return value
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        Path("C:/Program Files/LibreOffice/program/soffice.exe"),
        Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def _collect_pngs(directory: Path) -> List[Path]:
    paths = list(directory.glob("*.png")) + list(directory.glob("*.PNG"))
    unique_paths = {path.resolve(): path for path in paths}
    return sorted(unique_paths.values(), key=lambda path: _natural_key(path.name))


def _first_file(directory: Path, suffix: str) -> Path | None:
    for path in directory.iterdir():
        if path.suffix.lower() == suffix:
            return path
    return None


def _count_ppt_slides(path: Path) -> int:
    if path.suffix.lower() != ".pptx":
        return 0
    try:
        with zipfile.ZipFile(path) as archive:
            return len([name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)])
    except Exception:
        return 0


def _natural_key(value: str) -> List[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip() or "presentation.pptx"
    return re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", name)


def _command_detail(result: subprocess.CompletedProcess[str]) -> str:
    detail = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
    return detail[:1200] if detail else f"exit code {result.returncode}"
