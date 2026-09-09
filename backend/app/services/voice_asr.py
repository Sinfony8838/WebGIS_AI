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
``status()`` reports a precise ``state`` and the frontend falls back to Web
Speech or text input. No existing test needs the models.

Readiness states (``status()["state"]``):
    disabled      voice ASR turned off by configuration
    not_installed dependency missing, or no model file present at all
    incomplete    some model files present but missing/undersized members
    load_failed   model files exist but the recognizer failed to load
    initializing  background warm-up currently loading the recognizer
    ready         recognizer loaded (or loadable) and usable right now
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import AppConfig
from .voice_model_paths import (
    MODEL_FILES,
    PARAFORMER_SUBDIR,
    files_complete,
    missing_files,
    resolve_model_dir,
    undersized_files,
)

try:  # heavy optional dependency; absence must not break the backend
    import numpy as _numpy
    import sherpa_onnx as _sherpa_onnx
except Exception:  # pragma: no cover - depends on local environment
    _numpy = None
    _sherpa_onnx = None


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
        self._warming = False

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def model_dir(self) -> Path:
        """Resolve via the shared rule (env override → complete legacy dir →
        stable per-user dir) so every worktree sees the same installation."""
        override = self.config.voice_model_dir or None
        stable_root = self.config.voice_model_stable_root or None
        return resolve_model_dir(
            legacy_data_dir=self.config.data_dir,
            override=Path(override) if override else None,
            stable_root=Path(stable_root) if stable_root else None,
        )

    def _files_ready(self) -> bool:
        if not self.config.voice_asr_enabled or _sherpa_onnx is None or _numpy is None:
            return False
        return files_complete(self.model_dir())

    def available(self) -> bool:
        """True when a streaming session can be created right now."""
        return self._files_ready() and not self._init_error

    def status(self) -> Dict[str, Any]:
        if not self.config.voice_asr_enabled:
            state = "disabled"
        elif _sherpa_onnx is None or _numpy is None:
            state = "not_installed"
        elif self._init_error:
            state = "load_failed"
        elif self._warming:
            state = "initializing"
        elif self._recognizer is not None:
            state = "ready"
        else:
            model_dir = self.model_dir()
            missing = missing_files(model_dir)
            if missing:
                # Distinguish "nothing downloaded at all" from "partial
                # download" so operators know whether to run the script once
                # or to repair a broken install.
                state = "incomplete" if len(missing) < len(MODEL_FILES) else "not_installed"
            elif undersized_files(model_dir):
                state = "incomplete"
            else:
                # Files complete, recognizer not loaded yet: lazy load on the
                # next session. Report ready (legacy contract); a load failure
                # surfaces as load_failed once attempted.
                state = "ready"

        reason = ""
        if state == "disabled":
            reason = "disabled_by_config"
        elif state == "not_installed":
            reason = "sherpa_onnx_not_installed" if (_sherpa_onnx is None or _numpy is None) else "models_not_downloaded"
        elif state == "incomplete":
            reason = "models_incomplete"
        elif state == "load_failed":
            reason = self._init_error

        return {
            "available": self.available(),
            "state": state,
            "reason": reason,
            "model": PARAFORMER_SUBDIR if self._files_ready() else "",
            "model_dir": str(self.model_dir()),
        }

    # ------------------------------------------------------------------
    # Recognizer lifecycle
    # ------------------------------------------------------------------

    def warm_up(self) -> None:
        """Start loading the recognizer in a daemon thread (idempotent).

        Called once at runtime startup so the first browser connection does
        not pay the multi-second ONNX session cost, and so /health can report
        ``initializing`` instead of silently accepting a slow first session.
        """
        if not self.config.voice_asr_enabled or self._recognizer is not None or self._warming:
            return
        if _sherpa_onnx is None or _numpy is None:
            return
        self._warming = True

        def _load() -> None:
            try:
                self._ensure_recognizer()
            except Exception:
                pass  # _init_error already recorded by _ensure_recognizer
            finally:
                self._warming = False

        threading.Thread(target=_load, name="voice-asr-warmup", daemon=True).start()

    def warm_up_sync(self) -> None:
        """Blocking variant used by the deployment check script."""
        self._ensure_recognizer()

    def _ensure_recognizer(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer
        with self._lock:
            if self._recognizer is not None:
                return self._recognizer
            if _sherpa_onnx is None or _numpy is None:
                raise RuntimeError("sherpa-onnx is not installed")
            model_dir = self.model_dir()
            missing = missing_files(model_dir)
            if missing:
                raise RuntimeError("voice ASR models missing: " + ", ".join(missing))
            undersized = undersized_files(model_dir)
            if undersized:
                raise RuntimeError("voice ASR models incomplete (undersized files): " + ", ".join(undersized))
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
        while self._recognizer.is_ready(self.stream):
            self._recognizer.decode_stream(self.stream)
        text = (self._recognizer.get_result(self.stream) or "").strip()
        return {"type": "final", "text": text} if text else None

    def close(self) -> None:
        # Streams are owned by the recognizer's internal pool after reset;
        # nothing to free explicitly, but keep the hook for future teardown.
        self.stream = None


def build_voice_asr_engine(config: AppConfig) -> VoiceAsrEngine:
    return VoiceAsrEngine(config)
