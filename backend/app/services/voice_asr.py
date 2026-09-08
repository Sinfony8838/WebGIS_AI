"""Local streaming voice recognition backed by sherpa-onnx.

The classroom demo cannot rely on the browser Web Speech API: Chrome routes
its recognition through Google servers, which are unreachable on the demo
network, and its accuracy on spontaneous classroom Chinese is weak. This
engine runs the open-source streaming Paraformer bilingual (zh-en) model
fully locally on the FastAPI backend. The browser captures microphone audio
with AudioWorklet and streams 16 kHz mono PCM16 frames over a WebSocket;
``VoiceAsrSession.feed`` returns partial/final transcript events using the
recognizer's built-in endpoint detection (VAD-style silence splitting).

Everything degrades gracefully: when sherpa-onnx is not installed or the
model files have not been downloaded (``scripts/download_voice_models.py``),
``available()`` reports False and the frontend falls back to Web Speech or
text input. No existing test needs the models.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import AppConfig

try:  # heavy optional dependency; absence must not break the backend
    import numpy as _numpy
    import sherpa_onnx as _sherpa_onnx
except Exception:  # pragma: no cover - depends on local environment
    _numpy = None
    _sherpa_onnx = None

MODEL_DIR_NAME = "voice-models"
PARAFORMER_SUBDIR = "sherpa-onnx-streaming-paraformer-bilingual-zh-en"
# The release ships fp32 and int8 variants; int8 is the right size/speed
# trade-off for a teacher laptop CPU.
MODEL_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt")


class VoiceAsrEngine:
    """Lazy, thread-safe wrapper around one sherpa-onnx streaming recognizer.

    One recognizer instance is shared across connections (ONNX session reuse);
    every WebSocket connection gets its own ``VoiceAsrSession`` with a fresh
    stream, so teacher and student browsers never bleed audio into each other.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._recognizer: Any = None
        self._lock = threading.Lock()
        self._init_error = ""

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def model_dir(self) -> Path:
        return self.config.data_dir / MODEL_DIR_NAME / PARAFORMER_SUBDIR

    def available(self) -> bool:
        if not self.config.voice_asr_enabled or _sherpa_onnx is None or _numpy is None:
            return False
        model_dir = self.model_dir()
        return all((model_dir / name).is_file() for name in MODEL_FILES)

    def status(self) -> Dict[str, Any]:
        reason = ""
        if not self.config.voice_asr_enabled:
            reason = "disabled_by_config"
        elif _sherpa_onnx is None or _numpy is None:
            reason = "sherpa_onnx_not_installed"
        elif not self.available():
            reason = "models_not_downloaded"
        return {
            "available": self.available() and not self._init_error,
            "reason": reason or self._init_error,
            "model": PARAFORMER_SUBDIR if self.available() else "",
        }

    # ------------------------------------------------------------------
    # Recognizer lifecycle
    # ------------------------------------------------------------------

    def _ensure_recognizer(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer
        with self._lock:
            if self._recognizer is not None:
                return self._recognizer
            if _sherpa_onnx is None or _numpy is None:
                raise RuntimeError("sherpa-onnx is not installed")
            model_dir = self.model_dir()
            missing = [name for name in MODEL_FILES if not (model_dir / name).is_file()]
            if missing:
                raise RuntimeError("voice ASR models missing: " + ", ".join(missing))
            try:
                self._recognizer = _sherpa_onnx.OnlineRecognizer.from_paraformer(
                    tokens=str(model_dir / "tokens.txt"),
                    encoder=str(model_dir / "encoder.int8.onnx"),
                    decoder=str(model_dir / "decoder.int8.onnx"),
                    num_threads=2,
                    sample_rate=16000,
                    feature_dim=80,
                    enable_endpoint_detection=True,
                    rule1_min_trailing_silence=2.4,
                    rule2_min_trailing_silence=1.0,
                    rule3_min_utterance_length=20.0,
                )
                self._init_error = ""
            except Exception as exc:  # pragma: no cover - model loading failures
                self._init_error = f"recognizer_init_failed: {exc}"
                raise
        return self._recognizer

    def create_session(self) -> "VoiceAsrSession":
        return VoiceAsrSession(self)


class VoiceAsrSession:
    """One WebSocket connection worth of streaming recognition state."""

    def __init__(self, engine: VoiceAsrEngine):
        self._engine = engine
        self._recognizer = engine._ensure_recognizer()
        self.stream = self._recognizer.create_stream()
        self._last_partial = ""

    def feed(self, pcm16: bytes) -> List[Dict[str, Any]]:
        """Feed a PCM16/16kHz mono chunk; return transcript events to send back.

        Events: ``{"type": "partial", "text": ...}`` while a utterance is in
        progress and ``{"type": "final", "text": ...}`` once endpoint
        detection closes the utterance (trailing silence / max length).
        """
        if not pcm16:
            return []
        samples = _numpy.frombuffer(pcm16, dtype=_numpy.int16).astype(_numpy.float32) / 32768.0
        self.stream.accept_waveform(16000, samples)
        while self._recognizer.is_ready(self.stream):
            self._recognizer.decode_stream(self.stream)
        text = (self._recognizer.get_result(self.stream) or "").strip()
        events: List[Dict[str, Any]] = []
        if self._recognizer.is_endpoint(self.stream):
            if text:
                events.append({"type": "final", "text": text})
            self._recognizer.reset(self.stream)
            self._last_partial = ""
            return events
        if text and text != self._last_partial:
            self._last_partial = text
            events.append({"type": "partial", "text": text})
        return events

    def flush(self) -> Optional[Dict[str, Any]]:
        """Close the audio side and emit any pending utterance as final."""
        try:
            self.stream.input_finished()
        except Exception:
            pass
        text = (self._recognizer.get_result(self.stream) or "").strip()
        return {"type": "final", "text": text} if text else None

    def close(self) -> None:
        # Streams are owned by the recognizer's internal pool after reset;
        # nothing to free explicitly, but keep the hook for future teardown.
        self.stream = None


def build_voice_asr_engine(config: AppConfig) -> VoiceAsrEngine:
    return VoiceAsrEngine(config)
