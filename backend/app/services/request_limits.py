"""Request-budget primitives (phase-1 audit task T3).

* ``BodySizeLimitMiddleware`` — pure ASGI middleware that counts the bytes
  actually received for JSON bodies and answers 413 before FastAPI parses
  the request, so oversized payloads never reach deserialization.
* ``read_upload_limited`` — chunked multipart-file reader with a hard byte
  ceiling (replaces unbounded ``await file.read()``).
* ``AdmissionGate`` — bounded semaphore with a queue timeout for the QGIS
  worker pipeline (configurable ceiling, explicit busy error instead of an
  unbounded wait).
* ``VoiceSessionGate`` — per-user concurrent voice-stream cap.
"""
from __future__ import annotations

import threading
from typing import Any, Dict

CHUNK_SIZE = 1024 * 1024

_STATUS_413: Dict[str, Any] = {
    "type": "http.response.start",
    "status": 413,
    "headers": [(b"content-type", b"application/json")],
}


class PayloadTooLarge(Exception):
    """Raised when an upload exceeds its endpoint's byte ceiling."""


class BodySizeLimitMiddleware:
    """Reject oversized JSON bodies by counting received bytes.

    Runs below the FastAPI routing layer (pure ASGI), so the rejection
    happens before any request-model deserialization. WebSocket and lifecycle
    scopes pass through untouched; non-JSON content types are not counted
    (multipart uploads enforce their own per-endpoint ceilings).
    """

    def __init__(self, app: Any, max_json_body_bytes: int) -> None:
        self.app = app
        self.max_json_body_bytes = int(max_json_body_bytes)

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        content_type = headers.get("content-type", "")
        declared = headers.get("content-length")
        if (
            scope.get("method") in {"POST", "PUT", "PATCH"}
            and "application/json" in content_type
        ):
            if declared and declared.isdigit() and int(declared) > self.max_json_body_bytes:
                await send(_STATUS_413)
                await send({"type": "http.response.body", "body": '{"detail":"请求体过大"}'.encode("utf-8")})
                return

            received = 0
            rejected = False
            body_413 = '{"detail":"请求体过大"}'.encode("utf-8")

            async def counting_receive() -> Dict[str, Any]:
                nonlocal received, rejected
                message = await receive()
                if rejected:
                    return {"type": "http.disconnect"}
                if message.get("type") == "http.request":
                    received += len(message.get("body", b""))
                    if received > self.max_json_body_bytes:
                        rejected = True
                        await send(_STATUS_413)
                        await send({"type": "http.response.body", "body": body_413})
                        # Hand the app a complete empty body so it finishes
                        # cleanly (its response is swallowed below); drain any
                        # remaining wire chunks so the transport stays sane.
                        if message.get("more_body", False):
                            while True:
                                drain = await receive()
                                if drain.get("type") != "http.request" or not drain.get("more_body", False):
                                    break
                        return {"type": "http.request", "body": b"", "more_body": False}
                    return message
                return message

            async def guarded_send(message: Dict[str, Any]) -> None:
                if rejected:
                    return
                await send(message)

            await self.app(scope, counting_receive, guarded_send)
            return
        await self.app(scope, receive, send)


async def read_upload_limited(upload: Any, max_bytes: int) -> bytes:
    """Read an UploadFile in chunks, refusing payloads above ``max_bytes``."""
    chunks: list[bytes] = []
    received = 0
    while True:
        chunk = await upload.read(CHUNK_SIZE)
        if not chunk:
            break
        received += len(chunk)
        if received > max_bytes:
            raise PayloadTooLarge(f"upload exceeds limit of {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


class AdmissionGate:
    """Bounded concurrency with an explicit queue timeout.

    ``acquire`` returns False when no slot frees up within ``timeout``
    seconds — callers turn that into a user-friendly busy error instead of
    queueing without bound.
    """

    def __init__(self, max_concurrent: int, timeout: float = 120.0) -> None:
        self._semaphore = threading.BoundedSemaphore(max(1, int(max_concurrent)))
        self.timeout = float(timeout)
        self._lock = threading.Lock()
        self._waiting = 0

    def acquire(self, timeout: float | None = None) -> bool:
        with self._lock:
            self._waiting += 1
        try:
            return self._semaphore.acquire(timeout=self.timeout if timeout is None else timeout)
        finally:
            with self._lock:
                self._waiting -= 1

    def release(self) -> None:
        try:
            self._semaphore.release()
        except ValueError:
            pass

    @property
    def waiting(self) -> int:
        with self._lock:
            return self._waiting


class VoiceSessionGate:
    """Per-user cap on concurrent voice WebSocket sessions."""

    def __init__(self, max_per_user: int) -> None:
        self.max_per_user = max(1, int(max_per_user))
        self._counts: Dict[str, int] = {}
        self._lock = threading.Lock()

    def enter(self, user_key: str) -> bool:
        with self._lock:
            current = self._counts.get(user_key, 0)
            if current >= self.max_per_user:
                return False
            self._counts[user_key] = current + 1
            return True

    def leave(self, user_key: str) -> None:
        with self._lock:
            remaining = self._counts.get(user_key, 0) - 1
            if remaining > 0:
                self._counts[user_key] = remaining
            else:
                self._counts.pop(user_key, None)
