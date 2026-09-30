import type { LessonPlanProfile, LessonStage, LessonQuestion } from "../types";

// 一页表格式教案的纯工具：预设方法、AI 修改目标映射、环节差异计算。

export const PRESET_METHODS: string[] = [
  "讲授法",
  "演示法",
  "讨论法",
  "实验法",
  "角色扮演",
  "情境教学",
  "问题式教学",
  "小组合作探究",
  "案例教学",
  "地图技能训练",
  "比较归纳法",
  "任务驱动"
];

// 单元格/环节 → AI turn 的步骤作用域（后端 STEP_PATCH_SCOPES 按步骤过滤补丁）。
export const STEP_FOR_SECTION: Record<string, string> = {
  title: "requirements",
  topic: "requirements",
  grade: "requirements",
  duration_minutes: "requirements",
  subject: "requirements",
  requirements: "requirements",
  curriculum_interpretation: "analysis",
  student_analysis: "analysis",
  textbook_analysis: "analysis",
  objectives: "objectives",
  key_difficulties: "objectives",
  methods: "objectives",
  knowledge_structure: "objectives",
  core_questions: "core_questions",
  stages: "process",
  board_design: "process",
  question_citations: "question_matching",
  homework: "question_matching",
  references: "question_matching",
  design_thinking: "confirmation",
  reflection: "confirmation"
};

export function stageList(draft: { stages?: unknown } | undefined | null): LessonStage[] {
  // 历史数据可能存在被写坏的非数组 stages，渲染层统一容错。
  return Array.isArray(draft?.stages) ? (draft.stages as LessonStage[]) : [];
}

export function formatQuestion(q: LessonQuestion): string {
  const tags: string[] = [];
  if (q.source === "question_bank") tags.push(`题库 ${q.number || ""}`.trim());
  else if (q.source === "teacher_manual") tags.push("手动");
  if (q.year) tags.push(q.year);
  if (q.region) tags.push(q.region);
  if (q.answer_complete === false) tags.push("答案缺失");
  if (q.images?.length) tags.push(`${q.images.length}图`);
  const prefix = tags.length ? `（${tags.join(" · ")}）` : "";
  const optionLine = q.options?.length ? `\n选项：${q.options.join(" ｜ ")}` : "";
  return `${prefix}${q.text || q.task_text || ""}${optionLine}`;
}

export type StageFieldDiff = {
  stageIndex: number;
  stageTitle: string;
  field: string;
  fieldLabel: string;
  oldValue: string;
  newValue: string;
};

const DIFF_FIELDS: Array<[string, string]> = [
  ["title", "名称"],
  ["minutes", "时长"],
  ["knowledge_point", "知识点"],
  ["material", "材料"],
  ["question_chain", "问题链"],
  ["teacher_activities", "教师活动"],
  ["student_activities", "学生活动"],
  ["knowledge_conclusion", "知识结论"],
  ["design_intent", "设计意图"]
];

function fieldText(stage: Record<string, unknown>, field: string): string {
  const value = stage[field];
  if (Array.isArray(value)) return value.map((item) => String(item)).join("；");
  if (value === null || value === undefined) return "";
  return String(value);
}

export function diffStages(
  before: LessonPlanProfile | Record<string, unknown>,
  after: LessonPlanProfile | Record<string, unknown>
): StageFieldDiff[] {
  const oldStages = Array.isArray(before.stages) ? (before.stages as Array<Record<string, unknown>>) : [];
  const newStages = Array.isArray(after.stages) ? (after.stages as Array<Record<string, unknown>>) : [];
  const diffs: StageFieldDiff[] = [];
  const count = Math.max(oldStages.length, newStages.length);
  for (let index = 0; index < count; index += 1) {
    const oldStage = oldStages[index] || {};
    const newStage = newStages[index] || {};
    if (oldStage.stage_id && newStage.stage_id && oldStage.stage_id !== newStage.stage_id) {
      continue; // 环节被整体替换（新增/删除），由增删提示说明，不做逐字段 diff。
    }
    for (const [field, fieldLabel] of DIFF_FIELDS) {
      const oldValue = fieldText(oldStage, field);
      const newValue = fieldText(newStage, field);
      if (oldValue !== newValue) {
        diffs.push({
          stageIndex: index,
          stageTitle: String(newStage.title || oldStage.title || `环节${index + 1}`),
          field,
          fieldLabel,
          oldValue,
          newValue
        });
      }
    }
  }
  return diffs;
}

export function sectionText(sectionId: string, draft: Record<string, unknown>): string {
  const value = draft[sectionId];
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map((item) => (typeof item === "object" ? JSON.stringify(item) : String(item))).join("\n");
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

export function splitLines(text: string): string[] {
  return text
    .split(/\r?\n|；|;/)
    .map((item) => item.trim())
    .filter(Boolean);
}
