import type { Message, ModelAdapter, ToolCall, ToolDefinition, ToolRegistry } from "./tool.js";
import type { PermissionManager } from "./permissions.js";
import type { AgentConfig } from "./config.js";
import { buildSystemPrompt } from "./prompt.js";
import { applySnipCompact, estimateTokens, autoCompact } from "./context.js";

export interface AgentLoopCallbacks {
  onAssistantText?: (text: string, isProgress: boolean) => void;
  onToolCall?: (name: string, args: Record<string, unknown>) => void;
  onToolResult?: (name: string, output: string, isError: boolean) => void;
  onStatus?: (msg: string) => void;
  onConfirm?: (toolName: string, args: Record<string, unknown>) => Promise<boolean>;
  onAskUser?: (question: string) => Promise<string>;
}

export interface AgentLoopResult {
  messages: Message[];
  totalTokens: number;
  toolCallCount: number;
}

/**
 * Core agentic loop. Sends messages to the model, executes tool calls,
 * and loops until the model produces a final text response.
 *
 * Follows the same pattern as Claude Code's query.ts and MiniCode's agent-loop.ts.
 */
export async function runAgentLoop(params: {
  userMessage: string;
  messages: Message[];
  model: ModelAdapter;
  tools: ToolRegistry;
  permissions: PermissionManager;
  config: AgentConfig;
  ctx: { cwd: string; backendUrl: string; sessionId: string };
  callbacks?: AgentLoopCallbacks;
  sessionSummary?: string;
}): Promise<AgentLoopResult> {
  const {
    userMessage,
    messages,
    model,
    tools,
    permissions,
    config,
    ctx,
    callbacks,
    sessionSummary,
  } = params;

  const cbs = callbacks ?? {};
  let totalTokens = 0;
  let toolCallCount = 0;

  // Append user message
  messages.push({ role: "user", content: userMessage });

  const toolDefs = tools.getDefinitions();

  for (let turn = 0; turn < config.maxTurns; turn++) {
    // ── Context compression ──
    applySnipCompact(messages);

    const estimatedTokens = estimateTokens(messages);
    if (estimatedTokens > 60000) {
      cbs.onStatus?.("Context is large, compressing...");
      await autoCompact(messages, model, config);
    }

    // ── Build system prompt ──
    const systemPrompt = buildSystemPrompt(config, sessionSummary);

    // ── Call model ──
    cbs.onStatus?.(`Calling model (turn ${turn + 1})...`);

    const apiMessages: Message[] = [
      { role: "system", content: systemPrompt },
      ...messages,
    ];

    let response;
    try {
      response = await model.chat(apiMessages, toolDefs);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      cbs.onStatus?.(`Model error: ${errMsg}`);
      messages.push({ role: "assistant", content: `[Error] ${errMsg}` });
      break;
    }

    if (response.usage) {
      totalTokens += response.usage.total_tokens ?? response.usage.prompt_tokens + response.usage.completion_tokens;
    }

    // ── Handle response ──
    if (response.finish_reason === "stop" || response.finish_reason === "length") {
      // Final answer (or truncation)
      const content = response.content ?? "";
      messages.push({ role: "assistant", content });

      if (response.finish_reason === "length") {
        cbs.onStatus?.("Warning: response was truncated (max_tokens reached).");
      }

      // Parse progress/final markers
      const isProgress = content.startsWith("[progress]");
      const displayText = isProgress ? content.replace(/^\[progress\]\s*/, "") : content;
      cbs.onAssistantText?.(displayText, isProgress);

      // If marked as progress, continue the loop with a continuation prompt
      if (isProgress) {
        messages.push({ role: "user", content: "Continue." });
        continue;
      }

      break;
    }

    if (response.finish_reason === "tool_calls" && response.tool_calls.length > 0) {
      // Append assistant message with tool calls
      messages.push({
        role: "assistant",
        content: response.content,
        tool_calls: response.tool_calls,
      });

      if (response.content) {
        const isProgress = response.content.startsWith("[progress]");
        const displayText = isProgress
          ? response.content.replace(/^\[progress\]\s*/, "")
          : response.content;
        cbs.onAssistantText?.(displayText, isProgress);
      }

      // ── Execute tool calls ──
      for (const toolCall of response.tool_calls) {
        const { name, args } = parseToolCall(toolCall);
        toolCallCount++;

        cbs.onToolCall?.(name, args);

        // Permission check
        const tool = tools.get(name);
        let allowed = true;
        if (tool) {
          const decision = permissions.check(tool);
          if (decision === "deny") {
            messages.push({
              role: "tool",
              tool_call_id: toolCall.id,
              content: `Permission denied for tool: ${name}`,
            });
            cbs.onToolResult?.(name, "Permission denied", true);
            continue;
          }
          if (decision === "confirm" && cbs.onConfirm) {
            allowed = await cbs.onConfirm(name, args);
            if (allowed) {
              permissions.approveForSession(name);
            }
          }
        }

        if (!allowed) {
          messages.push({
            role: "tool",
            tool_call_id: toolCall.id,
            content: "User denied this operation.",
          });
          cbs.onToolResult?.(name, "Denied by user", true);
          continue;
        }

        if (name === "ask_user" && cbs.onAskUser) {
          const question = typeof args.question === "string" ? args.question : "Please provide more information.";
          const answer = await cbs.onAskUser(question);
          const output = `User answered: ${answer}`;
          messages.push({
            role: "tool",
            tool_call_id: toolCall.id,
            content: output,
          });
          cbs.onToolResult?.(name, output, false);
          continue;
        }

        // Execute
        const result = await tools.execute(name, args, ctx);
        messages.push({
          role: "tool",
          tool_call_id: toolCall.id,
          content: result.output,
        });
        cbs.onToolResult?.(name, result.output, result.isError ?? false);
      }

      // Continue loop for next model call
      continue;
    }

    // Unexpected finish reason
    const content = response.content ?? "(empty response)";
    messages.push({ role: "assistant", content });
    cbs.onAssistantText?.(content, false);
    break;
  }

  return { messages, totalTokens, toolCallCount };
}

function parseToolCall(tc: ToolCall): { name: string; args: Record<string, unknown> } {
  let args: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(tc.function.arguments);
    if (typeof parsed === "object" && parsed !== null) {
      args = parsed;
    }
  } catch {
    // If JSON parse fails, try as a plain string argument
    args = { input: tc.function.arguments };
  }
  return { name: tc.function.name, args };
}
