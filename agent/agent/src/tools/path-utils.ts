import { isAbsolute, relative, resolve } from "node:path";

export function resolveWorkspacePath(inputPath: string, cwd: string): string {
  const path = String(inputPath || "").trim();
  if (!path) {
    throw new Error("Path is required.");
  }

  const workspaceRoot = resolve(cwd);
  const candidate = isAbsolute(path) ? resolve(path) : resolve(workspaceRoot, path);
  const rel = relative(workspaceRoot, candidate);

  if (rel === "" || (!rel.startsWith("..") && !isAbsolute(rel))) {
    return candidate;
  }

  throw new Error(`Path is outside the workspace: ${inputPath}`);
}
