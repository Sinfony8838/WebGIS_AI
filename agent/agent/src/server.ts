#!/usr/bin/env node

import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { resolve } from "node:path";
import { loadConfig, validateConfig } from "./config.js";
import { createModelAdapter } from "./model-adapter.js";
import { PermissionManager } from "./permissions.js";
import { createToolRegistry } from "./registry.js";
import { runAgentLoop } from "./agent-loop.js";
import { SessionManager } from "./session.js";
import type { Message, ToolContext } from "./tool.js";

type AgentEvent =
  | { type: "status"; message: string }
  | { type: "assistant"; message: string; progress: boolean }
  | { type: "tool_call"; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; name: string; output: string; error: boolean };

type WebSession = {
  id: string;
  messages: Message[];
  permissions: PermissionManager;
};

const workspaceRoot = process.env.AGENT_WORKSPACE_DIR || resolve(process.cwd(), "..");
const config = loadConfig({ cwd: workspaceRoot });
const errors = validateConfig(config);
if (errors.length > 0) {
  console.error(`Agent server configuration error:\n${errors.join("\n")}`);
  process.exit(1);
}

const port = Number(process.env.AGENT_SERVER_PORT || "19000");
const model = createModelAdapter(config);
const tools = createToolRegistry();
const sessionManager = new SessionManager(config.sessionDir);
const sessions = new Map<string, WebSession>();
await sessionManager.init();

function sendJson(response: ServerResponse, statusCode: number, body: unknown): void {
  response.writeHead(statusCode, {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Content-Type": "application/json; charset=utf-8",
  });
  response.end(JSON.stringify(body));
}

async function readJson(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const raw = Buffer.concat(chunks).toString("utf-8").trim();
  if (!raw) return {};
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Request body must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

async function getSession(sessionId?: string): Promise<WebSession> {
  if (sessionId && sessions.has(sessionId)) {
    return sessions.get(sessionId)!;
  }

  if (sessionId) {
    const loaded = await sessionManager.loadSession(sessionId);
    const session = {
      id: sessionId,
      messages: loaded,
      permissions: new PermissionManager(config.autoApprove),
    };
    sessions.set(sessionId, session);
    return session;
  }

  const id = await sessionManager.createSession(config.cwd);
  const session = {
    id,
    messages: [],
    permissions: new PermissionManager(config.autoApprove),
  };
  sessions.set(id, session);
  return session;
}

function summarizeEvents(events: AgentEvent[], reply: string): string {
  const lines: string[] = [];
  const failed = events.filter(
    (event): event is Extract<AgentEvent, { type: "tool_result" }> =>
      event.type === "tool_result" && event.error,
  );

  if (reply.trim()) {
    lines.push(reply.trim());
  }
  if (failed.length > 0) {
    lines.push(`有 ${failed.length} 个工具步骤没有完成；需要时可以让我展开诊断细节。`);
  }

  return lines.join("\n\n").trim() || "已处理，但没有生成可显示的文本结果。";
}

async function handleChat(request: IncomingMessage, response: ServerResponse): Promise<void> {
  const body = await readJson(request);
  const message = String(body.message || "").trim();
  if (!message) {
    sendJson(response, 400, { status: "error", detail: "message is required" });
    return;
  }

  const session = await getSession(typeof body.session_id === "string" ? body.session_id : undefined);
  const startIndex = session.messages.length;
  const events: AgentEvent[] = [];
  const assistantTexts: Array<{ text: string; progress: boolean }> = [];
  const ctx: ToolContext = {
    cwd: config.cwd,
    backendUrl: config.backendUrl,
    sessionId: session.id,
  };

  const result = await runAgentLoop({
    userMessage: message,
    messages: session.messages,
    model,
    tools,
    permissions: session.permissions,
    config,
    ctx,
    callbacks: {
      onStatus(statusMessage) {
        events.push({ type: "status", message: statusMessage });
      },
      onAssistantText(text, isProgress) {
        assistantTexts.push({ text, progress: isProgress });
        events.push({ type: "assistant", message: text, progress: isProgress });
      },
      onToolCall(name, args) {
        events.push({ type: "tool_call", name, args });
      },
      onToolResult(name, output, isError) {
        events.push({ type: "tool_result", name, output, error: isError });
      },
      async onConfirm() {
        return config.autoApprove;
      },
      async onAskUser(question) {
        return `The web UI received this clarification request but no inline answer channel is available: ${question}`;
      },
    },
  });

  for (let i = startIndex; i < session.messages.length; i++) {
    await sessionManager.saveMessageToSession(session.id, session.messages[i]);
  }

  const finalText = [...assistantTexts].reverse().find((item) => !item.progress)?.text || "";
  sendJson(response, 200, {
    status: "success",
    session_id: session.id,
    reply: summarizeEvents(events, finalText),
    events,
    total_tokens: result.totalTokens,
    tool_call_count: result.toolCallCount,
    auto_approve: config.autoApprove,
    cwd: config.cwd,
  });
}

const server = createServer((request, response) => {
  void (async () => {
    if (request.method === "OPTIONS") {
      sendJson(response, 204, {});
      return;
    }
    if (request.method === "GET" && request.url === "/health") {
      sendJson(response, 200, {
        status: "ok",
        cwd: config.cwd,
        backend_url: config.backendUrl,
        auto_approve: config.autoApprove,
      });
      return;
    }
    if (request.method === "POST" && request.url === "/agent/chat") {
      await handleChat(request, response);
      return;
    }
    sendJson(response, 404, { status: "error", detail: "Not found" });
  })().catch((err: unknown) => {
    const detail = err instanceof Error ? err.message : String(err);
    sendJson(response, 500, { status: "error", detail });
  });
});

server.listen(port, "127.0.0.1", () => {
  console.log(`WebGIS Agent server listening on http://127.0.0.1:${port}`);
  console.log(`Workspace: ${config.cwd}`);
  console.log(`Auto approve: ${config.autoApprove ? "enabled" : "disabled"}`);
});
