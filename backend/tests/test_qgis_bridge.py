from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from backend.app.config import AppConfig
from backend.app.services.qgis_bridge import QgisBridgeClient


class QgisBridgeFocusWindowTest(unittest.TestCase):
    def test_focus_window_parses_json_payload(self) -> None:
        client = QgisBridgeClient(AppConfig())
        completed = subprocess.CompletedProcess(
            args=["powershell"],
            returncode=0,
            stdout='{"ok":true,"message":"QGIS window focused","method":"SetForegroundWindow"}',
            stderr="",
        )
        with patch("backend.app.services.qgis_bridge.subprocess.run", return_value=completed):
            result = client.focus_window()

        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "QGIS window focused")
        self.assertEqual(result["method"], "SetForegroundWindow")

    def test_focus_window_returns_plain_stdout_when_not_json(self) -> None:
        client = QgisBridgeClient(AppConfig())
        completed = subprocess.CompletedProcess(
            args=["powershell"],
            returncode=0,
            stdout="QGIS window restored",
            stderr="",
        )
        with patch("backend.app.services.qgis_bridge.subprocess.run", return_value=completed):
            result = client.focus_window()

        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "QGIS window restored")

    def test_focus_window_returns_error_payload_on_nonzero_exit(self) -> None:
        client = QgisBridgeClient(AppConfig())
        completed = subprocess.CompletedProcess(
            args=["powershell"],
            returncode=1,
            stdout="",
            stderr="QGIS window not found",
        )
        with patch("backend.app.services.qgis_bridge.subprocess.run", return_value=completed):
            result = client.focus_window()

        self.assertFalse(result["ok"])
        self.assertIn("QGIS window not found", result["message"])
