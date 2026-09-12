#!/usr/bin/env node
/**
 * 浏览器语音验收 CDP 驱动（无外部依赖，Node >= 18）。
 *
 * 用法：node scripts/acceptance_browser_cdp.js <命令> [参数]
 * 前提：Chrome 以 --remote-debugging-port=9223 启动并打开 5176 页面
 * （假麦克风 + 假权限旗标由启动方提供）。命令：
 *   enter [timeoutS]              前置页面、开启焦点仿真、进入智能交互、等待聆听
 *   status                        输出当前页面状态 JSON
 *   waitExec [timeoutS]           等待出现执行迹象（已识别/正在执行/正在播报）
 *   waitListening [timeoutS]      等待回到正在聆听
 *   waitStatus <子串> [timeoutS]  等待状态行包含子串
 *   mic                           点击麦克风（暂停/恢复）
 *   tts                           点击回复播报开关，输出新标签
 *   retry                         点击识别不可用的重试按钮
 */
const http = require("node:http");
const net = require("node:net");
const crypto = require("node:crypto");

const CDP_PORT = process.env.WEBGIS_CDP_PORT || 9223;

function getJson(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => {
      let d = "";
      r.on("data", (c) => (d += c));
      r.on("end", () => res(JSON.parse(d)));
    }).on("error", rej);
  });
}

class MiniWS {
  constructor(socket) {
    this.sock = socket;
    this.buf = Buffer.alloc(0);
    this.onmessage = null;
    socket.on("data", (c) => this._feed(c));
    socket.on("error", () => {});
  }
  _feed(chunk) {
    this.buf = Buffer.concat([this.buf, chunk]);
    for (;;) {
      if (this.buf.length < 2) return;
      const len0 = this.buf[1] & 0x7f;
      let offset = 2;
      let len = len0;
      if (len0 === 126) {
        if (this.buf.length < 4) return;
        len = this.buf.readUInt16BE(2);
        offset = 4;
      } else if (len0 === 127) {
        if (this.buf.length < 10) return;
        len = Number(this.buf.readBigUInt64BE(2));
        offset = 10;
      }
      if (this.buf.length < offset + len) return;
      const payload = this.buf.subarray(offset, offset + len);
      this.buf = this.buf.subarray(offset + len);
      this.onmessage?.(payload.toString("utf8"));
    }
  }
  send(text) {
    const data = Buffer.from(text, "utf8");
    const mask = crypto.randomBytes(4);
    let header;
    if (data.length < 126) header = Buffer.from([0x81, 0x80 | data.length]);
    else if (data.length < 65536) {
      header = Buffer.alloc(4);
      header[0] = 0x81;
      header[1] = 0x80 | 126;
      header.writeUInt16BE(data.length, 2);
    } else {
      header = Buffer.alloc(10);
      header[0] = 0x81;
      header[1] = 0x80 | 127;
      header.writeBigUInt64BE(BigInt(data.length), 2);
    }
    const masked = Buffer.alloc(data.length);
    for (let i = 0; i < data.length; i++) masked[i] = data[i] ^ mask[i % 4];
    this.sock.write(Buffer.concat([header, mask, masked]));
  }
  close() {
    try { this.sock.end(); } catch { /* already closed */ }
  }
}

function wsConnect(url) {
  return new Promise((res, rej) => {
    const u = new URL(url);
    const key = crypto.randomBytes(16).toString("base64");
    const sock = net.connect(Number(u.port), u.hostname, () => {
      sock.write(
        `GET ${u.pathname}${u.search} HTTP/1.1\r\nHost: ${u.host}\r\nUpgrade: websocket\r\n` +
        `Connection: Upgrade\r\nSec-WebSocket-Key: ${key}\r\nSec-WebSocket-Version: 13\r\n\r\n`
      );
    });
    let hs = Buffer.alloc(0);
    const onHs = (chunk) => {
      hs = Buffer.concat([hs, chunk]);
      const idx = hs.indexOf("\r\n\r\n");
      if (idx === -1) return;
      const head = hs.subarray(0, idx).toString("utf8");
      if (!/ 101 /.test(head)) {
        rej(new Error("websocket handshake failed"));
        return;
      }
      sock.removeListener("data", onHs);
      const ws = new MiniWS(sock);
      const rest = hs.subarray(idx + 4);
      if (rest.length) ws._feed(rest);
      res(ws);
    };
    sock.on("data", onHs);
    sock.on("error", rej);
  });
}

let seq = 0;
async function withPage(fn) {
  const targets = await getJson(`http://127.0.0.1:${CDP_PORT}/json`);
  const page = targets.find((t) => t.type === "page" && t.url.includes("5176"));
  if (!page) throw new Error("no 5176 page target");
  const ws = await wsConnect(page.webSocketDebuggerUrl);
  try {
    return await fn(ws);
  } finally {
    ws.close();
  }
}

