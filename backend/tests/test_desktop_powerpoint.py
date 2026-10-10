import http.client
import json
import threading
import time

import pytest

from backend.app.desktop_powerpoint import DesktopActions, DesktopServer, SERVICE

ORIGIN = "https://webgisai.com"


@pytest.fixture
def connector():
    calls = []
    def runner(action, path):
        calls.append((action, path))
        return {"status": "opened" if action == "open" else "focused",
                "file_name": "验收课件.pptx", "selected_path": "C:/private/验收课件.pptx", "foreground": True}
    actions = DesktopActions(runner)
    server = DesktopServer(0, (ORIGIN,), actions)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, calls
    server.shutdown(); server.server_close(); thread.join()


def request(server, method, path, body=None, **headers):
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    defaults = {"Origin": ORIGIN}
    defaults.update(headers)
    if body is not None:
        defaults.setdefault("Content-Type", "application/json")
    client.request(method, path, body, defaults)
    response = client.getresponse()
    raw = response.read()
    result = (response.status, dict(response.getheaders()), json.loads(raw) if raw else {})
    client.close()
    return result


def wait_result(actions, key):
    for _ in range(100):
        result = actions.get(key)
        if result["status"] != "pending":
            return result
        time.sleep(.01)
    pytest.fail("Native test action did not finish")


def test_open_then_focus_reuses_private_path_without_returning_it(connector):
    server, calls = connector
    status, headers, connection = request(server, "GET", "/connection")
    assert status == 200 and connection["service"] == SERVICE
    assert headers["Access-Control-Allow-Origin"] == ORIGIN
    assert headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Credentials" not in headers
    assert calls == []
    for action in ("open", "focus"):
        status, _, accepted = request(server, "POST", "/actions", json.dumps({"action": action}),
                                     **{"X-WebGIS-Desktop": connection["token"]})
        assert status == 202
        result = wait_result(server.actions, accepted["action_id"])
        status, _, actual = request(server, "GET", f"/actions/{accepted['action_id']}",
                                    **{"X-WebGIS-Desktop": connection["token"]})
        assert status == 200 and actual == result
        assert "selected_path" not in actual and "private" not in json.dumps(actual)
    assert calls == [("open", ""), ("focus", "C:/private/验收课件.pptx")]


@pytest.mark.parametrize("headers", [
    {"Origin": "https://attacker.example"}, {"Origin": "null"}, {"Origin": ""},
    {"Host": "attacker.example"}, {"X-Forwarded-For": "127.0.0.1"}, {"Forwarded": "for=127.0.0.1"},
    {"CF-Connecting-IP": "127.0.0.1"},
])
def test_rejects_foreign_origins_rebinding_and_proxy_requests(connector, headers):
    server, calls = connector
    status, response_headers, result = request(server, "GET", "/connection", **headers)
    assert status == 403 and "token" not in result
    assert "Access-Control-Allow-Origin" not in response_headers
    assert calls == []


@pytest.mark.parametrize("body", [
    '{"action":"open","path":"C:/secret.pptx"}', '{"action":"open","file":"abc"}',
    '{"action":"shutdown"}', '{"action":[]}', 'null', '["open"]', 'x' * 257,
])
def test_rejects_paths_uploads_and_unknown_operations(connector, body):
    server, calls = connector
    status, _, _ = request(server, "POST", "/actions", body, **{"X-WebGIS-Desktop": server.actions.token})
    assert status == 400 and calls == []


def test_requires_local_nonce_for_actions_and_results(connector):
    server, calls = connector
    assert request(server, "POST", "/actions", '{"action":"open"}')[0] == 403
    assert request(server, "GET", "/actions/nonexistent")[0] == 403
    assert calls == []


def test_native_operation_is_serialized_and_failure_releases_slot():
    entered, release = threading.Event(), threading.Event()
    def runner(*_):
        entered.set(); release.wait(2)
        raise RuntimeError("private C:/secret/filename.pptx")
    actions = DesktopActions(runner)
    key = actions.start("open")
    assert entered.wait(1)
    with pytest.raises(RuntimeError):
        actions.start("focus")
    release.set()
    result = wait_result(actions, key)
    assert result["status"] == "failed" and "secret" not in result["message"]
    second = actions.start("focus")
    assert wait_result(actions, second)["status"] == "failed"


def test_cancel_does_not_replace_the_last_selected_presentation():
    actions = DesktopActions(lambda *_: {"status": "cancelled"})
    actions.selected_path = "C:/existing.pptx"
    assert wait_result(actions, actions.start("open")) == {"status": "cancelled"}
    assert actions.selected_path == "C:/existing.pptx"
