import { spawn } from "node:child_process";
import { join } from "node:path";
import { readFile, readdir, stat } from "node:fs/promises";
import type { Tool, ToolContext, ToolResult } from "../tool.js";
import { resolveWorkspacePath } from "./path-utils.js";

const MAX_MATCHES = 250;

export const grepFilesTool: Tool = {
  name: "grep_files",
  description:
    "Search file contents using a regex pattern. Uses ripgrep if available, falls back to Node.js. " +
    "Returns matching lines with file paths and line numbers.",
  parameters: {
    type: "object",
    properties: {
      pattern: { type: "string", description: "Regex pattern to search for" },
      path: { type: "string", description: "Directory or file to search in (default: cwd)" },
      glob: { type: "string", description: "File glob filter (e.g. '*.ts')" },
      ignore_case: { type: "boolean", description: "Case-insensitive search" },
    },
    required: ["pattern"],
  },

  isReadOnly: () => true,
  requiresConfirmation: () => false,

  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const pattern = args.pattern as string;
      const searchPath = args.path ? resolveWorkspacePath(args.path as string, ctx.cwd) : ctx.cwd;
      const globFilter = args.glob as string | undefined;
      const ignoreCase = Boolean(args.ignore_case);

      return await grepWithRg(pattern, searchPath, globFilter, ignoreCase);
    } catch {
      try {
        const pattern = args.pattern as string;
        const searchPath = args.path ? resolveWorkspacePath(args.path as string, ctx.cwd) : ctx.cwd;
        const globFilter = args.glob as string | undefined;
        const ignoreCase = Boolean(args.ignore_case);
        return await grepWithNode(pattern, searchPath, globFilter, ignoreCase);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        return { output: `Error searching files: ${msg}`, isError: true };
      }
    }
  },
};

async function grepWithRg(
  pattern: string,
  searchPath: string,
  globFilter: string | undefined,
  ignoreCase: boolean,
): Promise<ToolResult> {
  return new Promise((resolve, reject) => {
    const args = ["--no-heading", "-n", "--max-count", String(MAX_MATCHES)];
    if (ignoreCase) args.push("-i");
    if (globFilter) args.push("--glob", globFilter);
    args.push(pattern, searchPath);

    const proc = spawn("rg", args, { shell: false, timeout: 15000 });
    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (data: Buffer) => (stdout += data.toString()));
    proc.stderr.on("data", (data: Buffer) => (stderr += data.toString()));

    proc.on("close", (code) => {
      if (code === 0 || code === 1) {
        // code 1 = no matches
        const lines = stdout.trim().split("\n").filter(Boolean);
        if (lines.length === 0) {
          resolve({ output: `No matches found for "${pattern}"` });
        } else {
          const truncated = lines.length >= MAX_MATCHES;
          let output = lines.slice(0, MAX_MATCHES).join("\n");
          if (truncated) output += `\n\n[Showing first ${MAX_MATCHES} matches]`;
          resolve({ output });
        }
      } else {
        reject(new Error(stderr || `rg exited with code ${code}`));
      }
    });

    proc.on("error", reject);
  });
}

async function grepWithNode(
  pattern: string,
  searchPath: string,
  globFilter: string | undefined,
  ignoreCase: boolean,
): Promise<ToolResult> {
  const regex = new RegExp(pattern, ignoreCase ? "gi" : "g");
  const matches: string[] = [];
  const maxFiles = 100;

  async function walk(dir: string, depth: number): Promise<void> {
    if (depth > 5 || matches.length >= MAX_MATCHES) return;
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }

    for (const entry of entries) {
      if (matches.length >= MAX_MATCHES) break;
      if (entry.name.startsWith(".") || entry.name === "node_modules") continue;

      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(fullPath, depth + 1);
      } else if (entry.isFile()) {
        // Apply glob filter
        if (globFilter && !matchGlob(entry.name, globFilter)) continue;

        try {
          const content = await readFile(fullPath, "utf-8");
          const lines = content.split("\n");
          for (let i = 0; i < lines.length && matches.length < MAX_MATCHES; i++) {
            regex.lastIndex = 0;
            if (regex.test(lines[i])) {
              const rel = fullPath.startsWith(searchPath) ? fullPath.slice(searchPath.length + 1) : fullPath;
              matches.push(`${rel}:${i + 1}: ${lines[i]}`);
            }
          }
        } catch {
          // skip binary or unreadable files
        }
      }
    }
  }

  const info = await stat(searchPath).catch(() => null);
  if (info?.isFile()) {
    const content = await readFile(searchPath, "utf-8");
    const lines = content.split("\n");
    for (let i = 0; i < lines.length && matches.length < MAX_MATCHES; i++) {
      regex.lastIndex = 0;
      if (regex.test(lines[i])) {
        matches.push(`${searchPath}:${i + 1}: ${lines[i]}`);
      }
    }
  } else {
    await walk(searchPath, 0);
  }

  if (matches.length === 0) {
    return { output: `No matches found for "${pattern}"` };
  }

  const truncated = matches.length >= MAX_MATCHES;
  let output = matches.join("\n");
  if (truncated) output += `\n\n[Showing first ${MAX_MATCHES} matches]`;
  return { output };
}

function matchGlob(name: string, pattern: string): boolean {
  const regex = new RegExp(
    "^" + pattern.replace(/\./g, "\\.").replace(/\*/g, ".*").replace(/\?/g, ".") + "$",
  );
  return regex.test(name);
}
