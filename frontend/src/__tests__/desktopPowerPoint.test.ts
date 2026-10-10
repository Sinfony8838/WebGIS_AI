import { afterEach, expect, it, vi } from "vitest";
import { openDesktopPowerPoint } from "../lib/desktopPowerPoint";
afterEach(() => vi.unstubAllGlobals());
const reply = (data: unknown, ok = true) => ({ ok, json: async () => data });

it("uses only loopback, omits credentials and sends no PPT bytes or paths", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(reply({ service: "webgis-desktop-powerpoint", protocol: 1, token: "local-nonce" }))
    .mockResolvedValueOnce(reply({ action_id: "a".repeat(32) }))
    .mockResolvedValueOnce(reply({ status: "focused", foreground: true }));
  vi.stubGlobal("fetch", fetch);
  expect(await openDesktopPowerPoint("focus")).toEqual({ status: "focused", foreground: true });
  expect(fetch.mock.calls.every(([url, init]) => url.startsWith("http://127.0.0.1:18998/") && init.credentials === "omit")).toBe(true);
  expect(fetch.mock.calls[1][1].body).toBe('{"action":"focus"}');
  expect(fetch.mock.calls[1][1].headers).toEqual({ "Content-Type": "application/json", "X-WebGIS-Desktop": "local-nonce" });
});

it("refuses another service on the same port before sending an action", async () => {
  const fetch = vi.fn().mockResolvedValue(reply({ service: "other", protocol: 1, token: "nonce" }));
  vi.stubGlobal("fetch", fetch);
  await expect(openDesktopPowerPoint("open")).rejects.toThrow("版本不匹配");
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("does not repeat an action after transport failure", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(reply({ service: "webgis-desktop-powerpoint", protocol: 1, token: "nonce" }))
    .mockRejectedValueOnce(new Error("response lost"));
  vi.stubGlobal("fetch", fetch);
  await expect(openDesktopPowerPoint("open")).rejects.toThrow("操作可能已经开始");
  expect(fetch).toHaveBeenCalledTimes(2);
});
