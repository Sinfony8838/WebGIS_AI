"""Local, synthetic browser fixture; never imports the application's runtime.

Run with Python 3.12, then open http://127.0.0.1:18746/. The dummy cookie and
protected endpoints exist only in this fixture. No external requests are needed.
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from starlette.responses import FileResponse
from backend.app.active_content import apply_file_policy


MATERIAL = b"""<!doctype html><html><body>
<button id="interact">Draw and increment</button><output id="counter">0</output>
<canvas id="canvas" width="40" height="40"></canvas><pre id="results"></pre>
<script>
const results = {};
function publish() {
  document.querySelector('#results').textContent = JSON.stringify(results);
  parent.postMessage({kind:'qa-result',results}, '*');
}
function attempt(name, action) {
  try { action(); results[name] = 'FAIL'; } catch { results[name] = 'PASS'; }
}
attempt('cookie_isolated', () => document.cookie);
attempt('storage_isolated', () => localStorage.setItem('qa', 'value'));
if (parent !== window) attempt('parent_isolated', () => parent.document.body);
fetch('/auth/me', {credentials:'include'}).then(() => {
  results.business_fetch_blocked = 'FAIL'; publish();
}).catch(() => { results.business_fetch_blocked = 'PASS'; publish(); });
fetch('/admin/action', {method:'POST', credentials:'include'}).then(() => {
  results.admin_action_blocked = 'FAIL'; publish();
}).catch(() => { results.admin_action_blocked = 'PASS'; publish(); });
fetch('https://example.invalid/qa-probe').then(() => {
  results.external_fetch_blocked = 'FAIL'; publish();
}).catch(() => { results.external_fetch_blocked = 'PASS'; publish(); });
document.querySelector('#interact').onclick = () => {
  const canvas = document.querySelector('#canvas');
  canvas.getContext('2d').fillRect(0,0,20,20);
  document.querySelector('#counter').textContent = String(Number(document.querySelector('#counter').textContent)+1);
  results.interaction_works = canvas.getContext('2d').getImageData(0,0,1,1).data[3] === 255 ? 'PASS' : 'FAIL';
  publish();
};
addEventListener('message', e => { if (e.data === 'qa-interact') document.querySelector('#interact').click(); });
publish();
</script></body></html>"""

PARENT = b"""<!doctype html><html><head><title>Active content isolation QA</title></head><body>
<h1>Active content isolation QA</h1><p id="session">Checking synthetic administrator...</p>
<iframe id="material" title="Self-contained teaching material" sandbox="allow-scripts" src="/files/fixture.html"></iframe>
<button id="exercise">Exercise teaching interaction</button><button id="check">Check protected endpoints</button>
<pre id="results">Waiting for sandbox checks</pre><pre id="server">Waiting for endpoint counts</pre>
<a href="/files/fixture.html">Open material directly</a>
<a href="/control.html">Negative control without isolation policy</a>
<script>
const frame = document.querySelector('#material');
addEventListener('message', e => {
  if (e.source === frame.contentWindow && e.origin === 'null' && e.data.kind === 'qa-result') {
    document.querySelector('#results').textContent = JSON.stringify(e.data.results, null, 2);
  }
});
document.querySelector('#exercise').onclick = () => frame.contentWindow.postMessage('qa-interact', '*');
document.querySelector('#check').onclick = async () => {
  document.querySelector('#server').textContent = JSON.stringify(await (await fetch('/stats')).json());
};
fetch('/auth/me').then(r => r.json()).then(r => {
  document.querySelector('#session').textContent = r.role === 'admin' ? 'Synthetic administrator session active' : 'FAIL';
});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protected_reads = 0
    admin_writes = 0

    def log_message(self, *args):
        pass

    def send_body(self, data: bytes, content_type: str, policy: str | None = None):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'private, no-store')
        if policy:
            self.send_header('Content-Security-Policy', policy)
            self.send_header('X-Content-Type-Options', 'nosniff')
        if self.path == '/':
            self.send_header('Set-Cookie', 'qa_session=synthetic-admin; HttpOnly; SameSite=Lax; Path=/')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/':
            self.send_body(PARENT, 'text/html; charset=utf-8')
        elif self.path == '/files/fixture.html':
            response = apply_file_policy(FileResponse('fixture.html'), 'fixture.html')
            self.send_body(MATERIAL, response.headers['content-type'], response.headers['content-security-policy'])
        elif self.path == '/control.html':
            # This deliberately unsafe local synthetic control makes the same
            # browser checks fail when the response policy is absent.
            self.send_body(MATERIAL, 'text/html; charset=utf-8')
        elif self.path == '/auth/me':
            type(self).protected_reads += 1
            self.send_body(b'{"role":"admin","csrf_token":"synthetic-only"}', 'application/json')
        elif self.path == '/stats':
            self.send_body(json.dumps({'protected_reads':self.protected_reads,'admin_writes':self.admin_writes}).encode(), 'application/json')
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != '/admin/action':
            self.send_error(404)
            return
        type(self).admin_writes += 1
        self.send_body(b'{"status":"synthetic-only"}', 'application/json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18746)
    args = parser.parse_args()
    print(f'Synthetic browser QA on http://127.0.0.1:{args.port}/', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
