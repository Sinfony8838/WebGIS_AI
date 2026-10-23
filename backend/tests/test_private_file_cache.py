import unittest

from starlette.datastructures import Headers

from backend.app.private_file_cache import PrivateFileCacheMiddleware


class PrivateFileCacheTest(unittest.IsolatedAsyncioTestCase):
    async def response(self, path, status=200, scope_type="http"):
        messages = []

        async def endpoint(scope, receive, send):
            await send({"type": "http.response.start", "status": status, "headers": [
                (b"cache-control", b"public, max-age=3600"),
                (b"vary", b"Origin, Accept-Encoding"),
                (b"content-range", b"bytes 0-3/10"),
            ]})
            await send({"type": "http.response.body", "body": b"0123"})

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            messages.append(message)

        await PrivateFileCacheMiddleware(endpoint)({"type": scope_type, "path": path}, receive, send)
        return messages

    async def test_file_success_denial_and_conditional_responses_are_not_cacheable(self):
        for status in (200, 206, 304, 401, 403, 404):
            with self.subTest(status=status):
                messages = await self.response("/files/outputs/project_fixture/map.png", status)
                headers = Headers(raw=messages[0]["headers"])
                self.assertEqual(messages[0]["status"], status)
                self.assertEqual(messages[1]["body"], b"0123")
                self.assertEqual(headers["cache-control"], "private, no-store, max-age=0")
                self.assertEqual(headers["cdn-cache-control"], "no-store")
                self.assertEqual(headers["cloudflare-cdn-cache-control"], "no-store")
                self.assertEqual(headers["content-range"], "bytes 0-3/10")
                self.assertEqual(set(headers["vary"].replace(" ", "").split(",")),
                                 {"Origin", "Accept-Encoding", "Cookie", "Authorization"})

    async def test_file_root_is_protected(self):
        messages = await self.response("/files", 307)
        self.assertIn("no-store", Headers(raw=messages[0]["headers"])["cache-control"])

    async def test_workflow_files_success_denial_and_partial_responses_are_private(self):
        for path in ("/workflow-files", "/workflow-files/workflow_fixture/map.svg"):
            for status in (200, 206, 304, 401, 403, 404):
                with self.subTest(path=path, status=status):
                    messages = await self.response(path, status)
                    headers = Headers(raw=messages[0]["headers"])
                    self.assertEqual(headers["cache-control"], "private, no-store, max-age=0")
                    self.assertEqual(headers["cloudflare-cdn-cache-control"], "no-store")
                    self.assertEqual(headers["content-range"], "bytes 0-3/10")
                    self.assertIn("Cookie", headers["vary"])

    async def test_other_routes_and_non_http_scopes_keep_their_cache_policy(self):
        for path, scope_type in (("/assets/index.js", "http"), ("/tiles/weather/x.png", "http"),
                                 ("/files-extra/map.png", "http"), ("/workflow-files-extra/map.png", "http"),
                                 ("/files/x", "websocket"), ("/workflow-files/x/map.svg", "websocket")):
            with self.subTest(path=path, scope_type=scope_type):
                messages = await self.response(path, scope_type=scope_type)
                headers = Headers(raw=messages[0]["headers"])
                self.assertEqual(headers["cache-control"], "public, max-age=3600")
                self.assertEqual(headers["vary"], "Origin, Accept-Encoding")
                self.assertNotIn("cdn-cache-control", headers)
