import { useEffect } from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { rememberPendingJob, readPendingJobs, forgetPendingJob } from "../lib/pendingJobs";
import { usePendingJobs } from "../hooks/usePendingJobs";
import { subscribeJob, type JobSubscription } from "../lib/jobSubscription";
import { fetchJob } from "../api";

beforeEach(() => { localStorage.clear(); vi.useFakeTimers(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

it("recovers the original job after remount and delivers the completed server result to its original tab", async () => {
  rememberPendingJob("teacher", "shanghai", { jobId: "job_1", tab: "interaction" });
  const server = { job_id: "job_1", project_id: "shanghai", status: "running", stages: {}, steps: [] };
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(server), { status: 200 }));
  const results: string[] = [];
  function usePage() {
    const handles: JobSubscription[] = [];
    usePendingJobs("teacher", "shanghai", pending => {
      handles.push(subscribeJob(pending.jobId, {
        createSource: () => ({ addEventListener: vi.fn(), close: vi.fn() }),
        fetchJob, projectId: "shanghai", reconcileImmediately: true, onRecovering: vi.fn(),
        onJob: value => {
          if (value.status === "completed") {
            results.push(`${pending.tab}:${value.job_id}`);
            forgetPendingJob("teacher", "shanghai", value.job_id);
          }
        }
      }));
    });
    useEffect(() => () => handles.forEach(handle => handle.close()), []);
  }
  const first = renderHook(usePage);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(readPendingJobs("teacher", "shanghai")).toHaveLength(1);
  first.unmount();
  server.status = "completed";
  const second = renderHook(usePage);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(results).toEqual(["interaction:job_1"]);
  expect(readPendingJobs("teacher", "shanghai")).toEqual([]);
  second.unmount();
  renderHook(usePage);
  await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
  expect(results).toHaveLength(1);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  for (const [url, init] of fetchMock.mock.calls) {
    expect(url).toMatch(/\/jobs\/job_1$/);
    expect(init?.method || "GET").toBe("GET");
  }
});

it("isolates accounts and projects and only resumes after the matching project loads", () => {
  rememberPendingJob("a", "p", { jobId: "job_a", tab: "teaching" });
  rememberPendingJob("b", "p", { jobId: "job_b", tab: "interaction" });
  const resume = vi.fn();
  const { rerender } = renderHook(({ user, project }) => usePendingJobs(user, project, resume), { initialProps: { user: "a", project: "" } });
  expect(resume).not.toHaveBeenCalled();
  rerender({ user: "a", project: "p" });
  expect(resume).toHaveBeenLastCalledWith({ jobId: "job_a", tab: "teaching" });
  rerender({ user: "a", project: "other" });
  expect(resume).toHaveBeenCalledTimes(1);
  rerender({ user: "b", project: "p" });
  expect(resume).toHaveBeenLastCalledWith({ jobId: "job_b", tab: "interaction" });
});

it("deduplicates pending IDs and tolerates damaged or blocked browser storage", () => {
  rememberPendingJob("a", "p", { jobId: "job_a", tab: "teaching" });
  rememberPendingJob("a", "p", { jobId: "job_a", tab: "interaction" });
  expect(readPendingJobs("a", "p")).toEqual([{ jobId: "job_a", tab: "interaction" }]);
  const key = localStorage.key(0)!;
  localStorage.setItem(key, JSON.stringify([{ jobId: "../../other", tab: "teaching" }, { jobId: "job_b", tab: "invalid" }]));
  expect(readPendingJobs("a", "p")).toEqual([]);
  localStorage.setItem(key, "broken");
  expect(readPendingJobs("a", "p")).toEqual([]);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
  expect(() => rememberPendingJob("a", "p", { jobId: "job_1", tab: "teaching" })).not.toThrow();
});
