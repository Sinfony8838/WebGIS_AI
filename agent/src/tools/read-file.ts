import { readFile, stat } from "node:fs/promises";
import type { Tool, ToolContext, ToolResult } from "../tool.js";
import { resolveWorkspacePath } from "./path-utils.js";

const MAX_LINES = 2000;
const DEFAULT_LIMIT = 500;

export const readFileTool: Tool = {
  name: "read_file",
  description:
    "Read the contents of a text file. Returns content with line numbers (cat -n style). " +
    "Supports offset and limit for reading portions of large files. " +
    "Default reads first 500 lines.",
  parameters: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Absolute or relative path to the file" },
      offset: { type: "number", description: "Line number to start from (0-based, optional)" },
      limit: { type: "number", description: "Max lines to read (default 500, max 2000)" },
    },
    required: ["file_path"],
  },

  isReadOnly: () => true,
  requiresConfirmation: () => false,

  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const filePath = resolveWorkspacePath(args.file_path as string, ctx.cwd);
      const offset = Math.max(0, Number(args.offset) || 0);
      const limit = Math.min(MAX_LINES, Math.max(1, Number(args.limit) || DEFAULT_LIMIT));

      const info = await stat(filePath);
      if (info.isDirectory()) {
        return { output: `Error: ${filePath} is a directory, not a file. Use list_files instead.`, isError: true };
      }

      const content = await readFile(filePath, "utf-8");
      const lines = content.split("\n");
      const totalLines = lines.length;

      const selected = lines.slice(offset, offset + limit);
      const numbered = selected.map((line, i) => {
        const num = String(offset + i + 1).padStart(6, " ");
        return `${num}\t${line}`;
      });

      let output = numbered.join("\n");
      if (offset + limit < totalLines) {
        output += `\n\n[Showing lines ${offset + 1}-${offset + limit} of ${totalLines}. Use offset to read more.]`;
      }

      return { output };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { output: `Error reading file: ${msg}`, isError: true };
    }
  },
};
