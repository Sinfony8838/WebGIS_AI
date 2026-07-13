import type { Tool, ToolContext, ToolResult } from "../tool.js";

const MAX_BODY_CHARS = 10000;

export const webFetchTool: Tool = {
  name: "web_fetch",
  description:
    "Fetch a URL and return its content as markdown. " +
    "Useful for reading documentation, API responses, or web pages.",
  parameters: {
    type: "object",
    properties: {
      url: { type: "string", description: "The URL to fetch" },
      prompt: { type: "string", description: "What to extract from the page (optional)" },
    },
    required: ["url"],
  },

  isReadOnly: () => true,
  requiresConfirmation: () => false,

  async execute(args, _ctx: ToolContext): Promise<ToolResult> {
    const url = args.url as string;

    try {
      const response = await fetch(url, {
        headers: {
          "User-Agent": "WebGIS-Agent/1.0",
          Accept: "text/html,application/xhtml+xml,text/plain,application/json,*/*",
        },
        signal: AbortSignal.timeout(30_000),
      });

      if (!response.ok) {
        return { output: `HTTP ${response.status}: ${response.statusText}`, isError: true };
      }

      const contentType = response.headers.get("content-type") ?? "";
      const body = await response.text();

      let markdown: string;

      if (contentType.includes("json")) {
        // Pretty-print JSON
        try {
          const parsed = JSON.parse(body);
          markdown = "```json\n" + JSON.stringify(parsed, null, 2).slice(0, MAX_BODY_CHARS) + "\n```";
        } catch {
          markdown = body.slice(0, MAX_BODY_CHARS);
        }
      } else if (contentType.includes("html")) {
        markdown = htmlToMarkdown(body).slice(0, MAX_BODY_CHARS);
      } else {
        markdown = body.slice(0, MAX_BODY_CHARS);
      }

      if (body.length > MAX_BODY_CHARS) {
        markdown += `\n\n[Content truncated, ${body.length} chars total]`;
      }

      return { output: markdown };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { output: `Error fetching ${url}: ${msg}`, isError: true };
    }
  },
};

/** Simple HTML-to-markdown converter */
function htmlToMarkdown(html: string): string {
  let text = html;

  // Remove script and style
  text = text.replace(/<script[\s\S]*?<\/script>/gi, "");
  text = text.replace(/<style[\s\S]*?<\/style>/gi, "");

  // Headings
  text = text.replace(/<h1[^>]*>(.*?)<\/h1>/gi, "\n# $1\n");
  text = text.replace(/<h2[^>]*>(.*?)<\/h2>/gi, "\n## $1\n");
  text = text.replace(/<h3[^>]*>(.*?)<\/h3>/gi, "\n### $1\n");
  text = text.replace(/<h[4-6][^>]*>(.*?)<\/h[4-6]>/gi, "\n#### $1\n");

  // Bold / Italic
  text = text.replace(/<(strong|b)>(.*?)<\/(strong|b)>/gi, "**$2**");
  text = text.replace(/<(em|i)>(.*?)<\/(em|i)>/gi, "*$2*");

  // Links
  text = text.replace(/<a[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/gi, "[$2]($1)");

  // Paragraphs and breaks
  text = text.replace(/<br\s*\/?>/gi, "\n");
  text = text.replace(/<\/p>/gi, "\n\n");
  text = text.replace(/<\/div>/gi, "\n");
  text = text.replace(/<\/li>/gi, "\n");
  text = text.replace(/<li[^>]*>/gi, "- ");

  // Code blocks
  text = text.replace(/<pre[^>]*><code[^>]*>([\s\S]*?)<\/code><\/pre>/gi, "\n```\n$1\n```\n");
  text = text.replace(/<code[^>]*>(.*?)<\/code>/gi, "`$1`");

  // Remove remaining tags
  text = text.replace(/<[^>]+>/g, "");

  // Decode common entities
  text = text.replace(/&amp;/g, "&");
  text = text.replace(/&lt;/g, "<");
  text = text.replace(/&gt;/g, ">");
  text = text.replace(/&quot;/g, '"');
  text = text.replace(/&#39;/g, "'");
  text = text.replace(/&nbsp;/g, " ");

  // Clean up whitespace
  text = text.replace(/\n{3,}/g, "\n\n");
  return text.trim();
}
