import { readFile, writeFile } from "node:fs/promises";
import type { Tool, ToolContext, ToolResult } from "../tool.js";
import { resolveWorkspacePath } from "./path-utils.js";

export const editFileTool: Tool = {
  name: "edit_file",
  description:
    "Edit a file using search-and-replace. Finds the exact old_string in the file and replaces it with new_string. " +
    "The old_string must be unique in the file (or use replace_all). Always read the file first to get the exact string.",
  parameters: {
    type: "object",
    properties: {
      file_path: { type: "string", description: "Path to the file to edit" },
      old_string: { type: "string", description: "The exact string to find and replace" },
      new_string: { type: "string", description: "The replacement string" },
      replace_all: { type: "boolean", description: "Replace all occurrences (default false)" },
    },
    required: ["file_path", "old_string", "new_string"],
  },

  isReadOnly: () => false,
  requiresConfirmation: () => true,

  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const filePath = resolveWorkspacePath(args.file_path as string, ctx.cwd);
      const oldStr = args.old_string as string;
      const newStr = args.new_string as string;
      const replaceAll = Boolean(args.replace_all);

      if (oldStr === newStr) {
        return { output: "Error: old_string and new_string are identical.", isError: true };
      }

      const content = await readFile(filePath, "utf-8");

      if (!content.includes(oldStr)) {
        return {
          output: `Error: old_string not found in ${filePath}. Make sure you read the file first and use the exact text.`,
          isError: true,
        };
      }

      let newContent: string;
      let count: number;

      if (replaceAll) {
        count = content.split(oldStr).length - 1;
        newContent = content.split(oldStr).join(newStr);
      } else {
        // Check uniqueness
        const occurrences = content.split(oldStr).length - 1;
        if (occurrences > 1) {
          return {
            output: `Error: old_string appears ${occurrences} times in the file. Provide more context to make it unique, or use replace_all: true.`,
            isError: true,
          };
        }
        count = 1;
        newContent = content.replace(oldStr, newStr);
      }

      await writeFile(filePath, newContent, "utf-8");

      // Build diff preview
      const oldLines = oldStr.split("\n");
      const newLines = newStr.split("\n");
      const diff = [
        ...oldLines.map((l) => `- ${l}`),
        ...newLines.map((l) => `+ ${l}`),
      ].join("\n");

      return {
        output: `Edited ${filePath} (${count} replacement${count > 1 ? "s" : ""}):\n${diff}`,
      };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { output: `Error editing file: ${msg}`, isError: true };
    }
  },
};
