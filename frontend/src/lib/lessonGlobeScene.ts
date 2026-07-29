import type { LessonGlobeScene } from "../types";

export type LessonGlobeSceneDecision =
  | { kind: "apply-globe"; rememberCurrent: boolean; globe: LessonGlobeScene }
  | { kind: "apply-plane" }
  | { kind: "restore" }
  | { kind: "none" };

/**
 * Pure policy for lesson-driven 2D/3D transitions.
 *
 * Empty globe intent preserves legacy lessons unless a previous lesson stage
 * pinned the globe, in which case it restores the teacher's entry view.
 */
export function decideLessonGlobeScene(
  globe: LessonGlobeScene,
  pinned: boolean,
  hasRestoreSnapshot: boolean
): LessonGlobeSceneDecision {
  if (globe.enabled === true) {
    return { kind: "apply-globe", rememberCurrent: !pinned, globe };
  }
  if (globe.enabled === false) {
    return { kind: "apply-plane" };
  }
  if (pinned && hasRestoreSnapshot) {
    return { kind: "restore" };
  }
  return { kind: "none" };
}
