import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addCatalogDatasetLayer,
  confirmAssistantAction,
  fetchDatasetCatalog,
  fetchKbManifest,
  fetchKbTopics,
  fetchPopulationSources,
  preparePopulationLesson,
  generateImageLibraryAsset,
  logSessionEvent,
  registerKbLayer,
  resolvePopulationLessonPrep,
  searchKb,
  sendAssistantMessage,
  summarizeCatalogLayers,
  uploadImageLibraryAsset,
  upsertKbItem
} from "../api";

describe("api.sendAssistantMessage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends voice input mode in the assistant request body", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job_id: "job_voice_1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await sendAssistantMessage(
      "project_1",
      "我们把目光转向上海区域",
      {
        center: [104, 35],
        zoom: 4,
        extent: [78, 18, 132, 50],
        visible_layers: [],
        recent_actions: []
      },
      "webgis",
      "voice"
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.method).toBe("POST");
    expect(String(init?.body)).toContain('"input_mode":"voice"');
  });

  it("sends teaching mode and conversation history in v2 requests", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job_id: "job_tool_1", conversation_id: "conv_1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await sendAssistantMessage(
      "project_1",
      "切换底图并解释",
      {
        center: [104, 35],
        zoom: 4,
        extent: [78, 18, 132, 50],
        visible_layers: [],
        recent_actions: []
      },
      "webgis",
      "text",
      {
        assistantMode: "teaching",
        conversationId: "conv_existing",
        history: [{ role: "user", text: "上一条消息", timestamp: "1" }]
      }
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(String(init?.body)).toContain('"assistant_mode":"teaching"');
    expect(String(init?.body)).toContain('"conversation_id":"conv_existing"');
    expect(String(init?.body)).toContain("上一条消息");
  });

  it("does not export the deleted coding-agent client", async () => {
    const apiModule = await import("../api");
    expect("sendAgentMessage" in apiModule).toBe(false);
    expect("AgentChatResponse" in apiModule).toBe(false);
  });

  it("sends teaching_context so the agent knows lesson/session/stage/phase", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job_id: "job_ctx_1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await sendAssistantMessage(
      "project_1",
      "点评一下刚才的投票",
      {
        center: [104, 35],
        zoom: 4,
        extent: [78, 18, 132, 50],
        visible_layers: [],
        recent_actions: []
      },
      "webgis",
      "text",
      {
        assistantMode: "teaching",
        teachingContext: { lesson_id: "lesson_1", session_id: "session_1", stage_id: "s3", phase: "in_class" }
      }
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(String(init?.body)).toContain(
      '"teaching_context":{"lesson_id":"lesson_1","session_id":"session_1","stage_id":"s3","phase":"in_class"}'
    );
  });

  it("falls back to map_context.teaching_context when options omit it", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job_id: "job_ctx_2" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await sendAssistantMessage("project_1", "什么是胡焕庸线", {
      center: [104, 35],
      zoom: 4,
      extent: [78, 18, 132, 50],
      visible_layers: [],
      recent_actions: [],
      teaching_context: { lesson_id: "lesson_1", phase: "course_prep" }
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(String(init?.body)).toContain('"teaching_context":{"lesson_id":"lesson_1","phase":"course_prep"}');
  });

  it("sends screen snapshot in assistant request body", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job_id: "job_screen_1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await sendAssistantMessage(
      "project_1",
      "读图讲解",
      {
        center: [121.47, 31.23],
        zoom: 9,
        extent: [120, 30, 122, 32],
        visible_layers: [],
        recent_actions: []
      },
      "webgis",
      "text",
      {
        assistantMode: "teaching",
        screenSnapshot: {
          image_data_url: "data:image/png;base64,AAAA",
          width: 1920,
          height: 1080,
          captured_at: "2026-04-28T00:00:00.000Z"
        }
      }
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(String(init?.body)).toContain('"screen_snapshot"');
    expect(String(init?.body)).toContain('"width":1920');
  });

  it("sends only an artifact id for an assistant image attachment", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job_id: "job_image_1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await sendAssistantMessage(
      "project_1",
      "这条河流有什么特征？",
      { center: [104, 35], zoom: 4, extent: [78, 18, 132, 50], visible_layers: [], recent_actions: [] },
      "webgis",
      "text",
      { imageAttachments: [{ artifact_id: "artifact_1" }] }
    );

    const [, init] = fetchMock.mock.calls[0];
    const body = String(init?.body);
    expect(body).toContain('"image_attachments":[{"artifact_id":"artifact_1"}]');
    expect(body).not.toContain("base64");
  });

  it("uploads an image to the project image library", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ artifact: { artifact_id: "artifact_1" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    const file = new File(["png"], "map.png", { type: "image/png" });
    await uploadImageLibraryAsset("project_1", file, "地图");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/image-library/upload");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get("project_id")).toBe("project_1");
    expect((init?.body as FormData).get("file")).toBe(file);
  });

  it("requests MiniMax image generation with project-scoped options", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ artifact: { artifact_id: "generated_1" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await generateImageLibraryAsset("project_1", "水循环示意图", {
      model: "image-01",
      aspectRatio: "4:3"
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/image-generation");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toMatchObject({
      project_id: "project_1",
      prompt: "水循环示意图",
      model: "image-01",
      aspect_ratio: "4:3",
      prompt_optimizer: true,
      confirmed: true
    });
  });

  it("posts assistant confirmation ids and decisions", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job_id: "job_confirm_1", confirmation_id: "confirm_1", decision: "reject" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await confirmAssistantAction("confirm_1", "reject");
    const [url, init] = fetchMock.mock.calls[0];

    expect(String(url)).toContain("/assistant/confirm");
    expect(String(init?.body)).toContain('"confirmation_id":"confirm_1"');
    expect(String(init?.body)).toContain('"decision":"reject"');
  });

  it("records a snapshot artifact in the classroom event stream", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ status: "success" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    await logSessionEvent("session_1", { event_type: "snapshot", stage_id: "s2", payload: { artifact_id: "snapshot_1" } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/class-sessions/session_1/events");
    expect(JSON.parse(String(init?.body))).toMatchObject({ event_type: "snapshot", stage_id: "s2", payload: { artifact_id: "snapshot_1" } });
  });

  it("requests kb manifest from /kb/manifest", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await fetchKbManifest();
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/kb/manifest");
  });

  it("requests one-map dataset catalog from /datasets/catalog", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await fetchDatasetCatalog();
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/datasets/catalog");
  });

  it("uses teacher-only population source and lesson-prep endpoints", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ status: "success", items: [], job_id: "job_prep_1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await fetchPopulationSources("project_1");
    await preparePopulationLesson("project_1", "lesson_1", {
      objective: "解释中国人口分布",
      grade: "高一",
      duration_minutes: 40,
      region: "中国"
    });
    await resolvePopulationLessonPrep("job_prep_1", "apply", ["s4"]);

    expect(String(fetchMock.mock.calls[0][0])).toContain("/population-sources?project_id=project_1");
    expect(String(fetchMock.mock.calls[1][0])).toContain("/lesson-prep/population");
    expect(String(fetchMock.mock.calls[1][1]?.body)).toContain('"lesson_id":"lesson_1"');
    expect(String(fetchMock.mock.calls[2][0])).toContain("/lesson-prep/change-sets/job_prep_1/resolve");
    expect(String(fetchMock.mock.calls[2][1]?.body)).toContain('"accepted_stage_ids":["s4"]');
  });

  it("loads one-map catalog datasets as map layers", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", layer: { layer_id: "one_map_world" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await addCatalogDatasetLayer("project_1", "world_population_density");
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/datasets/catalog/layers");
    expect(init?.method).toBe("POST");
    expect(String(init?.body)).toContain('"project_id":"project_1"');
    expect(String(init?.body)).toContain('"dataset_id":"world_population_density"');
  });

  it("posts selection geometry for one-map statistics", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", layers: [], totals: { matched_count: 0 } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await summarizeCatalogLayers("project_1", { type: "Polygon", coordinates: [] });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/datasets/catalog/statistics");
    expect(init?.method).toBe("POST");
    expect(String(init?.body)).toContain('"project_id":"project_1"');
    expect(String(init?.body)).toContain('"type":"Polygon"');
  });

  it("requests kb topic summaries from /kb/topics", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await fetchKbTopics();
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/kb/topics");
  });

  it("builds kb search query string", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", total: 0, items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await searchKb({ query: "港口", topic: "population", region: "china", tag: "交通", limit: 12 });
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/kb/search?");
    expect(String(url)).toContain("query=%E6%B8%AF%E5%8F%A3");
    expect(String(url)).toContain("topic=population");
    expect(String(url)).toContain("region=china");
    expect(String(url)).toContain("tag=%E4%BA%A4%E9%80%9A");
    expect(String(url)).toContain("limit=12");
  });

  it("posts kb item payload through /kb/items", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", item: { id: "ports" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await upsertKbItem({ id: "ports", title: "港口分布" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/kb/items");
    expect(String(init?.body)).toContain('"id":"ports"');
    expect(String(init?.body)).toContain('"title":"港口分布"');
  });

  it("registers active layer with kb metadata", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "success", item: { id: "ports" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await registerKbLayer("project_1", "layer_1", { topic: "shipping" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/kb/layers/register");
    expect(String(init?.body)).toContain('"project_id":"project_1"');
    expect(String(init?.body)).toContain('"layer_id":"layer_1"');
    expect(String(init?.body)).toContain('"topic":"shipping"');
  });
});


it("preserves HTTP status for distinguishing missing jobs from temporary service failures", async () => {
  const { fetchJob, ApiError } = await import("../api");
  const mock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Job not found" }), { status: 404 }));
  try {
    await expect(fetchJob("missing")).rejects.toBeInstanceOf(ApiError);
    mock.mockResolvedValue(new Response(JSON.stringify({ detail: "Service unavailable" }), { status: 503 }));
    await expect(fetchJob("running")).rejects.toMatchObject({ status: 503 });
  } finally { mock.mockRestore(); }
});


it("submits practice generation as a background task with the exact selected IDs", async () => {
  const { submitSessionPracticeExport } = await import("../api");
  const mock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ status: "accepted", job_id: "paper", session_id: "s1" }), { status: 200 }));
  try {
    await submitSessionPracticeExport("s1", { token: "selection", selected_ids: ["q1"] });
    expect(mock.mock.calls[0][0]).toMatch(/practice-export\?background=true$/);
    expect(mock.mock.calls[0][1]?.body).toBe(JSON.stringify({ token: "selection", selected_ids: ["q1"] }));
    expect(new Headers(mock.mock.calls[0][1]?.headers).get("Content-Type")).toBe("application/json");
  } finally { mock.mockRestore(); }
});
