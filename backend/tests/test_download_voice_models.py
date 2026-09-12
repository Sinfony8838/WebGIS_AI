"""scripts/download_voice_models.py 行为测试。

覆盖：完整模型直接返回成功；部分文件不再"假成功"而是补齐下载；
--force 重装；--check 依赖+完整性+真实加载。下载与解压均被替换为
本地桩，测试不访问网络、不写入真实模型体积的文件。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "download_voice_models.py"

_spec = importlib.util.spec_from_file_location("download_voice_models", str(SCRIPT_PATH))
assert _spec is not None and _spec.loader is not None
script = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("download_voice_models", script)
_spec.loader.exec_module(script)

from backend.app.services import voice_model_paths as vmp  # noqa: E402


def tiny_sizes():
    return {name: 8 for name in vmp.MODEL_FILES}


def fake_extract_factory(target_files: dict[str, int]):
    """返回 extract_and_validate 的替身：按给出的字节数写出模型文件。"""

    def fake_extract(archive_path: Path, extract_dir: Path) -> dict[str, Path]:
        extract_dir.mkdir(parents=True, exist_ok=True)
        found: dict[str, Path] = {}
        for name, size in target_files.items():
            path = extract_dir / name
            path.write_bytes(b"\x00" * size)
            found[name] = path
        return found

    return fake_extract


class DownloadScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        import os

        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)
        self.legacy_data_dir = self.base / "backend" / "data"
        self.stable_root = self.base / "stable"
        self._patches = [
            mock.patch.object(script, "legacy_data_dir", return_value=self.legacy_data_dir),
            mock.patch.dict(vmp.MIN_FILE_BYTES, tiny_sizes()),
        ]
        # 脚本以 ``app.services.voice_model_paths`` 导入共享模块，而测试以
        # ``backend.app.services...`` 导入：进程内存在两个副本，尺寸门槛的
        # 补丁必须同时作用于两者。
        script_vmp = sys.modules.get("app.services.voice_model_paths")
        if script_vmp is not None and script_vmp is not vmp:
            self._patches.append(mock.patch.dict(script_vmp.MIN_FILE_BYTES, tiny_sizes()))
        for patch in self._patches:
            patch.start()
        self._os = os
        self._backup = (os.environ.get(vmp.ENV_MODEL_DIR), os.environ.get(vmp.ENV_STABLE_ROOT))
        os.environ.pop(vmp.ENV_MODEL_DIR, None)
        # 把稳定目录钉到临时目录：main()/check() 的解析结果都落在测试沙箱里。
        os.environ[vmp.ENV_STABLE_ROOT] = str(self.stable_root)

    def tearDown(self) -> None:
        for patch in self._patches:
            patch.stop()
        model_dir, stable_root = self._backup
        if model_dir is None:
            self._os.environ.pop(vmp.ENV_MODEL_DIR, None)
        else:
            self._os.environ[vmp.ENV_MODEL_DIR] = model_dir
        if stable_root is None:
            self._os.environ.pop(vmp.ENV_STABLE_ROOT, None)
        else:
            self._os.environ[vmp.ENV_STABLE_ROOT] = stable_root
        self._temp.cleanup()

    def test_complete_model_reports_success_without_download(self) -> None:
        target = vmp.paraformer_dir(self.stable_root)
        target.mkdir(parents=True, exist_ok=True)
        for name in vmp.MODEL_FILES:
            (target / name).write_bytes(b"\x00" * 16)
        download = mock.Mock(side_effect=AssertionError("must not download"))
        with mock.patch.object(sys, "argv", ["download_voice_models.py"]), mock.patch.object(
            script, "download_archive", download
        ):
            self.assertEqual(script.main(), 0)
        download.assert_not_called()

    def test_partial_files_are_repaired_not_reported_success(self) -> None:
        # 旧逻辑缺陷：3 个文件只剩 1 个也直接返回成功。这里断言必须补齐。
        target = vmp.paraformer_dir(self.stable_root)
        target.mkdir(parents=True, exist_ok=True)
        (target / "tokens.txt").write_bytes(b"\x00" * 16)
        with mock.patch.object(sys, "argv", ["download_voice_models.py"]), mock.patch.object(
            script, "download_archive", lambda tmp: Path(tmp) / "fake.tar.bz2"
        ), mock.patch.object(
            script,
            "extract_and_validate",
            fake_extract_factory({name: 32 for name in vmp.MODEL_FILES}),
        ):
            self.assertEqual(script.main(), 0)
        for name in vmp.MODEL_FILES:
            self.assertTrue((target / name).is_file(), name)
            self.assertGreaterEqual((target / name).stat().st_size, 8)

    def test_force_reinstalls(self) -> None:
        target = vmp.paraformer_dir(self.stable_root)
        target.mkdir(parents=True, exist_ok=True)
        for name in vmp.MODEL_FILES:
            (target / name).write_bytes(b"\x00" * 16)
        with mock.patch.object(sys, "argv", ["download_voice_models.py", "--force"]), mock.patch.object(
            script, "download_archive", lambda tmp: Path(tmp) / "fake.tar.bz2"
        ), mock.patch.object(
            script,
            "extract_and_validate",
            fake_extract_factory({name: 64 for name in vmp.MODEL_FILES}),
        ):
            self.assertEqual(script.main(), 0)
        for name in vmp.MODEL_FILES:
            self.assertEqual((target / name).stat().st_size, 64)

    def test_truncated_archive_files_are_rejected(self) -> None:
        # 解压出的文件小于门槛：必须失败，绝不安装半截模型。
        with mock.patch.object(sys, "argv", ["download_voice_models.py"]), mock.patch.object(
            script, "download_archive", lambda tmp: Path(tmp) / "fake.tar.bz2"
        ), mock.patch.object(
            script,
            "extract_and_validate",
            mock.Mock(side_effect=RuntimeError("encoder.int8.onnx is truncated")),
        ):
            with self.assertRaises(RuntimeError):
                script.main()
        target = vmp.paraformer_dir(self.stable_root)
        self.assertFalse(target.exists())

    def test_check_fails_when_files_missing(self) -> None:
        self.assertEqual(script.check(), 1)

    def test_check_passes_with_dependencies_and_real_load(self) -> None:
        target = vmp.paraformer_dir(self.stable_root)
        target.mkdir(parents=True, exist_ok=True)
        for name in vmp.MODEL_FILES:
            (target / name).write_bytes(b"\x00" * 32)
        fake_sherpa = mock.Mock()
        fake_sherpa.OnlineRecognizer.from_paraformer.return_value = object()
        with mock.patch.dict(sys.modules, {"sherpa_onnx": fake_sherpa, "numpy": mock.Mock()}):
            self.assertEqual(script.check(), 0)
        fake_sherpa.OnlineRecognizer.from_paraformer.assert_called_once()

    def test_check_fails_when_real_load_raises(self) -> None:
        target = vmp.paraformer_dir(self.stable_root)
        target.mkdir(parents=True, exist_ok=True)
        for name in vmp.MODEL_FILES:
            (target / name).write_bytes(b"\x00" * 32)
        fake_sherpa = mock.Mock()
        fake_sherpa.OnlineRecognizer.from_paraformer.side_effect = RuntimeError("bad onnx")
        with mock.patch.dict(sys.modules, {"sherpa_onnx": fake_sherpa, "numpy": mock.Mock()}):
            self.assertEqual(script.check(), 1)


if __name__ == "__main__":
    unittest.main()
