"""A small bounded worker queue for synchronous request work.

Cancelled waiters do not release running work's capacity. A cancelled queued
future stays within the bound until the worker skips it, so repeated request
cancellation cannot accumulate an unbounded executor backlog.
"""
from __future__ import annotations

import asyncio
from collections import deque
from concurrent.futures import Future
from threading import Condition, Thread
from typing import Any, Callable


class ExecutorBusy(Exception):
    """The bounded facility is full or is shutting down."""


class BoundedExecutor:
    """One lazy worker, with an explicit limit on running plus queued work."""

    def __init__(self, *, max_queued: int = 1, name: str = "webgis-ppt-render") -> None:
        if max_queued < 0:
            raise ValueError("max_queued must be nonnegative")
        self._capacity = 1 + max_queued
        self._name = name
        self._condition = Condition()
        self._queue: deque[tuple[Future, Callable, tuple[Any, ...]]] = deque()
        self._outstanding = 0
        self._closed = False
        self._worker: Thread | None = None

    async def run(self, function: Callable, *args: Any) -> Any:
        with self._condition:
            if self._closed or self._outstanding >= self._capacity:
                raise ExecutorBusy("PPT 转换繁忙，请稍后重试")
            if self._worker is None:
                worker = Thread(target=self._work, name=self._name, daemon=False)
                worker.start()
                self._worker = worker
            future: Future = Future()
            self._queue.append((future, function, args))
            self._outstanding += 1
            self._condition.notify()
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            # Running native work remains owned by the worker. Queued work can
            # be cancelled, but retains capacity until consumed and discarded.
            future.cancel()
            raise

    def _work(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if not self._queue:
                    return
                future, function, args = self._queue.popleft()
            ran = future.set_running_or_notify_cancel()
            result = None
            failure = None
            if ran:
                try:
                    result = function(*args)
                except BaseException as exc:
                    failure = exc
            # Release only after real work has finished (or was skipped),
            # before waking a waiter which might submit its next request.
            with self._condition:
                self._outstanding -= 1
            if ran:
                if failure is None:
                    future.set_result(result)
                else:
                    future.set_exception(failure)
            # Do not retain request buffers/results while this thread waits.
            del future, function, args, result, failure

    def _begin_shutdown(self) -> Thread | None:
        with self._condition:
            self._closed = True
            for future, _, _ in self._queue:
                future.cancel()
            self._condition.notify_all()
            return self._worker

    def shutdown(self) -> None:
        """Reject new work, cancel queued work and drain the running converter."""
        worker = self._begin_shutdown()
        if worker is not None:
            worker.join()
        with self._condition:
            self._worker = None

    async def aclose(self) -> None:
        """An idle facility closes without creating a default-pool thread."""
        worker = self._begin_shutdown()
        if worker is not None:
            await asyncio.to_thread(worker.join)
        with self._condition:
            self._worker = None
