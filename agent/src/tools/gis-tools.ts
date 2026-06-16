import type { Tool, ToolContext, ToolResult } from "../tool.js";

// ─── Backend HTTP helper ──────────────────────────────────────────────────

async function backendFetch(
  path: string,
  backendUrl: string,
  options: RequestInit = {},
): Promise<unknown> {
  const url = `${backendUrl.replace(/\/+$/, "")}${path}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string> ?? {}),
    },
    signal: AbortSignal.timeout(30_000),
  });

  const body = await response.text();
  if (!response.ok) {
    throw new Error(`Backend ${response.status}: ${body.slice(0, 500)}`);
  }

  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

function jsonBody(data: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(data) };
}

function formatResult(data: unknown): string {
  if (typeof data === "string") return data;
  return JSON.stringify(data, null, 2).slice(0, 5000);
}

// ─── GIS Tools ────────────────────────────────────────────────────────────

export const gisHealthTool: Tool = {
  name: "gis_health",
  description: "Check if the WebGIS backend is running and healthy.",
  parameters: { type: "object", properties: {}, required: [] },
  isReadOnly: () => true,
  requiresConfirmation: () => false,
  async execute(_args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch("/health", ctx.backendUrl);
      return { output: `Backend healthy: ${formatResult(data)}` };
    } catch (err: unknown) {
      return { output: `Backend unreachable: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisListProjectsTool: Tool = {
  name: "gis_list_projects",
  description: "List all GIS projects on the backend.",
  parameters: { type: "object", properties: {}, required: [] },
  isReadOnly: () => true,
  requiresConfirmation: () => false,
  async execute(_args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch("/projects", ctx.backendUrl);
      return { output: formatResult(data) };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisCreateProjectTool: Tool = {
  name: "gis_create_project",
  description: "Create a new GIS project.",
  parameters: {
    type: "object",
    properties: {
      name: { type: "string", description: "Project name" },
    },
    required: [],
  },
  isReadOnly: () => false,
  requiresConfirmation: () => false,
  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch("/projects", ctx.backendUrl, jsonBody({ name: args.name || "", metadata: {} }));
      return { output: `Project created: ${formatResult(data)}` };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisGetProjectTool: Tool = {
  name: "gis_get_project",
  description: "Get details of a specific GIS project.",
  parameters: {
    type: "object",
    properties: {
      project_id: { type: "string", description: "Project ID" },
    },
    required: ["project_id"],
  },
  isReadOnly: () => true,
  requiresConfirmation: () => false,
  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch(`/projects/${args.project_id}`, ctx.backendUrl);
      return { output: formatResult(data) };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisListLayersTool: Tool = {
  name: "gis_list_layers",
  description: "List layers in a GIS project.",
  parameters: {
    type: "object",
    properties: {
      project_id: { type: "string", description: "Project ID" },
    },
    required: ["project_id"],
  },
  isReadOnly: () => true,
  requiresConfirmation: () => false,
  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch(`/layers?project_id=${args.project_id}`, ctx.backendUrl);
      return { output: formatResult(data) };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisSubmitWorkflowTool: Tool = {
  name: "gis_submit_workflow",
  description: "Submit a GIS analysis workflow (buffer, choropleth, clip, etc.).",
  parameters: {
    type: "object",
    properties: {
      project_id: { type: "string", description: "Project ID" },
      message: { type: "string", description: "Natural language description of the workflow" },
      mode: { type: "string", description: "Workflow mode: 'template' or 'custom'" },
      template_id: { type: "string", description: "Template ID (for template mode)" },
      parameters: { type: "object", description: "Workflow parameters" },
    },
    required: ["project_id"],
  },
  isReadOnly: () => false,
  requiresConfirmation: () => false,
  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch("/workflow/submit", ctx.backendUrl, jsonBody({
        project_id: args.project_id,
        message: args.message || "",
        mode: args.mode || "template",
        template_id: args.template_id || "",
        parameters: args.parameters || {},
      }));
      return { output: `Workflow submitted: ${formatResult(data)}` };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisWorkflowStatusTool: Tool = {
  name: "gis_workflow_status",
  description: "Get the status of a submitted workflow.",
  parameters: {
    type: "object",
    properties: {
      workflow_id: { type: "string", description: "Workflow ID" },
    },
    required: ["workflow_id"],
  },
  isReadOnly: () => true,
  requiresConfirmation: () => false,
  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch(`/workflow/${args.workflow_id}`, ctx.backendUrl);
      return { output: formatResult(data) };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisListTemplatesTool: Tool = {
  name: "gis_list_templates",
  description: "List available GIS workflow templates.",
  parameters: { type: "object", properties: {}, required: [] },
  isReadOnly: () => true,
  requiresConfirmation: () => false,
  async execute(_args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch("/workflow/templates", ctx.backendUrl);
      return { output: formatResult(data) };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisSearchPoiTool: Tool = {
  name: "gis_search_poi",
  description: "Search for points of interest (POI) by keyword.",
  parameters: {
    type: "object",
    properties: {
      project_id: { type: "string", description: "Project ID" },
      keyword: { type: "string", description: "Search keyword (e.g. '学校', '医院')" },
      mode: { type: "string", description: "Search mode: 'view' (current view) or 'custom'" },
    },
    required: ["project_id", "keyword"],
  },
  isReadOnly: () => true,
  requiresConfirmation: () => false,
  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch("/search/poi", ctx.backendUrl, jsonBody({
        project_id: args.project_id,
        keyword: args.keyword,
        mode: args.mode || "view",
        extent: [],
        geometry: {},
      }));
      return { output: formatResult(data) };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisAskAssistantTool: Tool = {
  name: "gis_ask_assistant",
  description: "Send a message to the WebGIS AI assistant (for map operations, explanations, etc.).",
  parameters: {
    type: "object",
    properties: {
      project_id: { type: "string", description: "Project ID" },
      message: { type: "string", description: "Message to the assistant" },
      assistant_mode: { type: "string", description: "Mode: 'tool' or 'knowledge'" },
    },
    required: ["project_id", "message"],
  },
  isReadOnly: () => false,
  requiresConfirmation: () => false,
  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch("/assistant/messages", ctx.backendUrl, jsonBody({
        project_id: args.project_id,
        message: args.message,
        assistant_mode: args.assistant_mode || "tool",
        map_context: {},
        conversation_id: "",
        history: [],
        target: "cli",
        input_mode: "text",
      }));
      return { output: formatResult(data) };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisListCatalogTool: Tool = {
  name: "gis_list_catalog",
  description: "List available datasets in the OneMap catalog.",
  parameters: { type: "object", properties: {}, required: [] },
  isReadOnly: () => true,
  requiresConfirmation: () => false,
  async execute(_args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch("/datasets/catalog", ctx.backendUrl);
      return { output: formatResult(data) };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisAddCatalogLayerTool: Tool = {
  name: "gis_add_catalog_layer",
  description: "Add a dataset from the catalog to a project as a map layer.",
  parameters: {
    type: "object",
    properties: {
      project_id: { type: "string", description: "Project ID" },
      dataset_id: { type: "string", description: "Dataset ID from the catalog" },
    },
    required: ["project_id", "dataset_id"],
  },
  isReadOnly: () => false,
  requiresConfirmation: () => false,
  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const data = await backendFetch("/datasets/catalog/layers", ctx.backendUrl, jsonBody({
        project_id: args.project_id,
        dataset_id: args.dataset_id,
      }));
      return { output: `Layer added: ${formatResult(data)}` };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

export const gisKbSearchTool: Tool = {
  name: "gis_kb_search",
  description: "Search the geography knowledge base.",
  parameters: {
    type: "object",
    properties: {
      query: { type: "string", description: "Search query" },
      topic: { type: "string", description: "Filter by topic (optional)" },
      region: { type: "string", description: "Filter by region (optional)" },
    },
    required: ["query"],
  },
  isReadOnly: () => true,
  requiresConfirmation: () => false,
  async execute(args, ctx: ToolContext): Promise<ToolResult> {
    try {
      const params = new URLSearchParams();
      if (args.query) params.set("query", String(args.query));
      if (args.topic) params.set("topic", String(args.topic));
      if (args.region) params.set("region", String(args.region));
      const data = await backendFetch(`/kb/search?${params}`, ctx.backendUrl);
      return { output: formatResult(data) };
    } catch (err: unknown) {
      return { output: `Error: ${err instanceof Error ? err.message : String(err)}`, isError: true };
    }
  },
};

/** All GIS tools as an array */
export const allGisTools: Tool[] = [
  gisHealthTool,
  gisListProjectsTool,
  gisCreateProjectTool,
  gisGetProjectTool,
  gisListLayersTool,
  gisSubmitWorkflowTool,
  gisWorkflowStatusTool,
  gisListTemplatesTool,
  gisSearchPoiTool,
  gisAskAssistantTool,
  gisListCatalogTool,
  gisAddCatalogLayerTool,
  gisKbSearchTool,
];
