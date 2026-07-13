import { spawn } from "node:child_process";
import type { Tool, ToolContext, ToolResult } from "../tool.js";

const DEFAULT_TIMEOUT = 120_000; // 120 seconds
const MAX_OUTPUT = 50_000;

export const runCommandTool: Tool = {
  name: "run_command",
  description:
    "Execute a shell command and return its output. " +
    "Use for running tests, building, git operations, etc. " +
    "Commands run in the current working directory.",
  parameters: {
    type: "object",
    properties: {
      command: { type: "string", description: "The shell command to execute" },
      timeout: { type: "number", description: "Timeout in ms (default: 120000)" },
    },
    required: ["command"],
  },

  isReadOnly: () => false,
  requiresConfirmation: () => true,

  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    const command = args.command as string;
    const timeout = Number(args.timeout) || DEFAULT_TIMEOUT;

    return new Promise((resolve) => {
      const isWindows = process.platform === "win32";
      const shell = isWindows ? "cmd" : "bash";
      const shellArgs = isWindows ? ["/c", command] : ["-c", command];

      const proc = spawn(shell, shellArgs, {
        cwd: ctx.cwd,
        timeout,
        env: { ...process.env },
        windowsHide: true,
      });

      let stdout = "";
      let stderr = "";

      proc.stdout.on("data", (data: Buffer) => {
        stdout += data.toString();
        if (stdout.length > MAX_OUTPUT) {
          stdout = stdout.slice(0, MAX_OUTPUT) + "\n[... output truncated]";
        }
      });

      proc.stderr.on("data", (data: Buffer) => {
        stderr += data.toString();
        if (stderr.length > MAX_OUTPUT) {
          stderr = stderr.slice(0, MAX_OUTPUT) + "\n[... output truncated]";
        }
      });

      proc.on("close", (code) => {
        const parts: string[] = [];
        if (stdout.trim()) parts.push(`stdout:\n${stdout.trim()}`);
        if (stderr.trim()) parts.push(`stderr:\n${stderr.trim()}`);
        parts.push(`exit code: ${code}`);

        const output = parts.join("\n\n");
        const isError = code !== 0;
        resolve({
          output: isError ? `Command failed.\n${output}` : output,
          isError,
        });
      });

      proc.on("error", (err) => {
        resolve({
          output: `Command error: ${err.message}`,
          isError: true,
        });
      });
    });
  },
};
