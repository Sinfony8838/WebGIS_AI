"""Request-budget primitives (phase-1 audit task T3).

* ``BodySizeLimitMiddleware`` — pure ASGI middleware that counts actual wire
  bytes for all media types, with route budgets preserving upload capacities.
* ``BudgetedUploadRoute`` — multipart limits before spool writes, with cleanup
  on size/count violations, malformed input, cancellation and disconnects.
* ``read_upload_limited`` — chunked multipart-file reader with a hard byte
  ceiling (replaces unbounded ``await file.read()``).
* ``AdmissionGate`` — bounded semaphore with a queue timeout for the QGIS
  worker pipeline (configurable ceiling, explicit busy error instead of an
  unbounded wait).
* ``VoiceSessionGate`` — per-user concurrent voice-stream cap.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict

from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException, MultiPartParser
try:
    from python_multipart.exceptions import MultipartParseError
except ImportError:  # python-multipart versions before the package rename
    from multipart.exceptions import MultipartParseError

CHUNK_SIZE = 1024 * 1024

_STATUS_413: Dict[str, Any] = {
    "type": "http.response.start",
    "status": 413,
    "headers": [(b"content-type", b"application/json")],
}


class PayloadTooLarge(Exception):
    """Raised when an upload exceeds its endpoint's byte ceiling."""


@dataclass(frozen=True)
class UploadBudget:
    """Wire and parser budgets; byte values retain existing upload capacities."""

    max_file_bytes: int
    max_files: int = 1
    max_fields: int = 0
    max_field_bytes: int = CHUNK_SIZE
    overhead_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if min(self.max_file_bytes, self.max_field_bytes, self.overhead_bytes) <= 0:
            raise ValueError("Upload byte budgets must be positive")
        if self.max_files < 1 or self.max_fields < 0:
            raise ValueError("Invalid multipart part count")

    @property
    def max_body_bytes(self) -> int:
        return self.max_files * self.max_file_bytes + self.max_fields * self.max_field_bytes + self.overhead_bytes


def build_route_budgets(config: Any = None) -> Dict[str, UploadBudget | int]:
    """Public integration API. Config is optional and need not be AppConfig.

    The caller must also set ``app.router.route_class = BudgetedUploadRoute``
    before registering routes, for file/field budgets before spool writes.
    """
    def upload(attribute: str, mib: int, fields: int, files: int = 1) -> UploadBudget:
        return UploadBudget(int(getattr(config, attribute, mib * CHUNK_SIZE)), files, fields)

    return {
        "/auth/register": 8192,
        "/datasets/upload": upload("max_dataset_upload_bytes", 512, 8),
        "/kb/materials/upload": upload("max_kb_upload_bytes", 50, 5),
        "/media/video-upload": upload("max_video_upload_bytes", 100, 2),
        "/image-library/upload": upload("max_image_upload_bytes", 20, 2),
        "/ppt/render": upload("max_ppt_upload_bytes", 50, 0),
        "/projects/{project_id}/presentations": upload("max_ppt_upload_bytes", 50, 1),
        "/question-banks/import": upload("max_question_bank_upload_bytes", 50, 1, 4),
        "/lesson-design/import-docx": upload("max_lesson_docx_upload_bytes", 20, 1),
        "/projects/{project_id}/timeline/generate": upload("max_timeline_upload_bytes", 20, 0),
    }


class _RequestBodyTooLarge(HTTPException, MultiPartException):
    """Also a parser error so Starlette closes partial spool files on abort."""

    def __init__(self) -> None:
        HTTPException.__init__(self, 413, "请求体过大")
        self.message = "请求体过大"


class _MultipartBudgetExceeded(MultiPartException):
    pass


_SCOPE_BUDGET = "webgis.request_budget"


