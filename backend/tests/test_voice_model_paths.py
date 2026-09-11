"""voice_model_paths 共享解析规则测试（后端与下载脚本共用的同一套逻辑）。"""
from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from backend.app.services import voice_model_paths as vmp


def write_complete(directory: Path, size: int = 32) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in vmp.MODEL_FILES:
        (directory / name).write_bytes(b"\x00" * size)


@contextmanager
def tiny_min_sizes():
    """测试中把体积门槛缩到极小，避免写出 100MB 级别的文件。"""
    original = dict(vmp.MIN_FILE_BYTES)
    for name in vmp.MIN_FILE_BYTES:
        vmp.MIN_FILE_BYTES[name] = 8
    try:
        yield
    finally:
        vmp.MIN_FILE_BYTES.clear()
        vmp.MIN_FILE_BYTES.update(original)


class VoiceModelPathsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)
        self.legacy_data_dir = self.base / "backend" / "data"
        self._old_env = (
            os.environ.get(vmp.ENV_MODEL_DIR),
            os.environ.get(vmp.ENV_STABLE_ROOT),
        )
        os.environ.pop(vmp.ENV_MODEL_DIR, None)
        os.environ.pop(vmp.ENV_STABLE_ROOT, None)

    def tearDown(self) -> None:
        old_model_dir, old_stable_root = self._old_env
        if old_model_dir is None:
            os.environ.pop(vmp.ENV_MODEL_DIR, None)
        else:
            os.environ[vmp.ENV_MODEL_DIR] = old_model_dir
        if old_stable_root is None:
            os.environ.pop(vmp.ENV_STABLE_ROOT, None)
        else:
            os.environ[vmp.ENV_STABLE_ROOT] = old_stable_root
        self._temp.cleanup()

    def test_env_override_wins(self) -> None:
        custom = self.base / "custom-root"
        os.environ[vmp.ENV_MODEL_DIR] = str(custom)
        self.assertEqual(vmp.resolve_model_dir(legacy_data_dir=self.legacy_data_dir), vmp.paraformer_dir(custom))
        # 下载目标同样遵循显式覆盖。
        self.assertEqual(vmp.install_target_dir(legacy_data_dir=self.legacy_data_dir), vmp.paraformer_dir(custom))

    def test_complete_legacy_directory_preferred(self) -> None:
        legacy = vmp.paraformer_dir(self.legacy_data_dir / vmp.MODEL_DIR_NAME)
        write_complete(legacy)
        with tiny_min_sizes():
            self.assertEqual(vmp.resolve_model_dir(legacy_data_dir=self.legacy_data_dir), legacy)

    def test_incomplete_legacy_falls_back_to_stable(self) -> None:
        legacy = vmp.paraformer_dir(self.legacy_data_dir / vmp.MODEL_DIR_NAME)
        # 只有一个文件：部分下载不得被视为可用。
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / "tokens.txt").write_bytes(b"\x00" * 32)
        stable = vmp.resolve_model_dir(legacy_data_dir=self.legacy_data_dir, stable_root=self.base / "stable")
        self.assertEqual(stable, vmp.paraformer_dir(self.base / "stable"))

    def test_undersized_legacy_file_is_not_complete(self) -> None:
        legacy = vmp.paraformer_dir(self.legacy_data_dir / vmp.MODEL_DIR_NAME)
        write_complete(legacy, size=4)  # 低于真实最小尺寸门槛
        self.assertFalse(vmp.files_complete(legacy))
        stable = vmp.resolve_model_dir(legacy_data_dir=self.legacy_data_dir, stable_root=self.base / "stable")
        self.assertEqual(stable, vmp.paraformer_dir(self.base / "stable"))

    def test_install_target_never_writes_into_repo(self) -> None:
        legacy = vmp.paraformer_dir(self.legacy_data_dir / vmp.MODEL_DIR_NAME)
        write_complete(legacy)
        target = vmp.install_target_dir(legacy_data_dir=self.legacy_data_dir, stable_root=self.base / "stable")
        self.assertNotIn(str(self.legacy_data_dir), str(target))
        self.assertEqual(target, vmp.paraformer_dir(self.base / "stable"))

    def test_explicit_override_used_even_when_incomplete(self) -> None:
        override = self.base / "override-root"
        override.mkdir(parents=True, exist_ok=True)
        self.assertEqual(
            vmp.resolve_model_dir(legacy_data_dir=self.legacy_data_dir, override=override),
            vmp.paraformer_dir(override),
        )

    def test_stable_root_env_honoured(self) -> None:
        os.environ[vmp.ENV_STABLE_ROOT] = str(self.base / "custom-stable")
        self.assertEqual(
            vmp.resolve_model_dir(legacy_data_dir=self.legacy_data_dir),
            vmp.paraformer_dir(self.base / "custom-stable"),
        )


if __name__ == "__main__":
    unittest.main()
