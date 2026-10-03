from __future__ import annotations

import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from backend.app.services import ppt_renderer
from backend.app.config import AppConfig


class PptRendererTest(unittest.TestCase):
    def test_refuses_partial_deck_exports(self) -> None:
        import io
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as package:
            for i in range(1, 4):
                package.writestr(f"ppt/slides/slide{i}.xml", "<slide/>")
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict("os.environ", {"WEBGIS_AI_DATA_DIR": directory}), mock.patch.object(
            ppt_renderer, "_attempt_powerpoint", return_value={"image_paths": [Path(directory) / "one.png"], "width_px": 1920, "height_px": 1080, "renderer": "powerpoint-pywin32"}
        ), mock.patch.object(ppt_renderer.sys, "platform", "win32"):
            with self.assertRaises(ppt_renderer.PptRenderError) as raised:
                ppt_renderer.render_pptx_to_images(AppConfig(root_dir=Path(directory)), "class.pptx", buffer.getvalue())
            self.assertEqual(raised.exception.code, "PPT_RENDER_INCOMPLETE")

    def test_repairs_generated_dcterms_qname_without_changing_uploaded_slides(self) -> None:
        core = b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:ns2="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><ns2:created xsi:type="dcterms:W3CDTF">2026-10-03T00:00:00Z</ns2:created></cp:coreProperties>'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "render_compatible.pptx"
            with zipfile.ZipFile(source, "w") as package:
                package.writestr("docProps/core.xml", core)
                package.writestr("ppt/slides/slide1.xml", b'<p:sld name="unchanged"/>')
            original = source.read_bytes()
            attempts: list[dict[str, str]] = []
            prepared = ppt_renderer._prepare_render_source(source, attempts)
            self.assertNotEqual(prepared, source)
            self.assertEqual(source.read_bytes(), original)
            with zipfile.ZipFile(prepared) as package:
                self.assertIn(b'xmlns:dcterms="http://purl.org/dc/terms/"', package.read("docProps/core.xml"))
                self.assertIn(b'<dcterms:created', package.read("docProps/core.xml"))
                self.assertEqual(package.read("ppt/slides/slide1.xml"), b'<p:sld name="unchanged"/>')
            self.assertEqual(attempts[0]["status"], "repaired")

    def test_leaves_valid_and_unknown_packages_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pptx"
            for core in [b'<core xmlns:dcterms="http://purl.org/dc/terms/"/>', b'<core/>']:
                with zipfile.ZipFile(source, "w") as package:
                    package.writestr("docProps/core.xml", core)
                attempts: list[dict[str, str]] = []
                self.assertEqual(ppt_renderer._prepare_render_source(source, attempts), source)
                self.assertEqual(attempts, [])

    def test_powerpoint_worker_python_falls_back_to_com_capable_interpreter(self) -> None:
        attempts: list[dict[str, str]] = []

        def fake_run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                0 if command[0] == "D:/Anaconda3/python.exe" else 1,
                "",
                "missing COM modules",
            )

        with mock.patch.object(
            ppt_renderer,
            "_powerpoint_python_candidates",
            return_value=["C:/Python312/python.exe", "D:/Anaconda3/python.exe"],
        ), mock.patch.object(
            ppt_renderer,
            "_resolve_python_candidate",
            side_effect=lambda candidate: candidate,
        ), mock.patch.object(
            ppt_renderer,
            "_run_command",
            side_effect=fake_run,
        ), mock.patch.object(
            ppt_renderer.sys,
            "executable",
            "C:/Python312/python.exe",
        ):
            selected = ppt_renderer._find_powerpoint_worker_python(attempts)

        self.assertEqual(selected, "D:/Anaconda3/python.exe")
        self.assertEqual(
            attempts,
            [
                {
                    "renderer": "powerpoint-worker-python",
                    "status": "selected",
                    "detail": "D:/Anaconda3/python.exe",
                }
            ],
        )
