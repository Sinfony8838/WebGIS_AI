import { describe, expect, it, vi } from "vitest";
import { UiActionReceiver } from "../lib/uiActionReceiver";
import { interactionActivityLabel } from "../lib/interactionActivity";
import type { JobRecord } from "../types";

function job(overrides: Partial<JobRecord> = {}): JobRecord {
  return { job_id: "job", project_id: "project", job_type: "assistant", title: "", workflow_type: "assistant_message", status: "running", updated_at: "", steps: [], stages: {},
    ui_actions: [{ action_id: "action", project_id: "project", session_id: "class", status: "pending", type: "switch_view", mode: "globe" }], ...overrides };
}
function options(overrides = {}) {
  return { isCurrent: () => true, recovered: false, sessionId: "class", apply: vi.fn(async () => {}), acknowledge: vi.fn(async () => {}), ...overrides };
}

describe("UI action observations", () => {
  it("applies running-job actions before acknowledging, once across duplicate snapshots", async () => {
    const receiver = new UiActionReceiver();
    let release!: () => void;
    const settings = options({ apply: vi.fn(() => new Promise<void>((resolve) => { release = resolve; })) });
    const first = receiver.receive(job(), settings);
    await receiver.receive(job(), settings);
    expect(settings.apply).toHaveBeenCalledOnce();
    expect(settings.acknowledge).not.toHaveBeenCalled();
    release();
    await first;
    await receiver.receive(job(), settings);
    expect(settings.apply).toHaveBeenCalledOnce();
    expect(settings.acknowledge).toHaveBeenCalledOnce();
    expect(settings.acknowledge).toHaveBeenCalledWith("job", expect.objectContaining({ status: "applied" }));
  });

  it("retries a lost receipt without replaying its UI action", async () => {
    const receiver = new UiActionReceiver();
    const settings = options();
    settings.acknowledge.mockRejectedValueOnce(new Error("offline"));
    await receiver.receive(job(), settings);
    await receiver.receive(job(), settings);
    expect(settings.apply).toHaveBeenCalledOnce();
    expect(settings.acknowledge).toHaveBeenCalledTimes(2);
    expect(settings.acknowledge.mock.calls[0]).toEqual(settings.acknowledge.mock.calls[1]);
  });

  it.each([{ recovered: true }, { sessionId: "new_class" }])("does not replay recovered or old-class actions: %s", async (overrides) => {
    const receiver = new UiActionReceiver();
    const settings = options(overrides);
    await receiver.receive(job(), settings);
    expect(settings.apply).not.toHaveBeenCalled();
    expect(settings.acknowledge).toHaveBeenCalledWith("job", expect.objectContaining({ status: "unconfirmed" }));
  });

  it("ignores expired, cancelled and unrelated project actions", async () => {
    const receiver = new UiActionReceiver();
    const settings = options();
    const expired = job();
    expired.ui_actions![0].expires_at = Date.now() / 1000 - 1;
    await receiver.receive(expired, settings);
    expect(settings.apply).not.toHaveBeenCalled();
    expect(settings.acknowledge).toHaveBeenCalledWith("job", expect.objectContaining({ status: "unconfirmed" }));
    settings.acknowledge.mockClear();
    await receiver.receive(job(), options({ isCurrent: () => false, apply: settings.apply, acknowledge: settings.acknowledge }));
    const unrelated = job({ job_id: "other_job" });
    unrelated.ui_actions![0].project_id = "other_project";
    await receiver.receive(unrelated, settings);
    expect(settings.apply).not.toHaveBeenCalled();
    expect(settings.acknowledge).not.toHaveBeenCalled();
  });

  it("reports application errors and drops late scope changes", async () => {
    const receiver = new UiActionReceiver();
    const settings = options({ apply: vi.fn(async () => { throw new Error("view unavailable"); }) });
    await receiver.receive(job(), settings);
    expect(settings.acknowledge).toHaveBeenCalledWith("job", expect.objectContaining({ status: "failed", detail: "view unavailable" }));
    let current = true;
    const late = options({ isCurrent: () => current, apply: vi.fn(async () => { current = false; }) });
    await receiver.receive(job({ job_id: "late" }), late);
    expect(late.acknowledge).not.toHaveBeenCalled();
  });

  it("does not apply a pending action carried by a restarted or terminal job", async () => {
    const receiver = new UiActionReceiver();
    const settings = options();
    await receiver.receive(job({ status: "failed" }), settings);
    await receiver.receive(job({ status: "completed" }), settings);
    expect(settings.apply).not.toHaveBeenCalled();
    expect(settings.acknowledge).not.toHaveBeenCalled();
  });

  it("shares the backend's actual phase label with both visual surfaces", () => {
    expect(interactionActivityLabel(job({ activity: { phase: "tool_running", label: "智能体调用工具中 · 空间统计" } }))).toBe("智能体调用工具中 · 空间统计");
    expect(interactionActivityLabel(job({ stages: { planning: { status: "running", summary: "hidden internal detail", detail: "" } } }))).toBe("智能体思考中");
  });
});
