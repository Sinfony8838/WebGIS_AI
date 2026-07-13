import { writeFile, mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import type { Tool, ToolContext, ToolResult } from "../tool.js";
import { resolveWorkspacePath } from "./path-utils.js";

export const writeFileTool: Tool = {
  name: "write_file",
  description:
    "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. " +
    "Parent directories are created automatically.",
  parameters: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Absolute or relative path to the file" },
      content: { type: "string", description: "Content to write to the file" },
    },
    required: ["file_path", "content"],
  },

  isReadOnly: () => false,
  requiresConfirmation: () => true,

  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const filePath = resolveWorkspacePath(args.file_path as string, ctx.cwd);
      const content = args.content as string;

      await mkdir(dirname(filePath), { recursive: true });
      await writeFile(filePath, content, "utf-8");
      const lines = content.split("\n").length;
      return { output: `Wrote ${lines} lines to ${filePath}` };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { output: `Error writing file: ${msg}`, isError: true };
    }
  },
};
