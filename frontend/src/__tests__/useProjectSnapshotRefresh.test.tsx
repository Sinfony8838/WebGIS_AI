import { StrictMode, type ReactNode } from "react";
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useProjectSnapshotRefresh, type ProjectSnapshot } from "../hooks/useProjectSnapshotRefresh";

const reads = vi.hoisted(() => Array.from({ length: 5 }, () => vi.fn()));
vi.mock("../api", () => ({
  fetchProject: reads[0], fetchLayers: reads[1], fetchOutputs: reads[2],
  fetchLessonResources: reads[3], fetchActiveTeachingMaps: reads[4]
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function cohort(id = "project-a", marker = "first") {
  const snapshot = {
    project: { project_id: id, name: marker }, layers: { items: [{ layer_id: marker }] },
    outputs: { items: [{ artifact_id: marker }] },
    lessons: { items: [{ id: marker }], active_lesson_resource_set_id: marker },
    teachingMaps: { active: [marker] }
  } as unknown as ProjectSnapshot;
  const members = Object.values(snapshot).map(() => deferred<unknown>());
  reads.forEach((read, index) => read.mockReturnValueOnce(members[index].promise));
  return { snapshot, members, finish: () => Object.values(snapshot).forEach((value, index) => members[index].resolve(value)) };
}
function fixture(userId = "teacher-a", projectId = "project-a", strict = false) {
  const commit = vi.fn();
  const reset = vi.fn();
  const hook = renderHook(props => useProjectSnapshotRefresh(props.userId, props.projectId, props.commit, reset), {
    initialProps: { userId, projectId, commit },
    wrapper: strict ? ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode> : undefined
  });
  return { ...hook, commit, reset };
}

describe("project snapshot ownership", () => {
  beforeEach(() => reads.forEach(read => read.mockReset()));
  afterEach(cleanup);

  it("commits all five reads together with one signal and no partial state", async () => {
    const batch = cohort();
    const hook = fixture();
    const pending = hook.result.current.refresh("project-a");
    const signal = reads[0].mock.calls[0][1] as AbortSignal;
    reads.forEach(read => expect(read).toHaveBeenCalledWith("project-a", signal));
    await act(async () => { batch.members[0].resolve(batch.snapshot.project); });
    expect(hook.commit).not.toHaveBeenCalled();
    await act(async () => { batch.finish(); expect(await pending).toEqual(batch.snapshot); });
    expect(hook.commit.mock.calls).toEqual([[batch.snapshot]]);
  });

  it("a newer same-project cohort wins even if the older transport ignores abort", async () => {
    const older = cohort("project-a", "old");
    const newer = cohort("project-a", "new");
    const hook = fixture();
    const oldRead = hook.result.current.refresh("project-a");
    const oldSignal = reads[0].mock.calls[0][1] as AbortSignal;
    const newRead = hook.result.current.refresh("project-a");
    expect(oldSignal.aborted).toBe(true);
    await act(async () => { newer.finish(); await newRead; });
    await act(async () => { older.finish(); expect(await oldRead).toBeNull(); });
    expect(hook.commit.mock.calls).toEqual([[newer.snapshot]]);
  });

  it("suppresses an obsolete failure but reports the current failure without clearing committed data", async () => {
    const older = cohort();
    const newer = cohort();
    const hook = fixture();
    const oldRead = hook.result.current.refresh("project-a");
    const newRead = hook.result.current.refresh("project-a");
    const error = new Error("synthetic read failure");
    const checked = expect(newRead).rejects.toBe(error);
    await act(async () => { older.members[1].reject(new Error("obsolete")); expect(await oldRead).toBeNull(); });
    await act(async () => { newer.members[2].reject(error); await checked; });
    expect(hook.commit).not.toHaveBeenCalled();
    expect(hook.reset).not.toHaveBeenCalled();
    expect((reads[0].mock.calls[1][1] as AbortSignal).aborted).toBe(true);
  });

  it("project changes reject late reads and wrong-project callers cannot cancel a valid cohort", async () => {
    const a = cohort();
    const b = cohort("project-b");
    const hook = fixture();
    const oldRead = hook.result.current.refresh("project-a");
    hook.rerender({ userId: "teacher-a", projectId: "project-b", commit: hook.commit });
    const current = hook.result.current.refresh("project-b");
    expect(await hook.result.current.refresh("project-a")).toBeNull();
    expect((reads[0].mock.calls[1][1] as AbortSignal).aborted).toBe(false);
    await act(async () => { a.finish(); b.finish(); expect(await oldRead).toBeNull(); await current; });
    expect(hook.reset.mock.calls).toEqual([[false]]);
    expect(hook.commit.mock.calls).toEqual([[b.snapshot]]);
    expect(reads[0]).toHaveBeenCalledTimes(2);
  });

  it("actor changes require a fresh selection and old actor callbacks make no reads", async () => {
    const oldBatch = cohort();
    const hook = fixture();
    const oldRefresh = hook.result.current.refresh;
    const oldSelect = hook.result.current.selectProject;
    const pending = oldRefresh("project-a");
    hook.rerender({ userId: "teacher-b", projectId: "project-a", commit: hook.commit });
    expect(oldSelect("project-a")).toBe(false);
    expect(await oldRefresh("project-a")).toBeNull();
    expect(await hook.result.current.refresh("project-a")).toBeNull();
    await act(async () => { oldBatch.finish(); expect(await pending).toBeNull(); });
    expect(hook.reset.mock.calls).toEqual([[true]]);
    expect(hook.commit).not.toHaveBeenCalled();
    expect(reads[0]).toHaveBeenCalledTimes(1);
  });

  it("returning to the original project does not revive its previous lifetime", async () => {
    const batch = cohort();
    const hook = fixture();
    const isCurrent = hook.result.current.captureScope("project-a");
    const pending = hook.result.current.refresh("project-a");
    hook.rerender({ userId: "teacher-a", projectId: "project-b", commit: hook.commit });
    hook.rerender({ userId: "teacher-a", projectId: "project-a", commit: hook.commit });
    expect(isCurrent()).toBe(false);
    await act(async () => { batch.finish(); expect(await pending).toBeNull(); });
    expect(hook.commit).not.toHaveBeenCalled();
  });

  it.each([false, true])("unmount cancels reads and invalidates partial callbacks (StrictMode=%s)", async strict => {
    const batch = cohort();
    const hook = fixture("teacher-a", "project-a", strict);
    const isCurrent = hook.result.current.captureScope("project-a");
    const pending = hook.result.current.refresh("project-a");
    hook.unmount();
    expect(isCurrent()).toBe(false);
    expect((reads[0].mock.calls[0][1] as AbortSignal).aborted).toBe(true);
    batch.finish();
    expect(await pending).toBeNull();
    expect(hook.commit).not.toHaveBeenCalled();
  });

  it("bootstrap selects before rendering the project without cancelling its matching read", async () => {
    const batch = cohort();
    const hook = fixture("teacher-a", "");
    expect(await hook.result.current.refresh("project-a")).toBeNull();
    expect(reads[0]).not.toHaveBeenCalled();
    act(() => { expect(hook.result.current.selectProject("project-a")).toBe(true); });
    const pending = hook.result.current.refresh("project-a");
    hook.rerender({ userId: "teacher-a", projectId: "project-a", commit: hook.commit });
    expect((reads[0].mock.calls[0][1] as AbortSignal).aborted).toBe(false);
    await act(async () => { batch.finish(); await pending; });
    expect(hook.reset.mock.calls).toEqual([[false]]);
    expect(hook.commit.mock.calls).toEqual([[batch.snapshot]]);
  });

  it("rejects a mismatched project response without committing other members", async () => {
    const batch = cohort("other-project");
    const hook = fixture();
    const pending = hook.result.current.refresh("project-a");
    const checked = expect(pending).rejects.toThrow("项目快照与当前项目不一致");
    await act(async () => { batch.finish(); await checked; });
    expect(hook.commit).not.toHaveBeenCalled();
  });

  it("a failed refresh preserves the previous committed snapshot and selected project", async () => {
    const good = cohort("project-a", "retained");
    const failing = cohort("project-a", "failed");
    const hook = fixture();
    const first = hook.result.current.refresh("project-a");
    await act(async () => { good.finish(); await first; });
    const next = hook.result.current.refresh("project-a");
    const checked = expect(next).rejects.toThrow("temporary I/O");
    await act(async () => { failing.members[1].reject(new Error("temporary I/O")); await checked; });
    expect(hook.commit.mock.calls).toEqual([[good.snapshot]]);
    expect(hook.reset).not.toHaveBeenCalled();
    expect(hook.result.current.captureScope("project-a")()).toBe(true);
    failing.finish();
  });

  it("uses current commit callbacks without changing a same-actor lifetime", async () => {
    const batch = cohort();
    const hook = fixture();
    const isCurrent = hook.result.current.captureScope("project-a");
    const pending = hook.result.current.refresh("project-a");
    const newCommit = vi.fn();
    hook.rerender({ userId: "teacher-a", projectId: "project-a", commit: newCommit });
    await act(async () => { batch.finish(); await pending; });
    expect(isCurrent()).toBe(true);
    expect(hook.commit).not.toHaveBeenCalled();
    expect(newCommit.mock.calls).toEqual([[batch.snapshot]]);
    expect(hook.reset).not.toHaveBeenCalled();
  });

  it("partial mutation invalidation blocks an older aggregate but permits a fresh reconciliation", async () => {
    const older = cohort("project-a", "old-base");
    const fresh = cohort("project-a", "new-base");
    const hook = fixture();
    const isCurrent = hook.result.current.captureScope("project-a");
    const oldRead = hook.result.current.refresh("project-a");
    act(() => hook.result.current.invalidate());
    expect(isCurrent()).toBe(true);
    const current = hook.result.current.refresh("project-a");
    await act(async () => { older.finish(); fresh.finish(); expect(await oldRead).toBeNull(); await current; });
    expect(hook.commit.mock.calls).toEqual([[fresh.snapshot]]);
  });
});
