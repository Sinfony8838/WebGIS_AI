"""Keep authenticated file responses out of browser and shared CDN caches."""
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class PrivateFileCacheMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == "/files" or path.startswith("/files/")):
            await self.app(scope, receive, send)
            return

        async def send_private(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                # Include denials and partial/conditional responses: neither a
                # successful login nor an error may seed a shared cache entry.
                headers["Cache-Control"] = "private, no-store, max-age=0"
                headers["CDN-Cache-Control"] = "no-store"
                headers["Cloudflare-CDN-Cache-Control"] = "no-store"
                headers.add_vary_header("Cookie, Authorization")
            await send(message)

        await self.app(scope, receive, send_private)
