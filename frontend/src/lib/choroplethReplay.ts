/**
 * Choropleth replay — replays the cartography process in the browser.
 *
 * The PyQGIS backend still owns the real classification math and ships the
 * final GeoJSON + graduated style.json. This module replays the colouring
 * steps on the OpenLayers layer so a class can watch the map being drawn:
 * grey base → per-class progressive fill (low values first) → final map.
 *
 * The module temporarily owns the layer style while running. Callers pass
 * `restoreStyle` so the dock's own style function is put back when the
 * replay finishes, is skipped, or is cancelled.
 */
import { Circle, Fill, Stroke, Style } from "ol/style";
import type { FeatureLike } from "ol/Feature";
import type VectorLayer from "ol/layer/Vector";

import type { GraduatedStyle } from "../types";

const DEFAULT_FILL = "#cccccc";

export type ReplayTiming = {
  /** Quiet beat on the grey base map before the first class fills. */
  initialHold: number;
  /** Pause between consecutive classes. */
  classDwell: number;
  /** Extra delay between two features of the same class. */
  featureStagger: number;
  /** Grey → class colour fade per feature. */
  fadeDuration: number;
};

export const DEFAULT_REPLAY_TIMING: ReplayTiming = {
  initialHold: 500,
  classDwell: 700,
  featureStagger: 45,
  fadeDuration: 520
};

export type ReplayPhase = {
  /** Index into style.classes, or -1 for the trailing unclassified group. */
  classIndex: number;
  classCount: number;
  label?: string;
};

export type ReplayEntry = {
  featureIndex: number;
  classIndex: number;
  color: string;
  /** Offset in ms from replay start when this feature starts fading in. */
  revealAt: number;
};

export type ReplayPlan = {
  entries: ReplayEntry[];
  /** Schedule of phases; each class gets one even when it has no features. */
  phaseStarts: Array<{ at: number; phase: ReplayPhase }>;
  endTime: number;
  fadeDuration: number;
};

/**
 * First class whose [min, max] contains the value — mirrors the backend's
 * style.json semantics (boundaries are inclusive on both ends, first match
 * wins) so replay colours always agree with the final style.
 */
export function classIndexFor(style: GraduatedStyle, value: number): number {
  const classes = style.classes || [];
  for (let i = 0; i < classes.length; i += 1) {
    const cls = classes[i];
    if (value >= cls.min && value <= cls.max) {
      return i;
    }
  }
  return -1;
}

export function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "");
  const full =
    clean.length === 3
      ? clean
          .split("")
          .map((ch) => ch + ch)
          .join("")
      : clean;
  const value = Number.parseInt(full, 16);
  if (!Number.isFinite(value)) {
    return [204, 204, 204];
  }
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

export function mixHexColors(from: string, to: string, t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const a = hexToRgb(from);
  const b = hexToRgb(to);
  const mix = a.map((channel, i) => Math.round(channel + (b[i] - channel) * clamped));
  return `rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`;
}

export function buildReplayPlan(
  style: GraduatedStyle,
  values: number[],
  timing: ReplayTiming = DEFAULT_REPLAY_TIMING
): ReplayPlan {
  const classes = style.classes || [];
  const classCount = classes.length;
  const defaultColor = style.default?.color || DEFAULT_FILL;

  // Bucket feature indices by class, keeping values sorted inside a class so
  // the fill spreads through the group from the smallest value up.
  const buckets = new Map<number, Array<{ index: number; value: number }>>();
  values.forEach((value, index) => {
    const classIndex = Number.isFinite(value) ? classIndexFor(style, value) : -1;
    const bucket = buckets.get(classIndex);
    if (bucket) {
      bucket.push({ index, value });
    } else {
      buckets.set(classIndex, [{ index, value }]);
    }
  });

  const entries: ReplayEntry[] = [];
  const phaseStarts: ReplayPlan["phaseStarts"] = [];
  let clock = timing.initialHold;

  const scheduleGroup = (classIndex: number) => {
    const bucket = buckets.get(classIndex) || [];
    bucket.sort((a, b) => a.value - b.value);
    const color = classIndex >= 0 ? classes[classIndex].color : defaultColor;
    phaseStarts.push({
      at: clock,
      phase: {
        classIndex,
        classCount,
        label: classIndex >= 0 ? classes[classIndex]?.label : "未分级区域"
      }
    });
    bucket.forEach((item, i) => {
      entries.push({
        featureIndex: item.index,
        classIndex,
        color,
        revealAt: clock + i * timing.featureStagger
      });
    });
    const spread = bucket.length > 1 ? (bucket.length - 1) * timing.featureStagger : 0;
    clock += spread + timing.fadeDuration + timing.classDwell;
  };

  for (let classIndex = 0; classIndex < classCount; classIndex += 1) {
    scheduleGroup(classIndex);
  }
  const unclassified = buckets.get(-1);
  if (unclassified && unclassified.length > 0) {
    scheduleGroup(-1);
  }

  const lastReveal = entries.reduce((max, entry) => Math.max(max, entry.revealAt), 0);
  return {
    entries,
    phaseStarts,
    endTime: lastReveal + timing.fadeDuration,
    fadeDuration: timing.fadeDuration
  };
}

