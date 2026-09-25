import type { LessonStage, LessonStageKind } from "../types";

const KIND_LABELS: Record<LessonStageKind, string> = {
  presentation: "讲授",
  practice: "练习",
  question: "提问",
  summary: "小结"
};

// 教师只要 ✍（练习）与？（提问）两类徽标；讲授/小结不上图标，避免满屏符号。
const KIND_ICONS: Partial<Record<LessonStageKind, string>> = {
  practice: "✍",
  question: "？"
};

const VALID_KINDS: ReadonlySet<string> = new Set(["presentation", "practice", "question", "summary"]);

export type StageKindInfo = {
  kind: LessonStageKind;
  icon: string;
  label: string;
};

/** 解析环节类型：优先显式 kind（非法值忽略），缺省时按环节内容回落推断。 */
export function stageKindInfo(stage: Pick<LessonStage, "kind" | "activities">): StageKindInfo {
  const explicit = typeof stage.kind === "string" && VALID_KINDS.has(stage.kind)
    ? (stage.kind as LessonStageKind)
    : stage.activities && stage.activities.length
      ? "practice"
      : "presentation";
  return { kind: explicit, icon: KIND_ICONS[explicit] || "", label: KIND_LABELS[explicit] };
}
