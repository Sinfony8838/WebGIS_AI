import type { Message, ModelAdapter } from "./tool.js";
import type { AgentConfig } from "./config.js";

const MAX_TOOL_OUTPUT_CHARS = 3000;
const MAX_LINE_COUNT = 80;

/**
 * Snip compact: truncate large tool outputs in-place.
 * Replaces oversized tool results with a summary showing first/last N lines.
 */
export function applySnipCompact(messages: Message[]): void {
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    if (msg.role !== "tool") continue;
    if (msg.content.length <= MAX_TOOL_OUTPUT_CHARS) continue;

    const lines = msg.content.split("\n");
    if (lines.length > MAX_LINE_COUNT) {
      const head = lines.slice(0, 30).join("\n");
      const tail = lines.slice(-20).join("\n");
      messages[i] = {
        ...msg,
        content: `${head}\n\n[... ${lines.length - 50} lines omitted ...]\n\n${tail}`,
      };
    } else {
      messages[i] = {
        ...msg,
        content: msg.content.slice(0, MAX_TOOL_OUTPUT_CHARS) + `\n[... truncated, ${msg.content.length} chars total]`,
      };
    }
  }
}

/**
 * Estimate token count (rough: ~4 chars per token for mixed CJK/English).
 */
export function estimateTokens(messages: Message[]): number {
  let total = 0;
  for (const msg of messages) {
    if (msg.role === "system" || msg.role === "user") {
      total += msg.content.length / 3;
    } else if (msg.role === "assistant") {
      total += (msg.content?.length ?? 0) / 3;
      if (msg.tool_calls) {
        for (const tc of msg.tool_calls) {
          total += tc.function.arguments.length / 3 + 20;
        }
      }
    } else if (msg.role === "tool") {
      total += msg.content.length / 3;
    }
  }
  return Math.round(total);
}

/**
 * Auto-compact: ask LLM to summarize older messages, keep summary + recent.
 */
export async function autoCompact(
  messages: Message[],
  model: ModelAdapter,
  config: AgentConfig,
): Promise<void> {
  if (messages.length < 6) return;

  // Keep last 4 messages, summarize the rest
  const keepCount = 4;
  const toSummarize = messages.slice(0, -keepCount);
  const recent = messages.slice(-keepCount);

  // Build summarization request
  const summaryParts: string[] = [];
  for (const msg of toSummarize) {
    if (msg.role === "user") {
      summaryParts.push(`User: ${msg.content.slice(0, 200)}`);
    } else if (msg.role === "assistant") {
      const text = msg.content?.slice(0, 200) ?? "";
      const tools = msg.tool_calls?.map((tc) => tc.function.name).join(", ") ?? "";
      summaryParts.push(`Assistant: ${text}${tools ? ` [used tools: ${tools}]` : ""}`);
    } else if (msg.role === "tool") {
      summaryParts.push(`Tool result (${msg.content.length} chars)`);
    }
  }

  const summaryPrompt = [
    { role: "system" as const, content: "You are a summarizer. Summarize the following conversation in 3-5 concise bullet points. Focus on decisions made, files changed, and current task state. Reply in the same language as the conversation." },
    { role: "user" as const, content: summaryParts.join("\n") },
  ];

  try {
    const response = await model.chat(summaryPrompt);
    const summary = response.content ?? "(summary unavailable)";

    // Replace messages with summary + recent
    messages.length = 0;
    messages.push({ role: "user", content: `[Previous conversation summary]\n${summary}` });
    messages.push(...recent);
  } catch {
    // If summarization fails, just snip-compact and continue
    applySnipCompact(messages);
  }
}
