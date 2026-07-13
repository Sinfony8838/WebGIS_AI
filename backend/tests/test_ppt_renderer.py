from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from backend.app.services import ppt_renderer


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
