import type { LessonStage, PresentationBlock, PresentationBlockType, PresentationLayout } from "../types";

// 环节展示布局的纯工具：默认布局、区块工厂、几何约束。

export function newBlockId(type: PresentationBlockType): string {
  const random = Math.random().toString(36).slice(2, 8);
  return `blk_${type}_${Date.now().toString(36)}_${random}`;
}

export function clamp01(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

export function makeBlock(type: PresentationBlockType, overrides: Partial<PresentationBlock> = {}): PresentationBlock {
  const base: PresentationBlock = {
    id: newBlockId(type),
    type,
    text: "",
    z: 0,
    order: 0,
    x: 0.08,
    y: 0.08,
    w: 0.4,
    h: 0.2
  };
  return { ...base, ...overrides, id: overrides.id || base.id };
}

// 可直接内联播放的媒体：本库 mp4/webm 或 https 直链。
export function isDirectVideo(mimeType?: string, url?: string): boolean {
  if (mimeType === "video/mp4" || mimeType === "video/webm") return true;
  if (!url) return false;
  const clean = url.split("?")[0].toLowerCase();
  return /^https:\/\//.test(url) && (clean.endsWith(".mp4") || clean.endsWith(".webm"));
}

export function isExternalUrl(url?: string): boolean {
  return typeof url === "string" && /^https?:\/\//i.test(url || "");
}

/**
 * 旧课时没有布局时，用现有环节内容生成可读的默认展示：
 * 标题 + 材料/知识点 + 学生活动 + 问题（题干，不含答案）+ 知识结论。
 */
export function defaultLayoutFromStage(stage: LessonStage): PresentationLayout {
  const blocks: PresentationBlock[] = [];
  let order = 0;
  const push = (block: PresentationBlock) => {
    blocks.push({ ...block, order, z: 0 });
    order += 1;
  };
  const title = stage.title || "教学环节";
  push(makeBlock("text", { text: title, x: 0.06, y: 0.06, w: 0.88, h: 0.14 }));
  const info: string[] = [];
  if (stage.knowledge_point) info.push(`知识点：${stage.knowledge_point}`);
  if (stage.material) info.push(`材料：${stage.material}`);
  const activities = stage.student_activities || [];
  if (activities.length) info.push(`活动：${activities.join("；")}`);
  if (info.length) {
    push(makeBlock("text", { text: info.join("\n"), x: 0.06, y: 0.24, w: 0.88, h: 0.26 }));
  }
  const questions = (stage.questions || []).slice(0, 2);
  questions.forEach((question, index) => {
    push(
      makeBlock("question", {
        text: question.text || question.task_text || "",
        asset: { question_id: question.question_id },
        x: 0.06 + index * 0.46,
        y: 0.56,
        w: 0.42,
        h: 0.2
      })
    );
  });
  if (stage.knowledge_conclusion) {
    push(makeBlock("text", { text: `结论：${stage.knowledge_conclusion}`, teacher_reveal: true, x: 0.06, y: 0.8, w: 0.88, h: 0.14 }));
  }
  return { blocks };
}
