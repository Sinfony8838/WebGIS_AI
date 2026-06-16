import * as readline from "node:readline";
import chalk from "chalk";

const MAX_RESULT_PREVIEW = 500;

export class TUI {
  private rl: readline.Interface;

  constructor() {
    this.rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
      historySize: 100,
    });
  }

  showBanner(): void {
    console.log(
      chalk.cyan.bold("\n  WebGIS Agent") +
        chalk.gray(" v1.0.0") +
        chalk.dim(" - AI coding assistant for WebGIS-AI\n") +
        chalk.dim("  Type your message, or /help for commands. /quit to exit.\n"),
    );
  }

  async prompt(): Promise<string> {
    return new Promise((resolve) => {
      this.rl.question(chalk.cyan.bold("\n> "), (answer) => {
        resolve(answer.trim());
      });
    });
  }

  displayAssistantMessage(text: string): void {
    console.log("\n" + chalk.white(text));
  }

  displayProgress(text: string): void {
    console.log(chalk.dim(`  ${text}`));
  }

  displayToolCall(name: string, args: Record<string, unknown>): void {
    const argsStr = JSON.stringify(args);
    const shortArgs = argsStr.length > 120 ? argsStr.slice(0, 120) + "..." : argsStr;
    console.log(chalk.yellow(`  tool: ${name}(${shortArgs})`));
  }

  displayToolResult(name: string, output: string, isError: boolean): void {
    const color = isError ? chalk.red : chalk.green;
    const preview =
      output.length > MAX_RESULT_PREVIEW
        ? output.slice(0, MAX_RESULT_PREVIEW) + `... (${output.length} chars)`
        : output;
    const prefix = isError ? "  error:" : "  ok:";
    console.log(color(`${prefix} [${name}] ${preview}`));
  }

  displayStatus(msg: string): void {
    console.log(chalk.dim(`  ${msg}`));
  }

  displayError(msg: string): void {
    console.log(chalk.red(`  Error: ${msg}`));
  }

  async confirm(message: string): Promise<boolean> {
    return new Promise((resolve) => {
      this.rl.question(chalk.yellow(`  ${message} [y/N] `), (answer) => {
        resolve(answer.toLowerCase() === "y" || answer.toLowerCase() === "yes");
      });
    });
  }

  async ask(question: string): Promise<string> {
    return new Promise((resolve) => {
      this.rl.question(chalk.cyan(`  ${question}\n> `), (answer) => {
        resolve(answer.trim());
      });
    });
  }

  handleSlashCommand(input: string): string | null {
    const cmd = input.toLowerCase();

    if (cmd === "/quit" || cmd === "/exit" || cmd === "/q") {
      console.log(chalk.dim("\n  Goodbye!\n"));
      process.exit(0);
    }

    if (cmd === "/help") {
      console.log(chalk.cyan("\n  Commands:"));
      console.log(chalk.dim("  /help      Show this help"));
      console.log(chalk.dim("  /tools     List available tools"));
      console.log(chalk.dim("  /clear     Clear conversation history"));
      console.log(chalk.dim("  /quit      Exit the agent"));
      console.log(chalk.dim("  /compact   Force context compression"));
      return "help";
    }

    if (cmd === "/tools") {
      return "tools";
    }

    if (cmd === "/clear") {
      return "clear";
    }

    if (cmd === "/compact") {
      return "compact";
    }

    return null;
  }

  close(): void {
    this.rl.close();
  }
}
