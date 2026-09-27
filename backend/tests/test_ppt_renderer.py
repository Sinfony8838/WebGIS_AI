from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from backend.app.services import ppt_renderer, ppt_renderer_worker


class PptRendererTest(unittest.TestCase):
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


class FakeSlides:
    def __init__(self, presentation: "FakeComPresentation") -> None:
        self.Count = presentation.slide_count
        self._presentation = presentation

    def __call__(self, index: int):
        return self._presentation._slide(index)


class FakeComPresentation:
    """Minimal PowerPoint COM stand-in: PageSetup + per-slide Export."""

    def __init__(self, slide_count: int, export_writes_file: bool = True) -> None:
        self.slide_count = slide_count
        self.export_writes_file = export_writes_file
        self.exported: list[str] = []
        self.closed = False
        self.quit_called = False
        self.PageSetup = types.SimpleNamespace(SlideWidth=960.0, SlideHeight=540.0)
        self.Slides = FakeSlides(self)

    def _slide(self, index: int):
        presentation = self

        class FakeSlide:
            def Export(self, path: str, fmt: str, width: int, height: int) -> None:
                presentation.exported.append(path)
                if presentation.export_writes_file:
                    Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfake")

        return FakeSlide()

    def Open(self, path, read_only, untitled, with_window):  # noqa: ANN001
        return self

    def Close(self) -> None:
        self.closed = True

    def Quit(self) -> None:
        self.quit_called = True


class FakePresentations:
    def __init__(self, presentation: FakeComPresentation) -> None:
        self._presentation = presentation

    def Open(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self._presentation


@contextlib.contextmanager
def fake_pywin32(presentation: FakeComPresentation):
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: None
    pythoncom.CoUninitialize = lambda: None
    win32com = types.ModuleType("win32com")
    win32com_client = types.ModuleType("win32com.client")
    app = types.SimpleNamespace(
        Visible=None,
        Presentations=FakePresentations(presentation),
        Quit=presentation.Quit,
    )
    win32com_client.DispatchEx = lambda name: app
    win32com.client = win32com_client
    modules = {
        "pythoncom": pythoncom,
        "win32com": win32com,
        "win32com.client": win32com_client,
    }
    saved = {name: sys.modules.get(name) for name in modules}
    for name, module in modules.items():
        sys.modules[name] = module
    try:
        yield app
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class IncrementalExportTest(unittest.TestCase):
    def test_incremental_export_writes_progress_after_each_slide(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "deck.pptx"
            source.write_bytes(b"PK\x03\x04fake")
            export_dir = root / "png"
            progress_path = root / "progress.json"
            presentation = FakeComPresentation(slide_count=3)
            attempts: list[dict[str, str]] = []

            with fake_pywin32(presentation):
                result = ppt_renderer._export_slides_incrementally(source, export_dir, progress_path, attempts)

            self.assertIsNotNone(result)
            self.assertEqual(result["renderer"], "powerpoint-incremental")
            self.assertEqual(len(result["image_paths"]), 3)
            self.assertEqual(presentation.exported, [str(export_dir / f"slide_{i:03d}.png") for i in (1, 2, 3)])
            self.assertTrue(presentation.closed)
            self.assertTrue(presentation.quit_called)
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            self.assertEqual(progress["done"], 3)
            self.assertEqual(progress["total"], 3)
            self.assertEqual(progress["slide_width_px"], 1920)
            self.assertEqual(progress["slide_height_px"], 1080)
            self.assertEqual(len(progress["image_paths"]), 3)
            self.assertTrue(attempts[0]["detail"].startswith("3 slide images") or attempts[0]["status"] == "success")

    def test_incremental_export_fails_when_slide_not_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "deck.pptx"
            source.write_bytes(b"PK\x03\x04fake")
            progress_path = root / "progress.json"
            attempts: list[dict[str, str]] = []

            failing = FakeComPresentation(slide_count=2, export_writes_file=False)
            with fake_pywin32(failing):
                result = ppt_renderer._incremental_export_with_com(
                    "pywin32", source, root / "png", progress_path, attempts
                )

            self.assertIsNone(result)
            self.assertEqual(attempts[-1]["status"], "failed")
            self.assertFalse(progress_path.exists())


class WorkerMainTest(unittest.TestCase):
    def test_worker_prefers_incremental_export_and_writes_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result_path = root / "result.json"
            incremental_result = {
                "renderer": "powerpoint-incremental",
                "image_paths": [str(root / "slide_001.png")],
                "width_px": 1920,
                "height_px": 1080,
            }
            with mock.patch.object(
                ppt_renderer_worker,
                "_export_slides_incrementally",
                return_value=incremental_result,
            ) as incremental, mock.patch.object(
                ppt_renderer_worker,
                "_attempt_powerpoint_pywin32",
            ) as whole_deck:
                exit_code = ppt_renderer_worker.main(
                    [
                        "worker",
                        str(root / "deck.pptx"),
                        str(root / "png"),
                        str(result_path),
                        str(root / "progress.json"),
                    ]
                )

            self.assertEqual(exit_code, 0)
            incremental.assert_called_once()
            whole_deck.assert_not_called()
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["result"]["renderer"], "powerpoint-incremental")

    def test_worker_falls_back_to_whole_deck_when_incremental_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result_path = root / "result.json"
            whole_deck_result = {
                "renderer": "powerpoint-pywin32",
                "image_paths": [str(root / "slide_001.png"), str(root / "slide_002.png")],
                "width_px": 1920,
                "height_px": 1080,
            }
            with mock.patch.object(
                ppt_renderer_worker,
                "_export_slides_incrementally",
                return_value=None,
            ), mock.patch.object(
                ppt_renderer_worker,
                "_attempt_powerpoint_pywin32",
                return_value=whole_deck_result,
            ) as whole_deck, mock.patch.object(
                ppt_renderer_worker,
                "_attempt_powerpoint_comtypes",
                return_value=None,
            ):
                exit_code = ppt_renderer_worker.main(
                    [
                        "worker",
                        str(root / "deck.pptx"),
                        str(root / "png"),
                        str(result_path),
                        str(root / "progress.json"),
                    ]
                )

            self.assertEqual(exit_code, 0)
            whole_deck.assert_called_once()
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["result"]["renderer"], "powerpoint-pywin32")
            fallbacks = [a for a in payload["attempts"] if a["status"] == "fallback"]
            self.assertTrue(fallbacks)

    def test_worker_without_progress_path_keeps_legacy_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result_path = root / "result.json"
            whole_deck_result = {
                "renderer": "powerpoint-pywin32",
                "image_paths": [str(root / "slide_001.png")],
                "width_px": 1920,
                "height_px": 1080,
            }
            with mock.patch.object(
                ppt_renderer_worker,
                "_export_slides_incrementally",
            ) as incremental, mock.patch.object(
                ppt_renderer_worker,
                "_attempt_powerpoint_pywin32",
                return_value=whole_deck_result,
            ):
                exit_code = ppt_renderer_worker.main(
                    [
                        "worker",
                        str(root / "deck.pptx"),
                        str(root / "png"),
                        str(result_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            incremental.assert_not_called()
