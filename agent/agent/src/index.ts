#!/usr/bin/env node

import { Command } from "commander";
import chalk from "chalk";
import { loadConfig, validateConfig, type AgentConfig } from "./config.js";
import { createModelAdapter } from "./model-adapter.js";
import { ToolRegistry, type Message, type ModelAdapter, type ToolContext } from "./tool.js";
import { runAgentLoop } from "./agent-loop.js";
import { PermissionManager } from "./permissions.js";
import { TUI } from "./tui.js";
import { SessionManager } from "./session.js";
import { createToolRegistry } from "./registry.js";

// Tools

// ─── Register all tools ───────────────────────────────────────────────────

// ─── Chat command (interactive REPL) ──────────────────────────────────────

async function chatCommand(opts: {
  message?: string;
  session?: string;
  model?: string;
  backend?: string;
  autoApprove?: boolean;
}): Promise<void> {
  const config = loadConfig({
    model: opts.model,
    backendUrl: opts.backend,
    autoApprove: opts.autoApprove,
  });

  const errors = validateConfig(config);
  if (errors.length > 0) {
    console.error(chalk.red(`\n  Configuration errors:\n  ${errors.join("\n  ")}\n`));
    process.exit(1);
  }

  const tui = new TUI();
  const model = createModelAdapter(config);
  const tools = createToolRegistry();
  const permissions = new PermissionManager(config.autoApprove);
  const session = new SessionManager(config.sessionDir);
  await session.init();

  // Load or create session
  let messages: Message[] = [];
  let sessionId: string;

  if (opts.session) {
    sessionId = opts.session;
    messages = await session.loadSession(sessionId);
    tui.displayStatus(`Resumed session ${sessionId} (${messages.length} messages)`);
  } else {
    sessionId = await session.createSession(config.cwd);
    tui.displayStatus(`Session ${sessionId} started`);
  }

  const toolCtx: ToolContext = {
    cwd: config.cwd,
    backendUrl: config.backendUrl,
    sessionId,
  };

  tui.showBanner();

  // Single-shot mode
  if (opts.message) {
    await runSingleTurn(opts.message, messages, model, tools, permissions, config, toolCtx, tui, session);
    tui.close();
    return;
  }

  // Interactive REPL
  while (true) {
    const input = await tui.prompt();
    if (!input) continue;

    // Handle slash commands
    const slashResult = tui.handleSlashCommand(input);
    if (slashResult === "tools") {
      const toolList = tools.getAll();
      console.log(chalk.cyan(`\n  Available tools (${toolList.length}):`));
      for (const t of toolList) {
        console.log(chalk.dim(`    ${t.name.padEnd(25)} ${t.description.slice(0, 60)}`));
      }
      continue;
    }
    if (slashResult === "clear") {
      messages.length = 0;
      tui.displayStatus("Conversation cleared.");
      continue;
    }
    if (slashResult === "compact") {
      const { applySnipCompact } = await import("./context.js");
      applySnipCompact(messages);
      tui.displayStatus("Context compressed.");
      continue;
    }
    if (slashResult) continue; // /help was handled

    await runSingleTurn(input, messages, model, tools, permissions, config, toolCtx, tui, session);
  }
}

async function runSingleTurn(
  userMessage: string,
  messages: Message[],
  model: ModelAdapter,
  tools: ToolRegistry,
  permissions: PermissionManager,
  config: AgentConfig,
  toolCtx: ToolContext,
  tui: TUI,
  session: SessionManager,
): Promise<void> {
  const startIndex = messages.length;

  const result = await runAgentLoop({
    userMessage,
    messages,
    model,
    tools,
    permissions,
    config,
    ctx: toolCtx,
    callbacks: {
      onAssistantText(text, isProgress) {
        if (isProgress) {
          tui.displayProgress(text);
        } else {
          tui.displayAssistantMessage(text);
        }
      },
      onToolCall(name, args) {
        tui.displayToolCall(name, args);
      },
      onToolResult(name, output, isError) {
        tui.displayToolResult(name, output, isError);
      },
      onStatus(msg) {
        tui.displayStatus(msg);
      },
      async onConfirm(toolName, _args) {
        return tui.confirm(`Allow tool "${toolName}"?`);
      },
      async onAskUser(question) {
        return tui.ask(question);
      },
    },
  });

  // Save new messages to session
  for (let i = startIndex; i < messages.length; i++) {
    await session.saveMessage(result.messages[i]);
  }

  if (result.totalTokens > 0) {
    tui.displayStatus(`Tokens used: ~${result.totalTokens} | Tools called: ${result.toolCallCount}`);
  }
}

// ─── Sessions command ─────────────────────────────────────────────────────

async function sessionsCommand(): Promise<void> {
  const config = loadConfig();
  const session = new SessionManager(config.sessionDir);
  await session.init();

  const sessions = await session.listSessions();
  if (sessions.length === 0) {
    console.log(chalk.dim("\n  No sessions found.\n"));
    return;
  }

  console.log(chalk.cyan(`\n  Sessions (${sessions.length}):\n`));
  for (const s of sessions) {
    const date = new Date(s.updated_at).toLocaleString();
    console.log(chalk.white(`    ${s.id}`) + chalk.dim(`  ${date}  ${s.message_count} msgs`));
    if (s.first_message) {
      console.log(chalk.dim(`      ${s.first_message.slice(0, 70)}`));
    }
  }
  console.log();
}

// ─── CLI Definition ───────────────────────────────────────────────────────

const program = new Command();

program
  .name("webgis-agent")
  .description("CLI AI coding agent for WebGIS-AI project")
  .version("1.0.0");

program
  .command("chat")
  .description("Start an interactive chat session (default command)")
  .option("-m, --message <msg>", "Send a single message and exit")
  .option("-s, --session <id>", "Resume a previous session")
  .option("--model <model>", "Override MiMo model name")
  .option("--backend <url>", "Override WebGIS backend URL")
  .option("--auto-approve", "Auto-approve all tool calls (no confirmation prompts)")
  .action(chatCommand);

program
  .command("sessions")
  .description("List previous sessions")
  .action(sessionsCommand);

// Default command: chat
program
  .action(() => chatCommand({}));

program.parse();
