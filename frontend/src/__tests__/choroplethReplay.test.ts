import { describe, expect, it, vi } from "vitest";
import Feature from "ol/Feature";
import Point from "ol/geom/Point";
import VectorLayer from "ol/layer/Vector";
import { Style } from "ol/style";

import {
  buildReplayPlan,
  classIndexFor,
  mixHexColors,
  replayColorAt,
  DEFAULT_REPLAY_TIMING
} from "../lib/choroplethReplay";
import { startChoroplethReplay } from "../lib/choroplethReplay";
import type { GraduatedStyle } from "../types";

const STYLE: GraduatedStyle = {
  type: "graduated",
  field: "density",
  classes: [
    { min: 0, max: 100, color: "#eff3ff", label: "低" },
    { min: 100, max: 300, color: "#6baed6", label: "中" },
    { min: 300, max: 1000, color: "#08519c", label: "高" }
  ],
  default: { color: "#dddddd" }
};

const TIMING = {
  initialHold: 100,
  classDwell: 50,
  featureStagger: 10,
  fadeDuration: 40
};

it("keeps point results visible throughout replay and restores the final style", () => {
  vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  try {
    const layer = new VectorLayer();
    const feature = new Feature({ geometry: new Point([104, 35]), density: 150 });
    const restore = () => new Style();
    const replay = startChoroplethReplay({ layer, style: STYLE, features: [feature], restoreStyle: restore });
    const rendered = layer.getStyleFunction()!(feature, 1) as Style;
    expect(rendered.getImage()).toBeTruthy();
    replay.cancel();
    expect(layer.getStyle()).toBe(restore);
  } finally {
    vi.unstubAllGlobals();
  }
});

describe("classIndexFor", () => {
  it("matches the first class containing the value (inclusive bounds)", () => {
    expect(classIndexFor(STYLE, 50)).toBe(0);
    // 100 sits on the class0/class1 boundary; first match wins, mirroring
    // the dock's styleClassFor so replay colours equal final colours.
    expect(classIndexFor(STYLE, 100)).toBe(0);
    expect(classIndexFor(STYLE, 150)).toBe(1);
    expect(classIndexFor(STYLE, 1000)).toBe(2);
  });

  it("returns -1 for values outside every class", () => {
    expect(classIndexFor(STYLE, -5)).toBe(-1);
    expect(classIndexFor(STYLE, 2000)).toBe(-1);
  });
});

describe("mixHexColors", () => {
  it("returns the base colour at t=0 and the target at t=1", () => {
    expect(mixHexColors("#cccccc", "#08519c", 0)).toBe("rgb(204, 204, 204)");
    expect(mixHexColors("#cccccc", "#08519c", 1)).toBe("rgb(8, 81, 156)");
  });

  it("interpolates and clamps midpoints", () => {
    const mid = mixHexColors("#000000", "#ffffff", 0.5);
    expect(mid).toBe("rgb(128, 128, 128)");
    expect(mixHexColors("#000000", "#ffffff", 2)).toBe("rgb(255, 255, 255)");
  });
});

describe("buildReplayPlan", () => {
  const values = [50, 150, 200, 500, Number.NaN];

  it("schedules one entry per feature", () => {
    const plan = buildReplayPlan(STYLE, values, TIMING);
    expect(plan.entries).toHaveLength(5);
  });

  it("fills classes in ascending order and unclassified last", () => {
    const plan = buildReplayPlan(STYLE, values, TIMING);
    // Exact schedule with the fixed TIMING above:
    // class0 @100 → class1 @190 (stagger 10) → class2 @290 → unclassified @380.
    expect(plan.phaseStarts.map((item) => item.at)).toEqual([100, 190, 290, 380]);
    expect(plan.phaseStarts.map((item) => item.phase.classIndex)).toEqual([0, 1, 2, -1]);
    const unclassified = plan.entries.find((entry) => entry.classIndex === -1);
    expect(unclassified?.color).toBe("#dddddd");
    expect(unclassified?.revealAt).toBe(380);
    expect(plan.endTime).toBe(420);
  });

  it("staggers features inside a class by ascending value", () => {
    const plan = buildReplayPlan(STYLE, values, TIMING);
    const class1 = plan.entries.filter((entry) => entry.classIndex === 1);
    expect(class1).toHaveLength(2);
    expect(class1[0].revealAt).toBeLessThan(class1[1].revealAt);
  });

  it("keeps entry reveal times non-decreasing across the plan", () => {
    const plan = buildReplayPlan(STYLE, values, TIMING);
    for (let i = 1; i < plan.entries.length; i += 1) {
      expect(plan.entries[i].revealAt).toBeGreaterThanOrEqual(plan.entries[i - 1].revealAt);
    }
  });

  it("emits a phase for every class even when it has no features", () => {
    const plan = buildReplayPlan(STYLE, [50], TIMING);
    expect(plan.phaseStarts.map((item) => item.phase.classIndex)).toEqual([0, 1, 2]);
    expect(plan.entries).toHaveLength(1);
  });

  it("uses default timing when omitted", () => {
    const plan = buildReplayPlan(STYLE, [50]);
    expect(plan.phaseStarts[0].at).toBe(DEFAULT_REPLAY_TIMING.initialHold);
  });
});

describe("replayColorAt", () => {
  const entry = { featureIndex: 0, classIndex: 2, color: "#08519c", revealAt: 100 };

  it("stays on the base colour before the reveal time", () => {
    expect(replayColorAt("#cccccc", entry, 50, 40)).toBe("#cccccc");
  });

  it("returns the final class colour after the fade", () => {
    expect(replayColorAt("#cccccc", entry, 200, 40)).toBe("#08519c");
  });

  it("interpolates during the fade window", () => {
    const mid = replayColorAt("#cccccc", entry, 120, 40);
    expect(mid).toContain("rgb(");
    expect(mid).not.toBe("#cccccc");
    expect(mid).not.toBe("#08519c");
  });
});
