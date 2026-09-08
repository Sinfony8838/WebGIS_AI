import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { fetchWorkflow } from "../api";
import { useWorkflowStream } from "../hooks/useWorkflowStream";
import type { WorkflowRecord } from "../types";

vi.mock("../api", () => ({
  fetchWorkflow: vi.fn(),
  fetchCurrentUser: vi.fn().mockResolvedValue({}),
  buildWorkflowStreamUrl: (id: string) => `/workflow/${id}/stream`
}));

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners = new Map<string, (event: { data: string }) => void>();
  close = vi.fn();
  onerror: (() => void) | null = null;
  constructor() { FakeEventSource.instances.push(this); }
  addEventListener(type: string, listener: (event: { data: string }) => void) {
    this.listeners.set(type, listener);
  }
  emit(type: string, payload: object) {
    this.listeners.get(type)?.({ data: JSON.stringify(payload) });
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

function record(id = "wf1"): WorkflowRecord {
  return {
    workflow_id: id, project_id: "p1", user_message: "", intent: "人口分析",
    template_id: "", mode: "", workflow_json: {}, status: "running",
    steps: [], artifacts: [], error: null, created_at: "", updated_at: "",
    started_at: "", finished_at: ""
  };
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it("keeps a completed stream result when an older HTTP snapshot arrives later", async () => {
  const snapshot = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockReturnValue(snapshot.promise);
  const { result } = renderHook(() => useWorkflowStream("wf1"));
  const source = FakeEventSource.instances[0];
  const step = { id: "s1", op: "load_layer", status: "success", outputs: {}, error: null, started_at: "", finished_at: "" };
  const artifact = { artifact_id: "a1", workflow_id: "wf1", kind: "geojson", title: "结果", relative_path: "result.json", public_url: "/result.json", metadata: {}, created_at: "" };
  act(() => source.emit("workflow_success", {
    workflow_id: "wf1", workflow: { ...record(), status: "success", steps: [step] }, artifacts: [artifact]
  }));
  await act(async () => snapshot.resolve(record()));
  expect(result.current.status).toBe("success");
  expect(result.current.steps).toEqual([step]);
  expect(result.current.artifacts).toEqual([artifact]);
  expect(source.close).toHaveBeenCalledOnce();
});

it("hydrates historical steps while retaining newer stream updates", async () => {
  const snapshot = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockReturnValue(snapshot.promise);
  const { result } = renderHook(() => useWorkflowStream("wf1"));
  const base = record();
  const oldStep = { id: "s1", op: "load_layer", status: "success" as const, outputs: {}, error: null, started_at: "", finished_at: "" };
  const newStep = { ...oldStep, id: "s2", op: "buffer" };
  base.steps = [oldStep];
  act(() => FakeEventSource.instances[0].emit("step_success", { workflow_id: "wf1", step: newStep }));
  await act(async () => snapshot.resolve(base));
  expect(result.current.intent).toBe("人口分析");
  expect(result.current.steps).toEqual([oldStep, newStep]);
});

it("does not let delayed callbacks from the previous workflow affect the next one", async () => {
  const first = deferred<WorkflowRecord>();
  const second = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const { result, rerender } = renderHook(({ id }) => useWorkflowStream(id), { initialProps: { id: "wf1" } });
  const oldSource = FakeEventSource.instances[0];
  rerender({ id: "wf2" });
  act(() => oldSource.emit("workflow_success", { workflow: { status: "success" } }));
  await act(async () => first.resolve(record("wf1")));
  expect(result.current.workflowId).toBe("wf2");
  expect(result.current.status).toBe("pending");
  await act(async () => second.resolve(record("wf2")));
  expect(result.current.status).toBe("running");
});

it("continues receiving events if the initial HTTP request fails", async () => {
  const snapshot = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockReturnValue(snapshot.promise);
  const { result } = renderHook(() => useWorkflowStream("wf1"));
  await act(async () => snapshot.reject(new Error("offline")));
  act(() => FakeEventSource.instances[0].emit("workflow_error", { workflow_id: "wf1", error: { code: "FAILED" } }));
  expect(result.current.status).toBe("error");
  expect(result.current.error?.code).toBe("FAILED");
});
