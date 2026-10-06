"""An OS-held, nonblocking lease for one runtime-state directory."""
from __future__ import annotations

import errno
import hashlib
import os
import threading
import weakref
from pathlib import Path


class StateWriterAlreadyActive(RuntimeError):
    """Another store owns this data root; startup must not proceed."""


_registry_lock = threading.RLock()
_leases: weakref.WeakSet = weakref.WeakSet()


def _after_fork_child() -> None:
    # flock belongs to the shared open-file description. Close the child's
    # inherited descriptor without LOCK_UN, which would unlock the parent.
    for lease in list(_leases):
        lease._close_handle()
    _leases.clear()
    _registry_lock.release()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_registry_lock.acquire,
        after_in_parent=_registry_lock.release,
        after_in_child=_after_fork_child,
    )


class StateWriterLease:
    def __init__(self, state_file: Path):
        self.pid = os.getpid()
        self._handle = None
        self._file = None
        # Lock the directory, not only one filename: all snapshots in this
        # root share external layer files. resolve() includes Junction aliases.
        root = state_file.parent.resolve()
        with _registry_lock:
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
                kernel.CreateMutexW.restype = wintypes.HANDLE
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle.restype = wintypes.BOOL
                digest = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()
                # Global spans service and desktop sessions. Presence of the
                # object is the lease; no thread-owned Wait/ReleaseMutex pair.
                name = f"Global\\WebGISAI_RuntimeWriter_{digest}"
                ctypes.set_last_error(0)
                handle = kernel.CreateMutexW(None, False, name)
                error = ctypes.get_last_error()
                if not handle:
                    raise ctypes.WinError(error)
                if error == 183:  # ERROR_ALREADY_EXISTS
                    kernel.CloseHandle(handle)
                    raise StateWriterAlreadyActive("Runtime state root already has an active writer")
                self._kernel = kernel
                self._handle = handle
            else:
                import fcntl

                root.mkdir(parents=True, exist_ok=True)
                stream = (root / ".runtime-writer.lock").open("a+b")
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    stream.close()
                    if exc.errno in {errno.EACCES, errno.EAGAIN}:
                        raise StateWriterAlreadyActive("Runtime state root already has an active writer") from exc
                    raise
                self._file = stream
            _leases.add(self)

    def assert_owned(self) -> None:
        if self.pid != os.getpid() or (self._handle is None and self._file is None):
            raise RuntimeError("Runtime state writer is closed or belongs to another process")

    def _close_handle(self) -> None:
        if self._handle is not None:
            self._kernel.CloseHandle(self._handle)
            self._handle = None
        if self._file is not None:
            self._file.close()
            self._file = None

    def close(self) -> None:
        with _registry_lock:
            self._close_handle()
            _leases.discard(self)
