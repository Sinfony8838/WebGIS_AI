import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { SessionManager } from "../src/session.js";

describe("SessionManager", () => {
  it("persists messages once and updates the session index", async () => {
    const dir = await mkdtemp(join(tmpdir(), "webgis-agent-session-"));
    const manager = new SessionManager(dir);

    try {
      await manager.init();
      const id = await manager.createSession("D:/workspace");

      await manager.saveMessage({ role: "user", content: "hello" });
      await manager.saveMessage({ role: "assistant", content: "hi" });

      const loaded = await manager.loadSession(id);
      expect(loaded).toHaveLength(2);
      expect(loaded[0]).toEqual({ role: "user", content: "hello" });

      const sessions = await manager.listSessions();
      expect(sessions[0]).toMatchObject({
        id,
        message_count: 2,
        first_message: "hello",
      });
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  it("rejects unsafe session ids", async () => {
    const dir = await mkdtemp(join(tmpdir(), "webgis-agent-session-"));
    const manager = new SessionManager(dir);

    try {
      await manager.init();
      await expect(manager.loadSession("../outside")).rejects.toThrow(/Invalid session id/);
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
});
