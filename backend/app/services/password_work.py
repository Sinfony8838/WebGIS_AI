"""Bounded password work and a separate channel for small session reads."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Condition, Lock
from typing import Any, Callable


class WorkBusy(Exception):
    pass


class PasswordWork:
    """Run on synchronous callers' threads, with no persistent worker threads.

    Waiting callers count against capacity until they really leave. Cancelling
    an HTTP waiter therefore cannot free a slot while its hash still runs.
    No database or service lock may be held when calling ``run``.
    """

    def __init__(self, workers: int = 2, max_waiting: int = 8) -> None:
        if workers < 1 or max_waiting < 0:
            raise ValueError("Invalid password work capacity")
        self.workers = workers
        self.capacity = workers + max_waiting
        self._condition = Condition()
        self._running = 0
        self._outstanding = 0

    def run(self, function: Callable, *args: Any) -> Any:
        with self._condition:
            if self._outstanding >= self.capacity:
                raise WorkBusy()
            self._outstanding += 1
            try:
                while self._running >= self.workers:
                    self._condition.wait()
                self._running += 1
            except BaseException:
                self._outstanding -= 1
                self._condition.notify_all()
                raise
        try:
            return function(*args)
        finally:
            with self._condition:
                self._running -= 1
                self._outstanding -= 1
                self._condition.notify_all()


# All services in one process share the expensive-work budget, including
# bootstrap, registration and password administration.
PASSWORD_WORK = PasswordWork()


class SessionReadPool:
    """Bound submissions before enqueueing; never share password-work slots."""

    def __init__(self, workers: int = 4, max_waiting: int = 32) -> None:
        self._slots = BoundedSemaphore(workers + max_waiting)
        self._lock = Lock()
        self._closed = False
        # ThreadPoolExecutor starts threads lazily, so synchronous-only callers
        # and legacy service fixtures do not acquire persistent threads.
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="webgis-auth-read")

    async def run(self, function: Callable, *args: Any) -> Any:
        with self._lock:
            if self._closed or not self._slots.acquire(blocking=False):
                raise WorkBusy()
            try:
                future = self._executor.submit(function, *args)
            except BaseException:
                self._slots.release()
                raise
        future.add_done_callback(lambda _: self._slots.release())
        waiter = asyncio.wrap_future(future)
        # A cancelled caller must not cancel queued work and prematurely free
        # admission, leaving unlimited cancelled items in the executor queue.
        waiter.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(waiter)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)
