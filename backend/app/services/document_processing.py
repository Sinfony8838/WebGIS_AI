"""Shared process budget for every application document parsing entry point."""
from threading import Lock
from .document_executor import DocumentExecutor
from .blocking_work import request_cancel

_lock = Lock()
_executor = DocumentExecutor()

def startup():
    """Install a lifespan-owned pool, preserving the lazy direct-call facility."""
    global _executor
    with _lock:
        previous = _executor
        _executor = DocumentExecutor()
        return previous

def restore(previous):
    global _executor
    with _lock:
        _executor = previous

async def aclose():
    import asyncio
    status = _executor.status()
    if status["running"] or status["waiting"]:
        await asyncio.to_thread(close)
    else:
        close()

def close():
    _executor.close()

def run_document(operation, raw, **kwargs):
    kwargs.setdefault("cancel_event", request_cancel.get())
    return _executor.run(operation, raw, **kwargs)

async def arun_document(operation, raw, **kwargs):
    return await _executor.arun(operation, raw, **kwargs)
