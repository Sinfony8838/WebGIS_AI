import { afterEach, describe, expect, it, vi } from "vitest";
import { applyGlobeView, globeViewTarget, renderedGlobeMatches, type GlobeRenderEvidence } from "../lib/globeViewCommand";

afterEach(() => vi.useRealTimers());
const target = globeViewTarget("overview", 115.15, 33.99, 7.1);
const frame = (changes: Partial<GlobeRenderEvidence> = {}): GlobeRenderEvidence => ({ ...target, frame: 2, visible: true, scene3D: true, ...changes });
describe("real globe camera receipts", () => {
  it("shows the entire globe by default and honors reset/preserve explicitly", () => {
    expect(target.altitudeMeters).toBe(20_000_000);
    expect(globeViewTarget("default", 115, 34, 7)).toMatchObject({lon:104, lat:35, altitudeMeters:12_000_000});
    expect(globeViewTarget("preserve", 115, 34, 8).altitudeMeters).toBe(1_000_000);
  });
  it("rejects a mode flag, stale frame, flat camera, hidden canvas and wrong location", () => {
    expect(renderedGlobeMatches(null, target, 1)).toBe(false);
    for (const evidence of [frame({frame:1}), frame({altitudeMeters:1_000_000}), frame({visible:false}), frame({scene3D:false}), frame({lon:104}), frame({pitchDeg:-40})]) {
      expect(renderedGlobeMatches(evidence, target, 1)).toBe(false);
    }
    expect(renderedGlobeMatches(frame(), target, 1)).toBe(true);
  });
  it("waits for the visible globe and a new matching frame before completing, even when already globe", async () => {
    vi.useFakeTimers();
    let evidence = frame({visible:false, frame:1});
    const fly = vi.fn();
    const cancel = vi.fn();
    const done = vi.fn();
    const run = applyGlobeView({target, read:() => evidence, fly, cancel, isCurrent:() => true}).then(done);
    await vi.advanceTimersByTimeAsync(25);
    expect(fly).not.toHaveBeenCalled();
    evidence = frame({frame:1});
    await vi.advanceTimersByTimeAsync(25);
    expect(fly).toHaveBeenCalledOnce();
    expect(done).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(25);
    expect(done).not.toHaveBeenCalled();
    evidence = frame();
    await vi.advanceTimersByTimeAsync(25);
    await run;
    expect(done).toHaveBeenCalledOnce();
    expect(cancel).not.toHaveBeenCalled();
  });
  it("fails rather than reporting success when the camera stays flat", async () => {
    vi.useFakeTimers();
    const cancel = vi.fn();
    const run = applyGlobeView({target, read:() => frame({altitudeMeters:1_000_000}), fly:vi.fn(), cancel, isCurrent:() => true, timeoutMs:100});
    const rejection = expect(run).rejects.toThrow("未确认成功");
    await vi.advanceTimersByTimeAsync(125);
    await rejection;
    expect(cancel).toHaveBeenCalledOnce();
  });
  it("cancels flight without acknowledging success after a scope change", async () => {
    vi.useFakeTimers();
    let current = true;
    const cancel = vi.fn();
    const run = applyGlobeView({target, read:() => frame(), fly:vi.fn(), cancel, isCurrent:() => current});
    const rejection = expect(run).rejects.toThrow("已取消");
    current = false;
    await vi.advanceTimersByTimeAsync(25);
    await rejection;
    expect(cancel).toHaveBeenCalledOnce();
  });
});
