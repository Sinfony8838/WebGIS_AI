import { describe, expect, it } from "vitest";
import { decideLessonGlobeScene } from "../lib/lessonGlobeScene";

describe("decideLessonGlobeScene", () => {
  it("keeps legacy empty scenes unchanged when no lesson scene is pinned", () => {
    expect(decideLessonGlobeScene({}, false, false)).toEqual({ kind: "none" });
  });

  it("remembers the entry view for the first 3D lesson stage only", () => {
    const globe = { enabled: true, themes: ["density_fill"] };
    expect(decideLessonGlobeScene(globe, false, false)).toEqual({
      kind: "apply-globe",
      rememberCurrent: true,
      globe
    });
    expect(decideLessonGlobeScene(globe, true, true)).toEqual({
      kind: "apply-globe",
      rememberCurrent: false,
      globe
    });
  });

  it("restores after a pinned 3D scene and honors explicit 2D intent", () => {
    expect(decideLessonGlobeScene({}, true, true)).toEqual({ kind: "restore" });
    expect(decideLessonGlobeScene({ enabled: false }, true, true)).toEqual({ kind: "apply-plane" });
  });
});
