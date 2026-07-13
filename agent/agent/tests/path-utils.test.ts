import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { resolveWorkspacePath } from "../src/tools/path-utils.js";

describe("resolveWorkspacePath", () => {
  it("allows paths inside the workspace and rejects traversal outside it", async () => {
    const root = await mkdtemp(join(tmpdir(), "webgis-agent-path-"));
    const workspace = join(root, "workspace");
    await mkdir(workspace);

    try {
      expect(resolveWorkspacePath("src/index.ts", workspace)).toBe(join(workspace, "src", "index.ts"));
      expect(() => resolveWorkspacePath("../outside.txt", workspace)).toThrow(/outside the workspace/);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
