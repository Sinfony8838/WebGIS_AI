import { describe, expect, it } from "vitest";
import { stageKindInfo } from "../lib/stageKinds";
import type { LessonStage } from "../types";

function stage(kind: LessonStage["kind"], activities: string[] = []): Pick<LessonStage, "kind" | "activities"> {
  return { kind, activities };
}

describe("stageKindInfo", () => {
  it("maps explicit kinds to the two teacher-facing icons", () => {
    expect(stageKindInfo(stage("practice"))).toEqual({ kind: "practice", icon: "✍", label: "练习" });
    expect(stageKindInfo(stage("question"))).toEqual({ kind: "question", icon: "？", label: "提问" });
    expect(stageKindInfo(stage("presentation")).icon).toBe("");
    expect(stageKindInfo(stage("summary")).icon).toBe("");
    expect(stageKindInfo(stage("presentation")).label).toBe("讲授");
    expect(stageKindInfo(stage("summary")).label).toBe("小结");
  });

  it("ignores unknown kind values and infers practice from declared activities", () => {
    expect(stageKindInfo(stage("bogus" as NonNullable<LessonStage["kind"]>, ["小组绘制胡焕庸线"])).kind).toBe("practice");
    expect(stageKindInfo(stage(undefined, ["画线活动"])).kind).toBe("practice");
  });

  it("falls back to presentation without icon for untagged stages", () => {
    const info = stageKindInfo(stage(undefined));
    expect(info.kind).toBe("presentation");
    expect(info.icon).toBe("");
  });
});
