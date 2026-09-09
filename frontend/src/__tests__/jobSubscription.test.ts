import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { subscribeJob } from "../lib/jobSubscription";
import { JobActivity } from "../lib/jobActivity";
import type { JobRecord } from "../types";

class Source {
  handlers = new Map<string, EventListener>();
  close = vi.fn();
  addEventListener(type: string, listener: EventListenerOrEventListenerObject) { this.handlers.set(type, listener as EventListener); }
  emit(type: string, data?: unknown) { this.handlers.get(type)?.({ data: typeof data === "string" ? data : JSON.stringify(data) } as MessageEvent); }
}
const job = (status: string, extra = {}): JobRecord => ({ job_id: "job-1", project_id: "project-1", job_type: "assistant", title: "探究", workflow_type: "assistant", status, updated_at: "", steps: [], stages: {}, ...extra });
function setup(fetchJob = vi.fn().mockResolvedValue(job("running"))) {
  const source = new Source();
  const activity = new JobActivity<ReturnType<typeof subscribeJob>>();
  const onJob = vi.fn((value: JobRecord) => { if (["completed", "failed"].includes(value.status)) activity.delete(handle); });
  const onRecovering = vi.fn();
  const handle = subscribeJob("job-1", { createSource: () => source, fetchJob, onJob, onRecovering });
  activity.add(handle, false);
  return { source, fetchJob, onJob, onRecovering, handle, activity };
}
beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });

it("keeps the original write job locked through stream expiry and delivers its result once", async () => {
  const ctx = setup(vi.fn().mockResolvedValueOnce(job("running")).mockResolvedValueOnce(job("completed")));
  ctx.source.emit("job", job("running"));
  ctx.source.emit("error");
  await vi.advanceTimersByTimeAsync(0);
  expect(ctx.activity.mapBusy).toBe(true);
  expect(ctx.fetchJob).toHaveBeenCalledWith("job-1", expect.any(AbortSignal));
  await vi.advanceTimersByTimeAsync(3000);
  expect(ctx.activity.busy).toBe(false);
  ctx.source.emit("job", job("completed"));
  await vi.advanceTimersByTimeAsync(60000);
  expect(ctx.onJob.mock.calls.filter(([value]) => value.status === "completed")).toHaveLength(1);
  expect(ctx.fetchJob).toHaveBeenCalledTimes(2);
  expect(ctx.onRecovering).toHaveBeenCalledTimes(1);
});

it("reconciles a silent stream without waiting forever for a terminal event", async () => {
  const ctx = setup(vi.fn().mockResolvedValue(job("completed")));
  await vi.advanceTimersByTimeAsync(15000);
  expect(ctx.onJob).toHaveBeenCalledWith(expect.objectContaining({ status: "completed" }));
  expect(ctx.source.close).toHaveBeenCalled();
  expect(ctx.activity.busy).toBe(false);
});

it("does not overwrite a newer stream update with an older in-flight GET", async () => {
  let resolve!: (value: JobRecord) => void;
  const ctx = setup(vi.fn(() => new Promise<JobRecord>(done => { resolve = done; })));
  await vi.advanceTimersByTimeAsync(15000);
  ctx.source.emit("job", job("running", { title: "最新阶段" }));
  resolve(job("queued", { title: "旧快照" }));
  await vi.advanceTimersByTimeAsync(0);
  expect(ctx.onJob).toHaveBeenCalledTimes(1);
  expect(ctx.onJob).toHaveBeenLastCalledWith(expect.objectContaining({ title: "最新阶段" }));
  ctx.handle.close();
});

it("treats malformed events and foreign job snapshots as recovery, not task completion", async () => {
  const ctx = setup(vi.fn().mockResolvedValueOnce(job("completed", { job_id: "other-job" })).mockResolvedValueOnce(job("failed")));
  ctx.source.emit("job", "bad json");
  await vi.advanceTimersByTimeAsync(0);
  expect(ctx.onJob).not.toHaveBeenCalled();
  expect(ctx.activity.busy).toBe(true);
  await vi.advanceTimersByTimeAsync(6000);
  expect(ctx.onJob).toHaveBeenCalledWith(expect.objectContaining({ job_id: "job-1", status: "failed" }));
  expect(ctx.activity.busy).toBe(false);
});