class BodySizeLimitMiddleware:
    """Bound actual received bytes for every media type before deserialization.

    ``max_json_body_bytes`` remains compatible with the original constructor;
    it is now also the absolute fallback for other media types. Upload routes
    use their existing, larger capacities. ``route_budgets`` overrides defaults
    by route template and supports either UploadBudget or an integer byte cap.
    WebSocket/lifespan scopes are deliberately unchanged.
    """

    def __init__(self, app: Any, max_json_body_bytes: int | None = None, *,
                 config: Any = None, route_budgets: Dict[str, UploadBudget | int] | None = None) -> None:
        self.app = app
        self.max_json_body_bytes = int(max_json_body_bytes if max_json_body_bytes is not None else
                                       getattr(config, "max_json_body_bytes", 32 * CHUNK_SIZE))
        if self.max_json_body_bytes <= 0:
            raise ValueError("Request byte budget must be positive")
        budgets = build_route_budgets(config)
        budgets.update(route_budgets or {})
        self.route_budgets = []
        for path, budget in budgets.items():
            if not isinstance(budget, UploadBudget) and int(budget) <= 0:
                raise ValueError("Request byte budget must be positive")
            pattern = re.sub(r"\\\{[^{}]+\\\}", "[^/]+", re.escape(path))
            self.route_budgets.append((re.compile(pattern), budget))

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        root = scope.get("root_path", "").rstrip("/")
        if root and path.startswith(root + "/"):
            path = path[len(root):]
        # Match FastAPI's slash redirect too; a valid large upload must not be
        # rejected with the smaller fallback before it can reach that redirect.
        path = path.rstrip("/") or "/"
        budget: UploadBudget | int = self.max_json_body_bytes
        if scope.get("method") == "POST":
            for pattern, candidate in self.route_budgets:
                if pattern.fullmatch(path):
                    budget = candidate
                    break
        scope[_SCOPE_BUDGET] = budget
        limit = budget.max_body_bytes if isinstance(budget, UploadBudget) else int(budget)
        body_413 = '{"detail":"请求体过大"}'.encode("utf-8")

        async def reject() -> None:
            await send(dict(_STATUS_413))
            await send({"type": "http.response.body", "body": body_413})

        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length" and value.isdigit():
                digits = value.lstrip(b"0") or b"0"
                # Avoid Python's integer-conversion digit limit on hostile headers.
                if len(digits) > len(str(limit)) or int(digits) > limit:
                    await reject()
                    return
        received = 0
        rejected = False
        response_started = False

        async def counting_receive() -> Dict[str, Any]:
            nonlocal received, rejected
            if rejected:
                raise _RequestBodyTooLarge()
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    rejected = True
                    raise _RequestBodyTooLarge()
            return message

        async def guarded_send(message: Dict[str, Any]) -> None:
            nonlocal response_started
            if rejected:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
        if rejected and not response_started:
            # FastAPI may translate a parser error to 400; the wire budget is
            # authoritative. No synthetic body, downstream continuation or drain.
            await reject()


class _BudgetedMultiPartParser(MultiPartParser):
    """Enforce limits before writes, and close files on every failed parse.

    Starlette's parser callback API and its owned spool list are intentionally
    isolated here. The independent parser tests cover this compatibility seam.
    """

    def __init__(self, headers: Any, stream: Any, budget: UploadBudget) -> None:
        super().__init__(headers, stream, max_files=budget.max_files, max_fields=budget.max_fields)
        self.budget = budget
        self.max_part_size = budget.max_field_bytes
        self._part_bytes = 0
        self._header_bytes = 0
        self._complete = False

    def on_part_begin(self) -> None:
        super().on_part_begin()
        self._part_bytes = 0

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        self._part_bytes += end - start
        limit = self.budget.max_file_bytes if self._current_part.file is not None else self.budget.max_field_bytes
        if self._part_bytes > limit:
            raise _MultipartBudgetExceeded("上传文件或表单字段超过大小限制")
        super().on_part_data(data, start, end)

    def _count_header(self, size: int) -> None:
        self._header_bytes += size
        if self._header_bytes > self.budget.overhead_bytes:
            raise _MultipartBudgetExceeded("上传表单头部超过大小限制")

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._count_header(end - start)
        super().on_header_field(data, start, end)

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._count_header(end - start)
        super().on_header_value(data, start, end)

    def on_headers_finished(self) -> None:
        try:
            super().on_headers_finished()
        except MultiPartException as exc:
            if self._current_files > self.max_files or self._current_fields > self.max_fields:
                raise _MultipartBudgetExceeded("上传文件或表单字段数量超过限制") from exc
            raise

    def on_end(self) -> None:
        self._complete = True
        super().on_end()

    def close_files(self) -> None:
        # Synchronous close has no cancellation checkpoint. These are this
        # parser's owned spools, including a partially written current part.
        for file in self._files_to_close_on_error:
            file.close()

    async def parse(self) -> Any:
        try:
            result = await super().parse()
            if not self._complete:
                raise MultiPartException("上传表单不完整")
            return result
        except BaseException:
            # Includes disconnects/cancellation as well as parser and wire limits.
            self.close_files()
            raise


