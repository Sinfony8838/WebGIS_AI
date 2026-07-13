import { z } from "zod";

// ─── Message Types (OpenAI Chat Completions compatible) ───────────────────

export interface ToolCall {
  id: string;
  type: "function";
  function: {
    name: string;
    arguments: string;
  };
}

export type Message =
  | { role: "system"; content: string }
  | { role: "user"; content: string }
  | { role: "assistant"; content: string | null; tool_calls?: ToolCall[] }
  | { role: "tool"; tool_call_id: string; content: string };

// ─── Tool Contract ────────────────────────────────────────────────────────

export interface ToolContext {
  cwd: string;
  backendUrl: string;
  sessionId: string;
}

export interface ToolResult {
  output: string;
  isError?: boolean;
}

export interface Tool {
  name: string;
  description: string;
  /** JSON Schema for the model's function calling */
  parameters: Record<string, unknown>;
  execute(args: Record<string, unknown>, ctx: ToolContext): Promise<ToolResult>;
  isReadOnly(): boolean;
  requiresConfirmation(): boolean;
}

// ─── Model Adapter Types ──────────────────────────────────────────────────

export interface ToolDefinition {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

export interface ModelResponse {
  content: string | null;
  tool_calls: ToolCall[];
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens?: number };
  finish_reason: "stop" | "tool_calls" | "length";
}

export interface ModelAdapter {
  chat(messages: Message[], tools?: ToolDefinition[]): Promise<ModelResponse>;
}

// ─── Tool Registry ────────────────────────────────────────────────────────

export class ToolRegistry {
  private tools = new Map<string, Tool>();

  register(tool: Tool): void {
    this.tools.set(tool.name, tool);
  }

  registerAll(tools: Tool[]): void {
    for (const t of tools) this.register(t);
  }

  get(name: string): Tool | undefined {
    return this.tools.get(name);
  }

  getAll(): Tool[] {
    return Array.from(this.tools.values());
  }

  getDefinitions(): ToolDefinition[] {
    return this.getAll().map((t) => ({
      type: "function",
      function: {
        name: t.name,
        description: t.description,
        parameters: t.parameters,
      },
    }));
  }

  async execute(
    name: string,
    args: Record<string, unknown>,
    ctx: ToolContext,
  ): Promise<ToolResult> {
    const tool = this.tools.get(name);
    if (!tool) {
      return { output: `Unknown tool: ${name}`, isError: true };
    }
    try {
      return await tool.execute(args, ctx);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { output: `Tool error (${name}): ${msg}`, isError: true };
    }
  }
}