it("bounds status requests and aborts pending observation when the page closes", async () => {
  const fetchJob = vi.fn((_id: string, signal: AbortSignal) => new Promise<JobRecord>((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(new Error("aborted")));
  }));
  const ctx = setup(fetchJob);
  ctx.source.emit("error");
  await vi.advanceTimersByTimeAsync(10000);
  expect(fetchJob.mock.calls[0][1].aborted).toBe(true);
  expect(ctx.activity.busy).toBe(true);
  await vi.advanceTimersByTimeAsync(6000);
  expect(fetchJob).toHaveBeenCalledTimes(2);
  ctx.handle.close();
  expect(fetchJob.mock.calls[1][1].aborted).toBe(true);
  await vi.advanceTimersByTimeAsync(60000);
  expect(fetchJob).toHaveBeenCalledTimes(2);
  expect(ctx.onRecovering).toHaveBeenCalledTimes(1);
});

it("ignores a late GET after a terminal SSE event and cleans up its timer", async () => {
  let resolve!: (value: JobRecord) => void;
  const ctx = setup(vi.fn(() => new Promise<JobRecord>(done => { resolve = done; })));
  await vi.advanceTimersByTimeAsync(15000);
  ctx.source.emit("job", job("completed"));
  resolve(job("running"));
  await vi.advanceTimersByTimeAsync(60000);
  expect(ctx.onJob).toHaveBeenCalledTimes(1);
  expect(ctx.activity.busy).toBe(false);
  expect(ctx.fetchJob).toHaveBeenCalledTimes(1);
});


it("does not deliver results from another project when restoring a saved job", async () => {
  const source = new Source();
  const onJob = vi.fn();
  const fetchJob = vi.fn().mockResolvedValueOnce(job("completed", { project_id: "other-project" })).mockResolvedValueOnce(job("completed"));
  subscribeJob("job-1", { createSource: () => source, fetchJob, onJob, onRecovering: vi.fn(), projectId: "project-1", reconcileImmediately: true });
  await vi.advanceTimersByTimeAsync(0);
  expect(onJob).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(6000);
  expect(onJob).toHaveBeenCalledOnce();
});

it.each([403, 404])("stops observing an unavailable job after HTTP %s without reporting task completion", async (status) => {
  const source = new Source();
  const onJob = vi.fn();
  const onUnavailable = vi.fn();
  const fetchJob = vi.fn().mockRejectedValue(Object.assign(new Error("Unavailable"), { status }));
  subscribeJob("job-1", { createSource: () => source, fetchJob, onJob, onRecovering: vi.fn(), onUnavailable, reconcileImmediately: true });
  await vi.advanceTimersByTimeAsync(60000);
  expect(onJob).not.toHaveBeenCalled();
  expect(onUnavailable).toHaveBeenCalledOnce();
  expect(fetchJob).toHaveBeenCalledOnce();
  expect(source.close).toHaveBeenCalled();
});

it("keeps a job pending on service errors rather than treating an outage as disappearance", async () => {
  const source = new Source();
  const onUnavailable = vi.fn();
  const onJob = vi.fn();
  const fetchJob = vi.fn().mockRejectedValueOnce(Object.assign(new Error("Unavailable"), { status: 503 })).mockResolvedValueOnce(job("completed"));
  subscribeJob("job-1", { createSource: () => source, fetchJob, onJob, onRecovering: vi.fn(), onUnavailable, reconcileImmediately: true });
  await vi.advanceTimersByTimeAsync(0);
  expect(onUnavailable).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(6000);
  expect(onJob).toHaveBeenCalledWith(expect.objectContaining({ status: "completed" }));
});
