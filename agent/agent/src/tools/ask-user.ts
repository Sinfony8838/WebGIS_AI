import type { Tool, ToolContext, ToolResult } from "../tool.js";

export const askUserTool: Tool = {
  name: "ask_user",
  description:
    "Ask the user a question and wait for their response. " +
    "Use this when you need clarification, confirmation, or additional information from the user.",
  parameters: {
    type: "object",
    properties: {
      question: { type: "string", description: "The question to ask the user" },
    },
    required: ["question"],
  },

  isReadOnly: () => true,
  requiresConfirmation: () => false,

  async execute(args, _ctx: ToolContext): Promise<ToolResult> {
    const question = args.question as string;
    // The agent loop handles the actual prompting via callbacks.
    // This tool returns the question so the loop can display it.
    return { output: `[Question for user] ${question}` };
  },
};
