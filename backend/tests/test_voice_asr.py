"""voice_asr 引擎与 WS 流协议测试。

不依赖真实模型文件：引擎状态用 monkeypatch 的假状态探测；识别逻辑用
FakeSession 验证 partial/final 事件序列、endpoint 静音分段与 flush 行为。
真实模型只在演示机安装（scripts/download_voice_models.py），测试跳过。
"""
import tempfile
import unittest
from pathlib import Path
from typing import Tuple
from unittest import mock

from backend.app.config import AppConfig
from backend.app.services import voice_asr as voice_asr_module
from backend.app.services.voice_asr import VoiceAsrEngine, VoiceAsrSession


def hermetic_config() -> AppConfig:
    """AppConfig with a temp data_dir so neither the dev machine's legacy
    in-repo models nor the per-user stable model directory can leak into
    test outcomes."""
    config = AppConfig(root_dir=Path(__file__).resolve().parents[2])
    temp_dir = tempfile.TemporaryDirectory()
    config.data_dir = Path(temp_dir.name)
    config.voice_model_dir = ""
    config.voice_model_stable_root = str(config.data_dir / "voice-models-stable")
    config.state_dir = config.data_dir / "state"
    config.uploads_dir = config.data_dir / "uploads"
    config.outputs_dir = config.data_dir / "outputs"
    config.ensure_dirs()
    return config


class VoiceAsrEngineStatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = hermetic_config()

    def test_status_reports_missing_models_without_error(self) -> None:
        engine = VoiceAsrEngine(self.config)
        status = engine.status()
        self.assertFalse(status["available"])
        self.assertIn(status["reason"], {"models_not_downloaded", "sherpa_onnx_not_installed", "disabled_by_config"})

    def test_status_disabled_by_config(self) -> None:
        self.config.voice_asr_enabled = False
        engine = VoiceAsrEngine(self.config)
        status = engine.status()
        self.assertFalse(status["available"])
        self.assertEqual(status["reason"], "disabled_by_config")

    def test_create_session_raises_when_unavailable(self) -> None:
        engine = VoiceAsrEngine(self.config)
        with self.assertRaises(RuntimeError):
            engine.create_session()


class FakeStream:
    def __init__(self):
        self.owner = None

    def accept_waveform(self, sample_rate, samples):
        self.last_sample_rate = sample_rate
        self.last_size = len(samples)
        # 新音频到达：识别器重新变为 ready（由 FakeRecognizer 注册回调）。
        if self.owner is not None:
            self.owner._decoded = False


class FakeRecognizer:
    """Deterministic recognizer: emits text for non-silent chunks, endpoints on cue."""

    def __init__(self):
        self.endpoint_after_chunks = 4
        self.chunks = 0
        self.reset_count = 0
        self._decoded = False
        self.stream = FakeStream()
        self.stream.owner = self

    def create_stream(self):
        return self.stream

    def is_ready(self, stream) -> bool:
        # 每个音频块只消费一次，模拟真实识别器 ready 语义，
        # 否则 feed 里的 while is_ready: decode 循环永不终止。
        return self.chunks > 0 and not self._decoded

    def decode_stream(self, stream) -> None:
        self._decoded = True

    def get_result(self, stream) -> str:
        # 只要消费过音频就有累积文本；endpoint 与否只影响分段，不影响文本。
        return "切换到三维地球" if self.chunks else ""

    def is_endpoint(self, stream) -> bool:
        return self.chunks >= self.endpoint_after_chunks

    def reset(self, stream) -> bool:
        self.reset_count += 1
        self.chunks = 0
        self._decoded = False
        return True


