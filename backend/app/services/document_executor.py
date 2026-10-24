"""Bounded document subprocess execution, independent of application startup.

One shared instance belongs to a backend runtime. Admission is FIFO: by default
2 executing + 8 waiting, with a 120 second deadline including queue time. Every
accepted call retains its permit until its child process tree has been killed,
its direct child reaped, and its private IPC directory removed. No late result
is accepted. Windows uses Job Objects; Linux uses RLIMIT_AS and an isolated
subreaper supervisor. The Linux memory cap applies to each process; Windows
also caps the whole job. Neither boundary is a hostile-code sandbox.
"""
from __future__ import annotations

import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Iterator, Sequence

from .document_worker import OPERATIONS, restore_result, wire_object


class DocumentBusyError(RuntimeError):
    """All executing and waiting slots are occupied; retry later."""


class DocumentTimeoutError(TimeoutError):
    """The accepted call exhausted its wall-clock budget."""


class DocumentCancelledError(RuntimeError):
    """Caller cancellation or executor shutdown."""


class DocumentMemoryError(RuntimeError):
    """The worker reported allocation failure under its OS memory cap."""


class DocumentWorkerError(RuntimeError):
    """Worker startup, crash, IPC or process-control failure."""


class DocumentResultLimitError(ValueError):
    """Input or result exceeds the bounded IPC protocol."""


