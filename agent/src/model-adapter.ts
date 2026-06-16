import type { AgentConfig } from "./config.js";
import type { Message, ModelAdapter, ModelResponse, ToolDefinition } from "./tool.js";

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

function isRetryable(err: unknown): boolean {
  if (err instanceof TypeError && err.message.includes("fetch")) return true;
  if (err instanceof Error && err.message.includes("ECONNRESET")) return true;
  return false;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