class VoiceAsrSessionLogicTest(unittest.TestCase):
    def _session(self) -> Tuple[VoiceAsrSession, FakeRecognizer]:
        fake = FakeRecognizer()
        engine = mock.Mock(spec=VoiceAsrEngine)
        engine._ensure_recognizer.return_value = fake
        session = VoiceAsrSession.__new__(VoiceAsrSession)
        session._engine = engine
        session._recognizer = fake
        session.stream = fake.create_stream()
        session._last_partial = ""
        return session, fake

    def test_feed_emits_partial_then_final_on_endpoint(self) -> None:
        session, fake = self._session()
        fake.chunks = 1
        events = session.feed(b"\x00\x01" * 160)
        self.assertEqual([event["type"] for event in events], ["partial"])
        self.assertEqual(events[0]["text"], "切换到三维地球")

        # 到达 endpoint：final 事件 + 识别器重置。
        fake.chunks = fake.endpoint_after_chunks
        events = session.feed(b"\x00\x01" * 160)
        self.assertEqual([event["type"] for event in events], ["final"])
        self.assertEqual(fake.reset_count, 1)

    def test_feed_empty_bytes_returns_no_events(self) -> None:
        session, _fake = self._session()
        self.assertEqual(session.feed(b""), [])

    def test_duplicate_partials_suppressed(self) -> None:
        session, fake = self._session()
        fake.chunks = 1
        first = session.feed(b"\x00\x01" * 160)
        second = session.feed(b"\x00\x01" * 160)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_flush_returns_pending_utterance(self) -> None:
        session, fake = self._session()
        fake.endpoint_after_chunks = 99  # 永不触发 endpoint
        fake.chunks = 1
        final = session.flush()
        self.assertEqual(final, {"type": "final", "text": "切换到三维地球"})

    def test_flush_without_utterance_returns_none(self) -> None:
        session, fake = self._session()
        fake.endpoint_after_chunks = 99
        fake.chunks = 0
        self.assertIsNone(session.flush())

    def test_flush_decodes_audio_made_ready_by_input_finished(self) -> None:
        session, fake = self._session()
        pending = ["尾句第一部分", "完整尾句"]
        fake.stream.input_finished = mock.Mock()
        fake.is_ready = mock.Mock(side_effect=lambda stream: bool(pending))
        result = [""]

        def decode(stream):
            fake.stream.input_finished.assert_called_once_with()
            result[0] = pending.pop(0)

        fake.decode_stream = mock.Mock(side_effect=decode)
        fake.get_result = mock.Mock(side_effect=lambda stream: result[0])

        self.assertEqual(session.flush(), {"type": "final", "text": "完整尾句"})
        self.assertEqual(fake.decode_stream.call_count, 2)

    def test_numpy_missing_keeps_engine_unavailable(self) -> None:
        with mock.patch.object(voice_asr_module, "_numpy", None), mock.patch.object(
            voice_asr_module, "_sherpa_onnx", None
        ):
            engine = VoiceAsrEngine(hermetic_config())
            self.assertFalse(engine.available())


# 供状态矩阵测试使用的极小“模型文件”尺寸门槛（真实门槛为 100MB 量级）。
TINY_MIN_BYTES = {"encoder.int8.onnx": 8, "decoder.int8.onnx": 8, "tokens.txt": 4}


def write_model_files(model_dir: Path, names, size: int = 16) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (model_dir / name).write_bytes(b"\x00" * size)