class BudgetedUploadRoute(APIRoute):
    """Install before route declarations, alongside BodySizeLimitMiddleware.

    Uses the budget selected by that middleware, so config and overrides have
    one source of truth. Original endpoint signatures/OpenAPI are unchanged.
    """

    def get_route_handler(self) -> Any:
        original = super().get_route_handler()

        async def handle(request: Any) -> Any:
            budget = request.scope.get(_SCOPE_BUDGET)
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if not isinstance(budget, UploadBudget) or content_type != "multipart/form-data":
                return await original(request)
            parser = _BudgetedMultiPartParser(request.headers, request.stream(), budget)
            try:
                form = await parser.parse()
            except _RequestBodyTooLarge:
                raise
            except _MultipartBudgetExceeded as exc:
                raise HTTPException(413, exc.message) from exc
            except MultiPartException as exc:
                raise HTTPException(400, exc.message) from exc
            except MultipartParseError as exc:
                raise HTTPException(400, "上传表单格式无效") from exc
            # FastAPI consumes Request.form(), whose cache is this same object.
            request._form = form
            try:
                return await original(request)
            finally:
                parser.close_files()

        return handle


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

    def __init__(self, max_concurrent: int, timeout: float = 120.0, max_waiting: int = 8) -> None:
        self._semaphore = threading.BoundedSemaphore(max(1, int(max_concurrent)))
        self.timeout = float(timeout)
        self.max_waiting = max(0, int(max_waiting))
        self._lock = threading.Lock()
        self._waiting = 0

    def acquire(self, timeout: float | None = None, *, cancel_event: threading.Event | None = None) -> bool:
        if cancel_event is not None and cancel_event.is_set():
            return False
        if self._semaphore.acquire(blocking=False):
            return True
        with self._lock:
            if self._waiting >= self.max_waiting:
                return False
            self._waiting += 1
        try:
            budget = self.timeout if timeout is None else timeout
            if cancel_event is None:
                return self._semaphore.acquire(timeout=budget)
            deadline = time.monotonic() + max(0.0, budget)
            while not cancel_event.is_set():
                remaining = max(0.0, deadline - time.monotonic())
                acquired = self._semaphore.acquire(timeout=min(remaining, 0.2))
                if acquired:
                    if cancel_event.is_set():
                        self._semaphore.release()
                        return False
                    return True
                if remaining <= 0:
                    return False
            return False
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

    def __init__(self, max_per_user: int, max_total: int = 32) -> None:
        self.max_per_user = max(1, int(max_per_user))
        self.max_total = max(1, int(max_total))
        self._counts: Dict[str, int] = {}
        self._lock = threading.Lock()

    def enter(self, user_key: str) -> bool:
        with self._lock:
            current = self._counts.get(user_key, 0)
            if current >= self.max_per_user or sum(self._counts.values()) >= self.max_total:
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
