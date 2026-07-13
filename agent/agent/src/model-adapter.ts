import type { AgentConfig } from "./config.js";
import type { Message, ModelAdapter, ModelResponse, ToolCall, ToolDefinition } from "./tool.js";

// ─── OpenAI Chat Completions API types ────────────────────────────────────

interface OpenAIChoice {
  index: number;
  message: {
    role: string;
    content: string | null;
    tool_calls?: Array<{
      id: string;
      type: string;
      function: { name: string; arguments: string };
    }>;
  };
  finish_reason: string;
}

interface OpenAIChatResponse {
  id: string;
  choices: OpenAIChoice[];
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
}

// ─── MiMo API Adapter ────────────────────────────────────────────────────

export class MiMoAdapter implements ModelAdapter {
  constructor(private config: AgentConfig) {}

  async chat(messages: Message[], tools?: ToolDefinition[]): Promise<ModelResponse> {
    const body: Record<string, unknown> = {
      model: this.config.model,
      messages,
      temperature: this.config.temperature,
      max_tokens: this.config.maxTokens,
    };
    if (tools && tools.length > 0) {
      body.tools = tools;
      body.tool_choice = "auto";
    }

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "api-key": this.config.apiKey,
    };

    const url = `${this.config.baseUrl.replace(/\/+$/, "")}/chat/completions`;

    let lastError: Error | null = null;
    const maxRetries = 4;

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        const response = await fetch(url, {
          method: "POST",
          headers,
          body: JSON.stringify(body),
        });

        if (response.status === 429 || response.status >= 500) {
          const retryAfter = response.headers.get("Retry-After");
          const baseDelay = retryAfter
            ? parseInt(retryAfter, 10) * 1000
            : 500 * Math.pow(2, attempt);
          const jitter = baseDelay * 0.25 * Math.random();
          const delay = Math.min(baseDelay + jitter, 8000);

          if (attempt < maxRetries) {
            await sleep(delay);
            continue;
          }
        }

        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(`MiMo API ${response.status}: ${errorText}`);
        }

        const data = (await response.json()) as OpenAIChatResponse;
        const choice = data.choices?.[0];
        if (!choice) throw new Error("MiMo returned no choices");

        return {
          content: choice.message?.content ?? null,
          tool_calls: choice.message?.tool_calls?.map((tc) => ({
            id: tc.id,
            type: "function" as const,
            function: { name: tc.function.name, arguments: tc.function.arguments },
          })) ?? [],
          usage: data.usage
            ? {
                prompt_tokens: data.usage.prompt_tokens,
                completion_tokens: data.usage.completion_tokens,
                total_tokens: data.usage.total_tokens,
              }
            : undefined,
          finish_reason: (choice.finish_reason as ModelResponse["finish_reason"]) ?? "stop",
        };
      } catch (err: unknown) {
        lastError = err instanceof Error ? err : new Error(String(err));
        if (attempt < maxRetries && isRetryable(err)) {
          await sleep(500 * Math.pow(2, attempt));
          continue;
        }
        break;
      }
    }

    throw lastError ?? new Error("MiMo API request failed after retries");
  }
}

// ─── MiniMax Anthropic-compatible API Adapter ────────────────────────────
//
// MiniMax exposes an Anthropic Messages compatible endpoint
// (https://platform.minimaxi.com/docs/api-reference/text-anthropic-api).
// The agent loop keeps its OpenAI-style message history; this adapter
// translates to/from the Anthropic schema at the API boundary:
//   - system messages  → top-level `system` string
//   - assistant tool_calls → `tool_use` content blocks
//   - role:"tool" results   → user-turn `tool_result` content blocks
//   - tools → [{name, description, input_schema}]

interface AnthropicContentBlock {
  type: string;
  text?: string;
  id?: string;
  name?: string;
  input?: Record<string, unknown>;
  tool_use_id?: string;
  content?: string;
  is_error?: boolean;
}

interface AnthropicResponse {
  id: string;
  content: AnthropicContentBlock[];
  stop_reason: string | null;
  usage?: { input_tokens: number; output_tokens: number };
}