class VoiceAsrReadinessStateTest(unittest.TestCase):
    """就绪状态机：not_installed / incomplete / load_failed / initializing / ready。"""

    def setUp(self) -> None:
        self.config = hermetic_config()
        self.paraformer_dir = (
            Path(self.config.voice_model_stable_root)
            / "sherpa-onnx-streaming-paraformer-bilingual-zh-en"
        )

    def _engine(self) -> VoiceAsrEngine:
        return VoiceAsrEngine(self.config)

    def test_state_not_installed_when_no_files(self) -> None:
        status = self._engine().status()
        if voice_asr_module._sherpa_onnx is None or voice_asr_module._numpy is None:
            self.assertEqual(status["state"], "not_installed")
            self.assertEqual(status["reason"], "sherpa_onnx_not_installed")
        else:
            self.assertEqual(status["state"], "not_installed")
            self.assertEqual(status["reason"], "models_not_downloaded")
        self.assertFalse(status["available"])

    def test_state_incomplete_when_files_missing(self) -> None:
        from backend.app.services import voice_model_paths

        write_model_files(self.paraformer_dir, ["encoder.int8.onnx", "tokens.txt"])
        with mock.patch.dict(voice_model_paths.MIN_FILE_BYTES, TINY_MIN_BYTES):
            status = self._engine().status()
        self.assertEqual(status["state"], "incomplete")
        self.assertEqual(status["reason"], "models_incomplete")
        self.assertFalse(status["available"])

    def test_state_incomplete_when_file_undersized(self) -> None:
        from backend.app.services import voice_model_paths

        write_model_files(self.paraformer_dir, voice_model_paths.MODEL_FILES, size=1)
        with mock.patch.dict(voice_model_paths.MIN_FILE_BYTES, TINY_MIN_BYTES):
            status = self._engine().status()
        self.assertEqual(status["state"], "incomplete")
        self.assertFalse(status["available"])

    def test_state_ready_when_files_complete_and_recognizer_loaded(self) -> None:
        from backend.app.services import voice_model_paths

        write_model_files(self.paraformer_dir, voice_model_paths.MODEL_FILES)
        engine = self._engine()
        engine._recognizer = object()  # 模拟已完成加载
        with mock.patch.dict(voice_model_paths.MIN_FILE_BYTES, TINY_MIN_BYTES):
            status = engine.status()
        self.assertEqual(status["state"], "ready")
        self.assertTrue(status["available"])
        self.assertTrue(status["model"])

    def test_state_load_failed_reported(self) -> None:
        from backend.app.services import voice_model_paths

        write_model_files(self.paraformer_dir, voice_model_paths.MODEL_FILES)
        engine = self._engine()
        engine._init_error = "recognizer_init_failed: boom"
        with mock.patch.dict(voice_model_paths.MIN_FILE_BYTES, TINY_MIN_BYTES):
            status = engine.status()
        self.assertEqual(status["state"], "load_failed")
        self.assertFalse(status["available"])

    def test_state_initializing_while_warm_up_running(self) -> None:
        from backend.app.services import voice_model_paths

        write_model_files(self.paraformer_dir, voice_model_paths.MODEL_FILES)
        engine = self._engine()
        engine._warming = True
        with mock.patch.dict(voice_model_paths.MIN_FILE_BYTES, TINY_MIN_BYTES):
            status = engine.status()
        self.assertEqual(status["state"], "initializing")

    @unittest.skipIf(voice_asr_module._numpy is None, "numpy not installed")
    def test_warm_up_loads_recognizer_in_background(self) -> None:
        from backend.app.services import voice_model_paths

        write_model_files(self.paraformer_dir, voice_model_paths.MODEL_FILES)
        fake_recognizer = object()
        fake_module = mock.Mock()
        fake_module.OnlineRecognizer.from_paraformer.return_value = fake_recognizer
        engine = self._engine()
        with mock.patch.dict(voice_model_paths.MIN_FILE_BYTES, TINY_MIN_BYTES), mock.patch.object(
            voice_asr_module, "_sherpa_onnx", fake_module
        ):
            engine.warm_up()
            for _ in range(200):  # 最多等 ~2s
                if engine._recognizer is not None and not engine._warming:
                    break
                import time

                time.sleep(0.01)
            status = engine.status()
        self.assertIs(engine._recognizer, fake_recognizer)
        self.assertEqual(status["state"], "ready")
        fake_module.OnlineRecognizer.from_paraformer.assert_called_once()
        self.assertFalse(engine._warming)

    def test_model_dir_env_override_wins(self) -> None:
        custom_root = Path(self.config.data_dir) / "custom-models"
        self.config.voice_model_dir = str(custom_root)
        engine = self._engine()
        self.assertEqual(engine.model_dir(), custom_root / "sherpa-onnx-streaming-paraformer-bilingual-zh-en")

    def test_model_dir_prefers_complete_legacy_over_stable(self) -> None:
        from backend.app.services import voice_model_paths

        legacy_dir = self.config.data_dir / "voice-models" / "sherpa-onnx-streaming-paraformer-bilingual-zh-en"
        write_model_files(legacy_dir, voice_model_paths.MODEL_FILES)
        engine = self._engine()
        with mock.patch.dict(voice_model_paths.MIN_FILE_BYTES, TINY_MIN_BYTES):
            self.assertEqual(engine.model_dir(), legacy_dir)


if __name__ == "__main__":
    unittest.main()
