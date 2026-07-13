import { glob } from "glob";
import type { Tool, ToolContext, ToolResult } from "../tool.js";
import { resolveWorkspacePath } from "./path-utils.js";

const MAX_RESULTS = 200;

export const listFilesTool: Tool = {
  name: "list_files",
  description:
    "List files and directories matching a glob pattern. " +
    "Examples: '**/*.ts', 'src/**', '*.json'. " +
    "Defaults to listing all files in the given path.",
  parameters: {
    type: "object",
    properties: {
      pattern: { type: "string", description: "Glob pattern (e.g. '**/*.ts', 'src/**')" },
      path: { type: "string", description: "Directory to search in (default: cwd)" },
    },
    required: ["pattern"],
  },

  isReadOnly: () => true,
  requiresConfirmation: () => false,

  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const pattern = args.pattern as string;
      const searchPath = args.path ? resolveWorkspacePath(args.path as string, ctx.cwd) : ctx.cwd;

      const files = await glob(pattern, {
        cwd: searchPath,
        nodir: false,
        dot: false,
        absolute: false,
        maxDepth: 10,
      });

      const sorted = files.sort().slice(0, MAX_RESULTS);
      const truncated = files.length > MAX_RESULTS;

      let output = sorted.join("\n");
      if (truncated) {
        output += `\n\n[Showing ${MAX_RESULTS} of ${files.length} results. Use a more specific pattern.]`;
      }
      if (sorted.length === 0) {
        output = `No files found matching "${pattern}" in ${searchPath}`;
      }

      return { output };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { output: `Error listing files: ${msg}`, isError: true };
    }
  },
};
