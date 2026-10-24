"""Bound request work separately from lightweight authentication reads."""
import asyncio
from contextvars import ContextVar, copy_context
from threading import Event
from .password_work import SessionReadPool

request_cancel = ContextVar("request_cancel", default=None)

class BlockingWorkPool(SessionReadPool):
    def __init__(self, workers: int = 4, max_waiting: int = 8) -> None:
        super().__init__(workers, max_waiting, name="webgis-request-work")

    async def run(self, function, *args):
        cancel = Event()
        context = copy_context()
        def invoke():
            if cancel.is_set():
                return None
            token = request_cancel.set(cancel)
            try:
                return function(*args)
            finally:
                request_cancel.reset(token)
        try:
            return await super().run(context.run, invoke)
        except asyncio.CancelledError:
            cancel.set()
            raise
