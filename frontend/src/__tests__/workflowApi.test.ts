import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildWorkflowFileUrl,
  buildWorkflowStreamUrl,
  fetchWorkflow,
  fetchWorkflowArtifacts,
  fetchWorkflowHistory,
  getApiBase,
  listWorkflowTemplates,
  submitWorkflow
} from "../api";

const ORIGINAL_FETCH = global.fetch;

beforeEach(() => {
  global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    return new Response(
      JSON.stringify({ ok: true, url: typeof input === "string" ? input : input.toString(), method: init?.method || "GET", body: init?.body || "" }),
      {
        status: 200,
        headers: { "Content-Type": "application/json" }
      }
    );
  }) as unknown as typeof global.fetch;
});

afterEach(() => {
  global.fetch = ORIGINAL_FETCH;
});

describe("workflow API helpers", () => {
  it("submitWorkflow posts JSON with the expected payload shape", async () => {
    const response = await submitWorkflow({
      project_id: "p1",
      message: "demo",
      template_id: "population_choropleth",
      parameters: { dataset: "x.geojson" }
    });
    expect(response).toBeDefined();
    expect(global.fetch).toHaveBeenCalled();
    const callArgs = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(callArgs[0]).toContain("/workflow/submit");
    const init = callArgs[1] as RequestInit;
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.project_id).toBe("p1");
    expect(body.template_id).toBe("population_choropleth");
    expect(body.parameters.dataset).toBe("x.geojson");
  });

  it("fetchWorkflow encodes ids", async () => {
    await fetchWorkflow("wf abc");
    const url = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("/workflow/wf%20abc");
  });

  it("fetchWorkflowArtifacts hits the artifacts route", async () => {
    await fetchWorkflowArtifacts("wf123");
    const url = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("/workflow/wf123/artifacts");
  });

  it("fetchWorkflowHistory adds the project_id query when provided", async () => {
    await fetchWorkflowHistory("p9");
    const url = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("/workflow/history?project_id=p9");
  });

  it("listWorkflowTemplates uses the templates endpoint", async () => {
    await listWorkflowTemplates();
    const url = (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("/workflow/templates");
  });

  it("buildWorkflowStreamUrl produces an SSE URL", () => {
    const url = buildWorkflowStreamUrl("wf42");
    expect(url.startsWith(getApiBase())).toBe(true);
    expect(url).toContain("/workflow/wf42/stream");
  });

  it("buildWorkflowFileUrl preserves absolute URLs and prefixes relative ones", () => {
    expect(buildWorkflowFileUrl("https://cdn.example/foo.geojson")).toBe("https://cdn.example/foo.geojson");
    const url = buildWorkflowFileUrl("/workflow-files/wf1/outputs/x.geojson");
    expect(url.startsWith(getApiBase())).toBe(true);
    expect(url.endsWith("/workflow-files/wf1/outputs/x.geojson")).toBe(true);
  });
});
