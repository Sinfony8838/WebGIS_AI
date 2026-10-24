"""Bounded background tasks with admission before persistence.

One maintenance thread expires queued tasks even while every worker is busy.
Unused reservations never create durable entities and are revoked on shutdown.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class BackgroundBusy(Exception):
    """Retryable admission rejection; no task should be created for it."""

    retry_after = 2

    def __init__(self, message: str = "后台任务繁忙，请稍后重试") -> None:
        super().__init__(message)


class TaskReservation:
    def __init__(self, pool: "BoundedTaskPool") -> None:
        self._pool = pool
        self._state = "reserved"
        self._function: Callable[..., Any] | None = None
        self._args: tuple[Any, ...] = ()
        self._on_expire: Callable[[], Any] | None = None
        self._deadline: float | None = None

    def __enter__(self) -> "TaskReservation":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.release()

    def release(self) -> None:
        """Return unused admission, never release queued/running work early."""
        with self._pool._lock:
            if self._state == "reserved":
                self._pool._finish(self)

    def submit(self, function: Callable[..., Any], *args: Any,
               on_expire: Callable[[], Any] | None = None) -> None:
        self._pool._submit(self, function, args, on_expire)

    def cancel(self, cleanup: Callable[[], Any]) -> bool:
        """Remove a queued task and retain its slot through terminal cleanup."""
        with self._pool._lock:
            if self._state != "queued":
                return False
            self._pool._queue.remove(self)
            self._state = "running"
            self._pool._condition.notify_all()
        try:
            cleanup()
        finally:
            with self._pool._lock:
                self._pool._finish(self)
        return True


class BoundedTaskPool:
    def __init__(self, *, max_workers: int = 2, max_queued: int = 8,
                 queue_timeout: float = 120.0, name: str = "webgis-background") -> None:
        if max_workers < 1 or max_queued < 0 or queue_timeout <= 0:
            raise ValueError("invalid background task limits")
        self.max_workers = int(max_workers)
        self.max_queued = int(max_queued)
        self.queue_timeout = float(queue_timeout)
        self._name = name
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._queue: deque[TaskReservation] = deque()
        self._threads: set[threading.Thread] = set()
        self._monitor: threading.Thread | None = None
        self._reservations: set[TaskReservation] = set()
        self._outstanding = 0
        self._closed = False

    def reserve(self) -> TaskReservation:
        with self._lock:
            if self._closed or self._outstanding >= self.max_workers + self.max_queued:
                raise BackgroundBusy()
            reservation = TaskReservation(self)
            self._reservations.add(reservation)
            self._outstanding += 1
            return reservation

    def validate(self, reservation: TaskReservation) -> None:
        with self._lock:
            if self._closed:
                raise BackgroundBusy()
            if reservation._pool is not self or reservation._state != "reserved":
                raise ValueError("reservation is not available for this task pool")

    @contextmanager
    def preparing(self, reservation: TaskReservation):
        """Keep admitted persistence alive through shutdown without holding the queue lock."""
        with self._lock:
            self.validate(reservation)
            reservation._state = "preparing"
        try:
            yield
        finally:
            with self._lock:
                if reservation._state == "preparing":
                    self._finish(reservation)

    def _submit(self, reservation: TaskReservation, function: Callable[..., Any],
                args: tuple[Any, ...], on_expire: Callable[[], Any] | None) -> None:
        with self._lock:
            # Work already preparing is accepted and must finish even if shutdown
            # closed new admissions while persistence was in progress.
            if reservation._pool is not self or reservation._state != "preparing":
                self.validate(reservation)
            # Start before enqueue. Failed starts leave no orphaned queue item.
            if len(self._threads) < self.max_workers:
                thread = threading.Thread(target=self._work, name=self._name, daemon=True)
                self._threads.add(thread)
                try:
                    thread.start()
                except BaseException:
                    self._threads.discard(thread)
                    raise
            if self._monitor is None:
                monitor = threading.Thread(target=self._expire_queued, name=f"{self._name}-expiry", daemon=True)
                self._monitor = monitor
                try:
                    monitor.start()
                except BaseException:
                    self._monitor = None
                    raise
            reservation._function = function
            reservation._args = args
            reservation._on_expire = on_expire
            reservation._deadline = time.monotonic() + self.queue_timeout
            reservation._state = "queued"
            self._queue.append(reservation)
            self._condition.notify_all()

    def _finish(self, reservation: TaskReservation) -> None:
        reservation._state = "finished"
        reservation._function = None
        reservation._args = ()
        reservation._on_expire = None
        self._reservations.remove(reservation)
        self._outstanding -= 1
        self._condition.notify_all()

    def _invoke(self, reservation: TaskReservation, *, expired: bool) -> None:
        try:
            if expired and reservation._on_expire is not None:
                reservation._on_expire()
            elif not expired:
                reservation._function(*reservation._args)
        except BaseException:
            logger.exception("background task failed in %s", self._name)
        finally:
            with self._lock:
                self._finish(reservation)

    def _work(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._threads.discard(threading.current_thread())
                    return
                reservation = self._queue.popleft()
                reservation._state = "running"
                expired = time.monotonic() >= reservation._deadline
                self._condition.notify_all()
            self._invoke(reservation, expired=expired)
            del reservation

    def _expire_queued(self) -> None:
        while True:
            with self._condition:
                if not self._queue:
                    self._monitor = None
                    return
                reservation = self._queue[0]
                remaining = reservation._deadline - time.monotonic()
                if remaining > 0:
                    self._condition.wait(timeout=remaining)
                    continue
                self._queue.popleft()
                reservation._state = "running"
            # Only bounded terminal cleanup runs here, never the queued workload.
            self._invoke(reservation, expired=True)
            del reservation

    @property
    def outstanding(self) -> int:
        with self._lock:
            return self._outstanding

    @property
    def queued(self) -> int:
        with self._lock:
            return len(self._queue)

    def startup(self) -> None:
        """Reopen a fully drained pool for a new application lifespan."""
        with self._lock:
            if not self._closed:
                return
            if self._outstanding:
                raise RuntimeError("cannot reopen a background pool before it drains")
            self._closed = False

    def shutdown(self, *, wait: bool = True) -> None:
        """Revoke unused tokens and drain accepted work before storage closes."""
        with self._lock:
            self._closed = True
            for reservation in list(self._reservations):
                if reservation._state == "reserved":
                    self._finish(reservation)
            threads = list(self._threads)
            if self._monitor is not None:
                threads.append(self._monitor)
            self._condition.notify_all()
        if wait:
            for thread in threads:
                if thread is not threading.current_thread():
                    thread.join()
            # Queued cancellation can run terminal cleanup on a request thread.
            with self._condition:
                while self._outstanding and threading.current_thread() not in threads:
                    self._condition.wait()