async function cmd(ws, method, params = {}) {
  const id = ++seq;
  const out = await new Promise((res, rej) => {
    ws.onmessage = (p) => {
      const m = JSON.parse(p.toString("utf8"));
      if (m.id === id) res(m);
    };
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => rej(new Error(`cmd timeout: ${method}`)), 20000);
  });
  if (out.error) throw new Error(`${method}: ${JSON.stringify(out.error)}`);
  return out.result;
}

async function evalNow(ws, expr) {
  const r = await cmd(ws, "Runtime.evaluate", { expression: expr, awaitPromise: false, returnByValue: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 400));
  return r.result?.value;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function readState(ws) {
  return evalNow(
    ws,
    `(() => {
      const btn = Array.from(document.querySelectorAll("button")).find((b) => /(切换\s*(2D|3D))|(切换到\s*(2D|3D))/.test(b.textContent || ""));
      return {
        viewBtn: btn ? btn.textContent.trim() : "(none)",
        status: document.querySelector('[data-testid="copilot-voice-status"]')?.textContent || "",
        mic: document.querySelector('[data-testid="copilot-mic-button"]')?.getAttribute("aria-label") || "",
        tts: document.querySelector('[data-testid="copilot-tts-toggle"]')?.textContent.trim() || "",
        partial: document.querySelector('[data-testid="copilot-voice-partial"]')?.textContent || "",
        focus: document.hasFocus()
      };
    })()`
  );
}

async function main() {
  const [command, arg1, arg2] = process.argv.slice(2);
  if (!command) {
    console.log("usage: acceptance_browser_cdp.js <enter|status|waitExec|waitListening|waitStatus|mic|tts|retry> [args]");
    process.exit(2);
  }

  if (command === "enter") {
    const timeoutS = Number(arg1 || 40);
    const waitStatusLocal = async (needle, timeoutSec) => {
      const deadline2 = Date.now() + timeoutSec * 1000;
      let last = null;
      while (Date.now() < deadline2) {
        last = await withPage(readState);
        if (last.status.includes(needle)) return last;
        await sleep(800);
      }
      throw new Error(`waitStatus "${needle}" timeout, last=${JSON.stringify(last)}`);
    };
    await withPage(async (ws) => {
      await cmd(ws, "Emulation.setFocusEmulationEnabled", { enabled: true });
      await cmd(ws, "Page.bringToFront");
    });
    await sleep(1200);
    const deadline = Date.now() + timeoutS * 1000;
    let ready = false;
    while (Date.now() < deadline) {
      ready = await withPage(async (ws) =>
        evalNow(ws, `!!(document.querySelector('[aria-label="展开智能助教"]') || document.querySelector('[data-testid="copilot-tab-interaction"]'))`)
      );
      if (ready) break;
      await sleep(800);
    }
    if (!ready) throw new Error("assistant widget not found");
    await withPage(async (ws) => {
      await evalNow(ws, `(() => { const o = document.querySelector('[aria-label="展开智能助教"]'); if (o) o.click(); return 1; })()`);
    });
    await sleep(600);
    await withPage(async (ws) => {
      await evalNow(ws, `(() => { const t = document.querySelector('[data-testid="copilot-tab-interaction"]'); if (!t) throw new Error("no interaction tab"); t.click(); return 1; })()`);
    });
    await sleep(800);
    const listening = await waitStatusLocal("正在聆听", timeoutS);
    console.log(JSON.stringify({ ok: true, listening }, null, 2));
    return;
  }

  if (command === "status") {
    console.log(JSON.stringify(await withPage(readState), null, 2));
    return;
  }

  if (command === "mic" || command === "tts" || command === "retry") {
    const sel =
      command === "mic"
        ? `document.querySelector('[data-testid="copilot-mic-button"]').click(); 1`
        : command === "tts"
          ? `(() => { const b = document.querySelector('[data-testid="copilot-tts-toggle"]'); b.click(); return b.textContent.trim(); })()`
          : `(() => { const b = document.querySelector('[data-testid="copilot-voice-retry"]'); if (!b) throw new Error("no retry button"); b.click(); return 1; })()`;
    const out = await withPage(async (ws) => evalNow(ws, sel));
    await sleep(500);
    console.log(JSON.stringify({ clicked: command, result: out, state: await withPage(readState) }, null, 2));
    return;
  }

  if (command === "waitExec" || command === "waitListening" || command === "waitStatus") {
    const needle = command === "waitStatus" ? arg1 : command === "waitExec" ? "已识别|正在执行|正在播报" : "正在聆听";
    const timeoutS = Number((command === "waitStatus" ? arg2 : arg1) || 45);
    const deadline = Date.now() + timeoutS * 1000;
    let last = null;
    while (Date.now() < deadline) {
      last = await withPage(readState);
      const hit = needle.split("|").some((n) => last.status.includes(n));
      if (hit) {
        console.log(JSON.stringify({ matched: true, state: last }, null, 2));
        return;
      }
      await sleep(800);
    }
    console.log(JSON.stringify({ matched: false, needle, last }, null, 2));
    process.exit(1);
  }

  throw new Error(`unknown command: ${command}`);
}

main().catch((err) => {
  console.error(String(err));
  process.exit(1);
});