/** Colour of one feature at `elapsed` ms into the replay. */
export function replayColorAt(
  baseColor: string,
  entry: ReplayEntry,
  elapsed: number,
  fadeDuration: number
): string {
  if (elapsed <= entry.revealAt) {
    return baseColor;
  }
  if (elapsed >= entry.revealAt + fadeDuration) {
    return entry.color;
  }
  return mixHexColors(baseColor, entry.color, (elapsed - entry.revealAt) / fadeDuration);
}

export type ChoroplethReplay = {
  /** Total animation length in ms (0 when reduced motion skipped it). */
  duration: number;
  /** Jump straight to the final map; fires onPhase(null) + onComplete. */
  skip(): void;
  /** Stop and restore the final style without completion callbacks. */
  cancel(): void;
};

export function startChoroplethReplay(options: {
  layer: VectorLayer<any>;
  style: GraduatedStyle;
  features: FeatureLike[];
  restoreStyle: (feature: FeatureLike) => Style;
  baseColor?: string;
  timing?: Partial<ReplayTiming>;
  onPhase?(phase: ReplayPhase | null): void;
  onComplete?(): void;
}): ChoroplethReplay {
  const { layer, style, features, restoreStyle, onPhase, onComplete } = options;
  const timing = { ...DEFAULT_REPLAY_TIMING, ...(options.timing || {}) };
  const baseColor = options.baseColor || DEFAULT_FILL;

  const finishWithFinalStyle = () => {
    layer.setStyle(restoreStyle);
    layer.changed();
  };

  const prefersReducedMotion =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefersReducedMotion) {
    finishWithFinalStyle();
    onComplete?.();
    return { duration: 0, skip: () => undefined, cancel: () => undefined };
  }

  const values = features.map((feature) => {
    const raw = feature.get(style.field);
    const numeric = typeof raw === "string" ? Number(raw) : raw;
    return typeof numeric === "number" && Number.isFinite(numeric) ? numeric : Number.NaN;
  });
  const plan = buildReplayPlan(style, values, timing);
  const entryByFeature = new Map<FeatureLike, ReplayEntry>();
  plan.entries.forEach((entry) => {
    const feature = features[entry.featureIndex];
    if (feature) {
      entryByFeature.set(feature, entry);
    }
  });

  const strokeColor = style.stroke?.color || "#444444";
  const strokeWidth = style.stroke?.width ?? 0.6;

  let finished = false;
  let rafId = 0;
  let lastPhaseKey: number | null = null;
  const startedAt = performance.now();

  const styleDuringReplay = (feature: FeatureLike) => {
    const elapsed = performance.now() - startedAt;
    const entry = entryByFeature.get(feature);
    const color = entry
      ? replayColorAt(baseColor, entry, elapsed, plan.fadeDuration)
      : baseColor;
    return new Style({
      image: new Circle({ radius: 5.5, fill: new Fill({ color }), stroke: new Stroke({ color: strokeColor, width: strokeWidth }) }),
      fill: new Fill({ color }),
      stroke: new Stroke({ color: strokeColor, width: strokeWidth })
    });
  };

  const phaseAt = (elapsed: number): ReplayPhase | null => {
    let current: ReplayPhase | null = null;
    for (const item of plan.phaseStarts) {
      if (elapsed < item.at) {
        break;
      }
      current = item.phase;
    }
    return current;
  };

  const finish = (fireCallbacks: boolean) => {
    if (finished) {
      return;
    }
    finished = true;
    if (rafId) {
      cancelAnimationFrame(rafId);
    }
    finishWithFinalStyle();
    if (fireCallbacks) {
      onPhase?.(null);
      onComplete?.();
    }
  };

  const tick = () => {
    if (finished) {
      return;
    }
    const elapsed = performance.now() - startedAt;
    const phase = phaseAt(elapsed);
    const phaseKey = phase ? phase.classIndex : null;
    if (phaseKey !== lastPhaseKey) {
      lastPhaseKey = phaseKey;
      onPhase?.(phase);
    }
    if (elapsed >= plan.endTime) {
      finish(true);
      return;
    }
    layer.changed();
    rafId = requestAnimationFrame(tick);
  };

  layer.setStyle(styleDuringReplay);
  layer.changed();
  rafId = requestAnimationFrame(tick);

  return {
    duration: plan.endTime,
    skip: () => finish(true),
    cancel: () => finish(false)
  };
}