class _WindowsJob:
    """No breakaway flag: descendants inherit the cap and kill-on-close job."""

    def __init__(self, memory_limit: int):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        size_t = ctypes.c_size_t

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", size_t), ("MaximumWorkingSetSize", size_t),
                        ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", size_t),
                        ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", size_t), ("JobMemoryLimit", size_t),
                        ("PeakProcessMemoryUsed", size_t), ("PeakJobMemoryUsed", size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_longlong) for name in (
                "TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")]
            _fields_ += [(name, wintypes.DWORD) for name in (
                "TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")]

        self.accounting = Accounting
        self.limits_type = ExtendedLimits
        self.process_handles = {}
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "IsProcessInJob": ([wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            getattr(kernel, name).argtypes = args
            getattr(kernel, name).restype = result
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x100 | 0x200
        limits.ProcessMemoryLimit = memory_limit
        limits.JobMemoryLimit = memory_limit
        if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process: subprocess.Popen) -> None:
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())

    def track_processes(self) -> None:
        """Retain identity-bound handles while job members are discoverable."""
        from ctypes import wintypes

        count = 8
        while True:
            class ProcessIds(self.ctypes.Structure):
                _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD),
                            ("ids", self.ctypes.c_size_t * count)]

            members = ProcessIds()
            success = self.kernel.QueryInformationJobObject(
                self.handle, 3, self.ctypes.byref(members), self.ctypes.sizeof(members), None)
            error = self.ctypes.get_last_error()
            if not success and error != 234:  # ERROR_MORE_DATA
                raise self.ctypes.WinError(error)
            if not success or members.listed < members.assigned:
                count = max(count * 2, members.assigned)
                continue
            for pid in members.ids[:members.listed]:
                if pid in self.process_handles:
                    continue
                handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
                if not handle:
                    if self.ctypes.get_last_error() == 87:  # Already exited.
                        continue
                    raise self.ctypes.WinError(self.ctypes.get_last_error())
                belongs = wintypes.BOOL()
                if not self.kernel.IsProcessInJob(handle, self.handle, self.ctypes.byref(belongs)):
                    error = self.ctypes.WinError(self.ctypes.get_last_error())
                    self.kernel.CloseHandle(handle)
                    raise error
                if belongs:
                    self.process_handles[pid] = handle
                else:  # PID was reused between enumeration and OpenProcess.
                    self.kernel.CloseHandle(handle)
            return

    def terminate_and_wait(self) -> None:
        # Stop further descendants joining before taking the final snapshot.
        # A live member already occupies the sole slot; existing members stay
        # associated when the limit is lowered below the current population.
        limits = self.limits_type()
        if not self.kernel.QueryInformationJobObject(
                self.handle, 9, self.ctypes.byref(limits), self.ctypes.sizeof(limits), None):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        limits.BasicLimitInformation.LimitFlags |= 0x8  # ACTIVE_PROCESS
        limits.BasicLimitInformation.ActiveProcessLimit = 1
        if not self.kernel.SetInformationJobObject(
                self.handle, 9, self.ctypes.byref(limits), self.ctypes.sizeof(limits)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        self.track_processes()
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        while True:
            info = self.accounting()
            if not self.kernel.QueryInformationJobObject(self.handle, 1, self.ctypes.byref(info),
                                                         self.ctypes.sizeof(info), None):
                raise self.ctypes.WinError(self.ctypes.get_last_error())
            if not info.ActiveProcesses:
                break
            time.sleep(0.01)

        # Job accounting can reach zero before a process object is signaled.
        # Wait on retained handles before admitting the next document.
        for handle in self.process_handles.values():
            if self.kernel.WaitForSingleObject(handle, 0xFFFFFFFF) != 0:
                raise self.ctypes.WinError(self.ctypes.get_last_error())

    def close(self) -> None:
        for handle in self.process_handles.values():
            self.kernel.CloseHandle(handle)
        self.process_handles.clear()
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class DocumentExecutor:
    def __init__(self, *, max_workers: int = 2, max_waiting: int = 8,
                 timeout_seconds: float = 120, memory_limit_bytes: int = 1024 ** 3,
                 max_input_bytes: int = 100 * 1024 ** 2,
                 max_result_bytes: int = 300 * 1024 ** 2,
                 temp_dir: str | Path | None = None,
                 _worker_command: Sequence[str] | None = None):
        if (max_workers < 1 or max_waiting < 0 or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0 or min(memory_limit_bytes, max_input_bytes, max_result_bytes) <= 0):
            raise ValueError("Document process budgets must be positive (waiting may be zero)")
        self.max_workers = max_workers
        self.max_waiting = max_waiting
        self.timeout_seconds = timeout_seconds
        self.memory_limit_bytes = memory_limit_bytes
        self.max_input_bytes = max_input_bytes
        self.max_result_bytes = max_result_bytes
        self.temp_dir = str(temp_dir) if temp_dir is not None else None
        # Constructor-only hook for real subprocess fixtures, never request data.
        self._worker_command = list(_worker_command or [sys.executable, "-m", "backend.app.services.document_worker"])
        self._threads = ThreadPoolExecutor(max_workers=max_workers + max_waiting,
                                           thread_name_prefix="document-call")
        self._condition = threading.Condition()
        self._queue: deque[object] = deque()
        self._running = 0
        self._admitted = 0
        self._closed = False
        self._broken = False

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {"running": self._running, "waiting": self._admitted - self._running,
                    "max_workers": self.max_workers, "max_waiting": self.max_waiting,
                    "closed": self._closed, "broken": self._broken}

    def close(self, *, wait: bool = True) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
            if wait:
                self._condition.wait_for(lambda: self._admitted == 0)
        self._threads.shutdown(wait=wait)

    def _check(self, deadline: float, cancel_event: threading.Event | None) -> None:
        if self._closed or (cancel_event is not None and cancel_event.is_set()):
            raise DocumentCancelledError("Document parsing cancelled")
        if time.monotonic() >= deadline:
            raise DocumentTimeoutError("Document parsing exceeded its time budget")

    @contextmanager
    def _slot(self, ticket: object, deadline: float,
              cancel_event: threading.Event | None) -> Iterator[None]:
        with self._condition:
            try:
                while self._running >= self.max_workers or self._queue[0] is not ticket:
                    self._check(deadline, cancel_event)
                    if self._broken:
                        raise DocumentWorkerError("Document process control is unavailable")
                    self._condition.wait(min(0.05, max(0, deadline - time.monotonic())))
                self._check(deadline, cancel_event)
                if self._broken:
                    raise DocumentWorkerError("Document process control is unavailable")
                self._running += 1
            finally:
                self._queue.remove(ticket)
                self._condition.notify_all()
        try:
            yield
        finally:
            with self._condition:
                self._running -= 1
                self._condition.notify_all()

    def _admit(self, deadline: float, cancel_event: threading.Event | None) -> object:
        with self._condition:
            self._check(deadline, cancel_event)
            if self._broken:
                raise DocumentWorkerError("Document process control is unavailable")
            if self._admitted >= self.max_workers + self.max_waiting:
                raise DocumentBusyError("Document parsing is busy; try again later")
            ticket = object()
            self._queue.append(ticket)
            self._admitted += 1
            return ticket

    def _release_admission(self, ticket: object) -> None:
        with self._condition:
            # A scheduling failure can release a call before _slot was entered.
            if ticket in self._queue:
                self._queue.remove(ticket)
            self._admitted -= 1
            self._condition.notify_all()

    def _validate(self, operation: str, raw_bytes: bytes, filename: str, kind: str) -> None:
        if operation not in OPERATIONS:
            raise ValueError("Unsupported document operation")
        if not isinstance(raw_bytes, bytes):
            raise TypeError("Document input must be bytes")
        if len(raw_bytes) > self.max_input_bytes:
            raise DocumentResultLimitError("Document input exceeds the IPC size budget")
        if not isinstance(filename, str) or not isinstance(kind, str) or len(filename) > 4096 or len(kind) > 16:
            raise ValueError("Invalid document metadata")

    def run(self, operation: str, raw_bytes: bytes, *, filename: str = "", kind: str = "",
            cancel_event: threading.Event | None = None) -> Any:
        self._validate(operation, raw_bytes, filename, kind)
        deadline = time.monotonic() + self.timeout_seconds
        ticket = self._admit(deadline, cancel_event)
        return self._run_admitted(operation, raw_bytes, filename, kind, deadline, cancel_event, ticket)

    def _run_admitted(self, operation: str, raw_bytes: bytes, filename: str, kind: str,
                      deadline: float, cancel_event: threading.Event | None, ticket: object) -> Any:
        try:
            return self._run(operation, raw_bytes, filename, kind, deadline, cancel_event, ticket)
        finally:
            self._release_admission(ticket)

    def _run(self, operation: str, raw_bytes: bytes, filename: str, kind: str,
             deadline: float, cancel_event: threading.Event | None, ticket: object) -> Any:
        with self._slot(ticket, deadline, cancel_event):
            temporary = tempfile.TemporaryDirectory(prefix="webgis-document-", dir=self.temp_dir)
            try:
                directory = Path(temporary.name)
                (directory / "input.bin").write_bytes(raw_bytes)
                (directory / "request.json").write_text(json.dumps({
                    "operation": operation, "filename": filename, "kind": kind,
                }, ensure_ascii=False), encoding="utf-8")
                self._check(deadline, cancel_event)
                response = self._execute(directory, deadline, cancel_event)
                self._check(deadline, cancel_event)
                value = self._result(operation, response)
            finally:
                try:
                    temporary.cleanup()
                except Exception as exc:
                    with self._condition:
                        self._broken = True
                        self._condition.notify_all()
                    raise DocumentWorkerError("Document IPC cleanup failed; executor disabled") from exc
            self._check(deadline, cancel_event)
            return value

    async def arun(self, operation: str, raw_bytes: bytes, *, filename: str = "", kind: str = "") -> Any:
        self._validate(operation, raw_bytes, filename, kind)
        cancel = threading.Event()
        deadline = time.monotonic() + self.timeout_seconds
        # Reserve before scheduling: the default thread pool's own queue must
        # never become an unbounded second document admission queue.
        ticket = self._admit(deadline, cancel)
        try:
            task = asyncio.get_running_loop().run_in_executor(
                self._threads, self._run_admitted, operation, raw_bytes,
                filename, kind, deadline, cancel, ticket)
        except BaseException:
            self._release_admission(ticket)
            raise
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel.set()
            # Multiple caller cancellations must not detach cleanup from the call.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if task.done() and not task.cancelled():
                task.exception()
            raise

    def _execute(self, directory: Path, deadline: float, cancel: threading.Event | None) -> dict:
        root = Path(__file__).resolve().parents[3]
        allowed_env = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}
        env = {key: value for key, value in os.environ.items() if key.upper() in allowed_env}
        env.update(PYTHONPATH=str(root), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                   TEMP=str(directory), TMP=str(directory), TMPDIR=str(directory))
        process = None
        job = None
        assigned = False
        try:
            if os.name == "nt":
                job = _WindowsJob(self.memory_limit_bytes)
            elif not sys.platform.startswith("linux"):
                raise DocumentWorkerError("Document process isolation is unavailable on this platform")
            command = self._worker_command + [str(directory), str(self.memory_limit_bytes),
                                               str(self.max_result_bytes), str(self.max_input_bytes)]
            process = subprocess.Popen(command, cwd=directory, env=env, stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                                       start_new_session=os.name == "posix",
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if job is not None:
                job.assign(process)
                assigned = True
            self._check(deadline, cancel)
            process.stdin.write(b"G")
            process.stdin.close()
            while process.poll() is None:
                if job is not None:
                    job.track_processes()
                self._check(deadline, cancel)
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
            self._check(deadline, cancel)
            if process.returncode:
                raise DocumentWorkerError(f"Document worker exited unexpectedly ({process.returncode})")
        except (DocumentCancelledError, DocumentTimeoutError, DocumentWorkerError):
            raise
        except (OSError, ValueError) as exc:
            raise DocumentWorkerError("Document worker could not start safely") from exc
        finally:
            try:
                if process is not None:
                    if job is not None and assigned:
                        job.terminate_and_wait()
                    elif sys.platform.startswith("linux"):
                        if process.stdin and not process.stdin.closed:
                            process.stdin.close()
                        if process.poll() is None:
                            # The trusted supervisor kills its parser group and
                            # reaps adopted grandchildren before it exits.
                            process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            # A broken supervisor disables all future admission.
                            # Still attempt to terminate its known parser group.
                            group_file = directory / "parser-group.pid"
                            if group_file.exists():
                                try:
                                    os.killpg(int(group_file.read_text()), signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                            process.kill()
                            process.wait()
                            raise DocumentWorkerError("Linux document supervisor failed to reap its children")
                        group_file = directory / "parser-group.pid"
                        if group_file.exists() and not (directory / "process-tree-reaped").exists():
                            # An externally killed supervisor cannot attest that
                            # its adopted children were reaped. Stop admission.
                            try:
                                os.killpg(int(group_file.read_text()), signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            raise DocumentWorkerError("Linux document supervisor exited before reaping its children")
                    elif process.poll() is None:
                        process.kill()
                    process.wait()
                    if process.stdin and not process.stdin.closed:
                        process.stdin.close()
            except Exception as exc:
                # A process-control failure is never followed by more admission.
                with self._condition:
                    self._broken = True
                    self._condition.notify_all()
                raise DocumentWorkerError("Document process cleanup failed; executor disabled") from exc
            finally:
                if job is not None:
                    job.close()
        self._check(deadline, cancel)
        result_path = directory / "result.json"
        try:
            if result_path.stat().st_size > self.max_result_bytes:
                raise DocumentResultLimitError("Document result exceeds the IPC size budget")
            with result_path.open("r", encoding="utf-8") as source:
                response = json.load(source, object_hook=wire_object)
            if not isinstance(response, dict) or type(response.get("ok")) is not bool:
                raise ValueError("Invalid worker response")
            return response
        except DocumentResultLimitError:
            raise
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            raise DocumentWorkerError("Document worker returned an invalid result") from exc

    @staticmethod
    def _result(operation: str, response: dict) -> Any:
        if response["ok"]:
            try:
                return restore_result(operation, response["value"])
            except (KeyError, TypeError, ValueError) as exc:
                raise DocumentWorkerError("Document worker returned an invalid result schema") from exc
        from .archive_safety import ArchiveLimitError, ArchiveValidationError
        from .question_bank_parser import DocxBudgetError, DocxValidationError
        errors = {"memory": DocumentMemoryError, "docx_budget": DocxBudgetError,
                  "docx_validation": DocxValidationError, "archive_limit": ArchiveLimitError,
                  "archive_validation": ArchiveValidationError,
                  "result_limit": DocumentResultLimitError, "validation": ValueError}
        error_type = errors.get(response.get("error"), DocumentWorkerError)
        raise error_type(str(response.get("message") or "Document parser failed")[:2000])