function toAnthropicPayload(
  messages: Message[],
  tools: ToolDefinition[] | undefined,
  config: AgentConfig,
): Record<string, unknown> {
  const systemParts: string[] = [];
  const converted: Array<{ role: "user" | "assistant"; content: AnthropicContentBlock[] }> = [];

  const pushBlocks = (role: "user" | "assistant", blocks: AnthropicContentBlock[]) => {
    if (!blocks.length) return;
    const last = converted[converted.length - 1];
    if (last && last.role === role) {
      // Anthropic requires alternating roles; merge consecutive same-role turns.
      last.content.push(...blocks);
      return;
    }
    converted.push({ role, content: blocks });
  };

  for (const message of messages) {
    if (message.role === "system") {
      if (message.content.trim()) systemParts.push(message.content);
      continue;
    }
    if (message.role === "user") {
      pushBlocks("user", [{ type: "text", text: message.content }]);
      continue;
    }
    if (message.role === "assistant") {
      const blocks: AnthropicContentBlock[] = [];
      if (message.content && message.content.trim()) {
        blocks.push({ type: "text", text: message.content });
      }
      for (const call of message.tool_calls ?? []) {
        let input: Record<string, unknown> = {};
        try {
          const parsed = JSON.parse(call.function.arguments || "{}");
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) input = parsed;
        } catch {
          // leave input as {}
        }
        blocks.push({ type: "tool_use", id: call.id, name: call.function.name, input });
      }
      pushBlocks("assistant", blocks);
      continue;
    }
    // role === "tool" → Anthropic tool_result inside a user turn
    pushBlocks("user", [
      { type: "tool_result", tool_use_id: message.tool_call_id, content: message.content },
    ]);
  }

  // The API requires the conversation to start with a user turn.
  if (converted.length && converted[0].role !== "user") {
    converted.unshift({ role: "user", content: [{ type: "text", text: "(继续)" }] });
  }

  const body: Record<string, unknown> = {
    model: config.model,
    max_tokens: config.maxTokens,
    temperature: config.temperature,
    messages: converted,
  };
  if (systemParts.length) {
    body.system = systemParts.join("\n\n");
  }
  if (tools && tools.length > 0) {
    body.tools = tools.map((tool) => ({
      name: tool.function.name,
      description: tool.function.description,
      input_schema: tool.function.parameters,
    }));
  }
  return body;
}

export class MiniMaxAnthropicAdapter implements ModelAdapter {
  constructor(private config: AgentConfig) {}

  async chat(messages: Message[], tools?: ToolDefinition[]): Promise<ModelResponse> {
    const body = toAnthropicPayload(messages, tools, this.config);
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      // MiniMax's Anthropic-compatible endpoint accepts the API key in either
      // Anthropic style (x-api-key) or Bearer form; send both for safety.
      "x-api-key": this.config.apiKey,
      Authorization: `Bearer ${this.config.apiKey}`,
      "anthropic-version": "2023-06-01",
    };

    const url = `${this.config.baseUrl.replace(/\/+$/, "")}/v1/messages`;

    let lastError: Error | null = null;
    const maxRetries = 4;

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        const response = await fetch(url, {
          method: "POST",
          headers,
          body: JSON.stringify(body),
        });

        if (response.status === 429 || response.status >= 500) {
          const retryAfter = response.headers.get("Retry-After");
          const baseDelay = retryAfter
            ? parseInt(retryAfter, 10) * 1000
            : 500 * Math.pow(2, attempt);
          const jitter = baseDelay * 0.25 * Math.random();
          const delay = Math.min(baseDelay + jitter, 8000);

          if (attempt < maxRetries) {
            await sleep(delay);
            continue;
          }
        }

        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(`MiniMax API ${response.status}: ${errorText}`);
        }

        const data = (await response.json()) as AnthropicResponse;
        const blocks = Array.isArray(data.content) ? data.content : [];
        const text = blocks
          .filter((block) => block.type === "text" && typeof block.text === "string")
          .map((block) => block.text)
          .join("");
        const toolCalls: ToolCall[] = blocks
          .filter((block) => block.type === "tool_use" && block.name)
          .map((block, index) => ({
            id: block.id || `tool_${Date.now()}_${index}`,
            type: "function" as const,
            function: {
              name: String(block.name),
              arguments: JSON.stringify(block.input ?? {}),
            },
          }));

        const finishReason: ModelResponse["finish_reason"] =
          data.stop_reason === "tool_use"
            ? "tool_calls"
            : data.stop_reason === "max_tokens"
              ? "length"
              : "stop";

        return {
          content: text || null,
          tool_calls: toolCalls,
          usage: data.usage
            ? {
                prompt_tokens: data.usage.input_tokens,
                completion_tokens: data.usage.output_tokens,
                total_tokens: data.usage.input_tokens + data.usage.output_tokens,
              }
            : undefined,
          finish_reason: finishReason,
        };
      } catch (err: unknown) {
        lastError = err instanceof Error ? err : new Error(String(err));
        if (attempt < maxRetries && isRetryable(err)) {
          await sleep(500 * Math.pow(2, attempt));
          continue;
        }
        break;
      }
    }

    throw lastError ?? new Error("MiniMax API request failed after retries");
  }
}

/** Instantiate the adapter matching ``config.provider``. */
export function createModelAdapter(config: AgentConfig): ModelAdapter {
  if (config.provider === "minimax") {
    return new MiniMaxAnthropicAdapter(config);
  }
  return new MiMoAdapter(config);
}

function isRetryable(err: unknown): boolean {
  if (err instanceof TypeError && err.message.includes("fetch")) return true;
  if (err instanceof Error && err.message.includes("ECONNRESET")) return true;
  return false;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
