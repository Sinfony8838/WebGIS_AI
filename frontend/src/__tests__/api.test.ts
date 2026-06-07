import { afterEach, describe, expect, it, vi } from "vitest";
import {
  confirmAssistantAction,
  fetchKbManifest,
  fetchKbTopics,
  registerKbLayer,
  searchKb,
  sendAssistantMessage,
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

  it("sends assistant mode and conversation history in v2 requests", async () => {
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
        assistantMode: "tool",
        conversationId: "conv_existing",
        history: [{ role: "user", text: "上一条消息", timestamp: "1" }]
      }
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(String(init?.body)).toContain('"assistant_mode":"tool"');
    expect(String(init?.body)).toContain('"conversation_id":"conv_existing"');
    expect(String(init?.body)).toContain("上一条消息");
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
        assistantMode: "knowledge",
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
