"""Request-local model budget, cancellation and activity for voice goals.

Context variables cover nested service calls without changing the legacy client
API. Background workflow summarizers are deliberately disabled for assistant
workflows, so they cannot escape this request's ledger.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Dict, Optional


class RunStopped(RuntimeError):
    pass


class ModelBudgetExceeded(RunStopped):
    pass


@dataclass
class InteractionRun:
    job_id: str
    max_model_calls: int = 3
    max_seconds: float = 180.0
    cancelled: Callable[[], bool] = lambda: False
    publish: Callable[[Dict[str, Any], Dict[str, Any]], None] = lambda activity, usage: None
    observe_ui: Optional[Callable[[list], list]] = None
    started: float = field(default_factory=time.monotonic)
    route: str = "direct"
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    unknown_usage: bool = False
    model_ms: float = 0.0
    activity: Dict[str, Any] = field(default_factory=dict)
    observations: list = field(default_factory=list)
    _lock: Any = field(default_factory=RLock, repr=False)
    _closers: list = field(default_factory=list, repr=False)

    def check(self) -> None:
        if self.cancelled():
            raise RunStopped("操作已停止；已完成的结果已保留。")
        if time.monotonic() - self.started >= self.max_seconds:
            raise RunStopped("已达到任务时间上限；已完成的结果已保留。")

    def remaining_seconds(self) -> float:
        self.check()
        return max(0.01, self.max_seconds - (time.monotonic() - self.started))

    def usage(self) -> Dict[str, Any]:
        return {"model_calls": self.calls, "model_call_limit": self.max_model_calls,
                "input_tokens": None if self.unknown_usage else self.input_tokens,
                "output_tokens": None if self.unknown_usage else self.output_tokens,
                "model_ms": round(self.model_ms, 2),
                "elapsed_ms": round((time.monotonic() - self.started) * 1000, 2),
                "route": self.route, "asr_tts": "accounted_separately"}

    def emit(self, phase: str, label: str, **details: Any) -> None:
        self.activity = {"phase": phase, "label": label, "route": self.route, **details}
        self.publish(dict(self.activity), self.usage())

    def before_model(self) -> float:
        with self._lock:
            self.check()
            if self.calls >= self.max_model_calls:
                raise ModelBudgetExceeded("已用完本回合 3 次模型请求预算；未继续调用模型。")
            self.calls += 1
            self.emit("thinking", "智能体思考中", step=self.calls)
            return time.monotonic()

    def after_model(self, started: float, usage: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self.model_ms += (time.monotonic() - started) * 1000
            usage = usage or {}
            incoming = usage.get("input_tokens", usage.get("prompt_tokens"))
            outgoing = usage.get("output_tokens", usage.get("completion_tokens"))
            if not isinstance(incoming, int) or not isinstance(outgoing, int):
                self.unknown_usage = True
            else:
                self.input_tokens += incoming
                self.output_tokens += outgoing
            self.publish(dict(self.activity), self.usage())

    @contextmanager
    def response_scope(self, response: Any):
        """Close an active HTTP response when cancellation interrupts reading."""
        self.check()
        with self._lock:
            self._closers.append(response.close)
        try:
            yield
        finally:
            with self._lock:
                if response.close in self._closers:
                    self._closers.remove(response.close)

    def close_requests(self) -> None:
        with self._lock:
            for close in list(self._closers):
                try:
                    close()
                except Exception:
                    pass


_current: ContextVar[Optional[InteractionRun]] = ContextVar("webgis_interaction_run", default=None)
_usage: ContextVar[Optional[Dict[str, Any]]] = ContextVar("webgis_model_response_usage", default=None)


def current_run() -> Optional[InteractionRun]:
    return _current.get()


@contextmanager
def interaction_scope(run: Optional[InteractionRun]):
    token = _current.set(run)
    try:
        yield run
    finally:
        _current.reset(token)


def capture_model_usage(usage: Optional[Dict[str, Any]]) -> None:
    _usage.set(usage)


@contextmanager
def model_request_scope():
    run = current_run()
    if run is None:
        yield
        return
    started = run.before_model()
    token = _usage.set(None)
    try:
        yield
        run.check()
    finally:
        run.after_model(started, _usage.get())
        _usage.reset(token)


def complete(client: Any, *args: Any, **kwargs: Any) -> str:
    """Also meter injected/test clients; the production client meters at HTTP admission."""
    if client is None:
        raise RuntimeError("模型服务尚未配置。")
    if getattr(type(client), "meters_interaction_requests", False):
        return client.chat_completion(*args, **kwargs)
    with model_request_scope():
        return client.chat_completion(*args, **kwargs)
