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
  constructor(public url = "") { FakeEventSource.instances.push(this); }
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
  vi.clearAllTimers();
  vi.useRealTimers();
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

it("shows a cancelled run as cancelled when the terminal event carries the record", async () => {
  const snapshot = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockReturnValue(snapshot.promise);
  const { result } = renderHook(() => useWorkflowStream("wf1"));
  await act(async () => snapshot.resolve(record("wf1")));
  act(() => FakeEventSource.instances[0].emit("workflow_error", {
    workflow_id: "wf1",
    error: { code: "STEP_CANCELLED", message: "cancelled", user_friendly: "已取消本次分析。" },
    workflow: { ...record("wf1"), status: "cancelled" }
  }));
  expect(result.current.status).toBe("cancelled");
  expect(result.current.error?.code).toBe("STEP_CANCELLED");
});

it("reconciles an idle stream and reconnects only the original running workflow", async () => {
  vi.useFakeTimers();
  const recovery = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockResolvedValueOnce(record()).mockReturnValueOnce(recovery.promise);
  const { result } = renderHook(() => useWorkflowStream("wf1", "p1"));
  await act(async () => {});
  const first = FakeEventSource.instances[0];
  act(() => first.emit("stream_idle_timeout", { workflow_id: "wf1" }));
  expect(first.close).toHaveBeenCalledOnce();
  expect(result.current.status).toBe("running");
  expect(fetchWorkflow).toHaveBeenCalledTimes(2);
  await act(async () => recovery.resolve(record()));
  expect(FakeEventSource.instances).toHaveLength(2);
  expect(FakeEventSource.instances[1].url).toBe("/workflow/wf1/stream");
  expect(vi.mocked(fetchWorkflow).mock.calls.every(([id]) => id === "wf1")).toBe(true);
});

it("recovers the complete cancelled record after idle timeout without reopening", async () => {
  vi.useFakeTimers();
  const cancelled = { ...record(), status: "cancelled" as const,
    steps: [{ id: "s1", op: "buffer", status: "error" as const, outputs: {}, error: null, started_at: "", finished_at: "done" }],
    artifacts: [{ artifact_id: "retained", workflow_id: "wf1", kind: "geojson", title: "retained", relative_path: "a.json", public_url: "/a.json", metadata: {}, created_at: "" }],
    error: { code: "STEP_CANCELLED", message: "cancelled", user_friendly: "已取消" } };
  vi.mocked(fetchWorkflow).mockResolvedValueOnce(record()).mockResolvedValueOnce(cancelled);
  const { result } = renderHook(() => useWorkflowStream("wf1"));
  await act(async () => {});
  await act(async () => FakeEventSource.instances[0].emit("stream_idle_timeout", { workflow_id: "wf1" }));
  expect(result.current.status).toBe("cancelled");
  expect(result.current.steps).toEqual(cancelled.steps);
  expect(result.current.artifacts).toEqual(cancelled.artifacts);
  await act(async () => vi.advanceTimersByTimeAsync(30000));
  expect(fetchWorkflow).toHaveBeenCalledTimes(2);
  expect(FakeEventSource.instances).toHaveLength(1);
});

it("polls through a disconnected GET failure and stops when the original task completes", async () => {
  vi.useFakeTimers();
  vi.mocked(fetchWorkflow).mockResolvedValueOnce(record()).mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ ...record(), status: "success" });
  const { result } = renderHook(() => useWorkflowStream("wf1"));
  await act(async () => {});
  await act(async () => FakeEventSource.instances[0].onerror?.());
  expect(result.current.status).toBe("running");
  await act(async () => vi.advanceTimersByTimeAsync(3000));
  expect(result.current.status).toBe("success");
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(fetchWorkflow).toHaveBeenCalledTimes(3);
  expect(FakeEventSource.instances).toHaveLength(1);
});

it("does not issue overlapping recovery queries on repeated errors", async () => {
  vi.useFakeTimers();
  const pending = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockResolvedValueOnce(record()).mockReturnValueOnce(pending.promise);
  renderHook(() => useWorkflowStream("wf1"));
  await act(async () => {});
  const source = FakeEventSource.instances[0];
  act(() => { source.onerror?.(); source.onerror?.(); });
  await act(async () => vi.advanceTimersByTimeAsync(10000));
  expect(fetchWorkflow).toHaveBeenCalledTimes(2);
  await act(async () => pending.resolve({ ...record(), status: "error" }));
});

it("aborts a hung snapshot and rejects its late result after the next query", async () => {
  vi.useFakeTimers();
  const hung = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockReturnValueOnce(hung.promise).mockResolvedValueOnce(record());
  const { result } = renderHook(() => useWorkflowStream("wf1"));
  const signal = vi.mocked(fetchWorkflow).mock.calls[0][1];
  await act(async () => vi.advanceTimersByTimeAsync(18000));
  expect(signal?.aborted).toBe(true);
  expect(fetchWorkflow).toHaveBeenCalledTimes(2);
  expect(result.current.status).toBe("running");
  await act(async () => hung.resolve({ ...record(), status: "success" }));
  expect(result.current.status).toBe("running");
});

it("aborts the pending request and polling timer when unmounted", async () => {
  vi.useFakeTimers();
  const pending = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockReturnValueOnce(pending.promise);
  const { unmount } = renderHook(() => useWorkflowStream("wf1"));
  const signal = vi.mocked(fetchWorkflow).mock.calls[0][1];
  unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(fetchWorkflow).toHaveBeenCalledOnce();
  expect(FakeEventSource.instances[0].close).toHaveBeenCalledOnce();
});

it("rejects HTTP and nested stream records from another project", async () => {
  const pending = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockReturnValueOnce(pending.promise);
  const { result } = renderHook(() => useWorkflowStream("wf1", "p1"));
  act(() => FakeEventSource.instances[0].emit("workflow_success", { workflow: { ...record(), project_id: "p2", status: "success" } }));
  expect(result.current.status).toBe("pending");
  await act(async () => pending.resolve({ ...record(), project_id: "p2", artifacts: [{ artifact_id: "private" }] as never }));
  expect(result.current.artifacts).toEqual([]);
  expect(result.current.status).toBe("pending");
});

it("cleans up old project callbacks even when the workflow ID is unchanged", async () => {
  const first = deferred<WorkflowRecord>();
  const second = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const { result, rerender } = renderHook(({ project }) => useWorkflowStream("wf1", project), { initialProps: { project: "p1" } });
  const old = FakeEventSource.instances[0];
  const oldSignal = vi.mocked(fetchWorkflow).mock.calls[0][1];
  rerender({ project: "p2" });
  expect(oldSignal?.aborted).toBe(true);
  act(() => old.emit("workflow_success", { workflow_id: "wf1", workflow: { ...record(), status: "success" } }));
  await act(async () => first.resolve({ ...record(), status: "success" }));
  expect(result.current.status).toBe("pending");
  await act(async () => second.resolve({ ...record(), project_id: "p2" }));
  expect(result.current.status).toBe("running");
});

it("retains a terminal HTTP snapshot against buffered historical start events", async () => {
  const pending = deferred<WorkflowRecord>();
  vi.mocked(fetchWorkflow).mockReturnValueOnce(pending.promise);
  const { result } = renderHook(() => useWorkflowStream("wf1"));
  act(() => FakeEventSource.instances[0].emit("workflow_started", { workflow: record() }));
  await act(async () => pending.resolve({ ...record(), status: "success" }));
  expect(result.current.status).toBe("success");
});

it("restores full step and artifact state from a persisted terminal error event", async () => {
  vi.mocked(fetchWorkflow).mockResolvedValueOnce(record());
  const { result } = renderHook(() => useWorkflowStream("wf1"));
  await act(async () => {});
  const wf = { ...record(), status: "error", steps: [{ id: "active", status: "error" }],
    artifacts: [{ artifact_id: "retained" }], error: { code: "INTERNAL_ERROR" } };
  act(() => FakeEventSource.instances[0].emit("workflow_error", { workflow_id: "wf1", workflow: wf, error: wf.error }));
  expect(result.current.status).toBe("error");
  expect(result.current.steps).toEqual(wf.steps);
  expect(result.current.artifacts).toEqual(wf.artifacts);
});
