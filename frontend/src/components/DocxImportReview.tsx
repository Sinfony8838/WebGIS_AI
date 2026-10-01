import { useState } from "react";
import type { LessonDocxImportMapping, LessonDocxUnclassified, LessonStage } from "../types";
import { buildAuthenticatedUrl } from "../api";

// Word 导入校对界面：把待归类文字/图片分配到指定教案字段或环节栏目。
// 原文、来源位置与识别结果始终可见；未处理内容保留在清单中，刷新后恢复进度。

export const DOCX_SECTION_TARGETS: Array<[string, string]> = [
  ["title", "课题"],
  ["subject", "学科"],
  ["grade", "年级"],
  ["duration_minutes", "课时（分钟）"],
  ["objectives", "教学目标"],
  ["key_difficulties", "教学重难点"],
  ["methods", "教学方法"],
  ["core_questions", "核心问题与问题链"],
  ["knowledge_structure", "知识结构"],
  ["curriculum_interpretation", "课标解读"],
  ["student_analysis", "学情分析"],
  ["textbook_analysis", "教材分析"],
  ["design_thinking", "设计思路"],
  ["board_design", "板书设计"],
  ["homework", "课后作业"],
  ["reflection", "教学反思"],
  ["references", "参考资料"]
];

export const DOCX_STAGE_COLUMN_TARGETS: Array<[string, string]> = [
  ["title", "环节名称"],
  ["minutes", "环节时长"],
  ["knowledge_point", "知识点"],
  ["material", "材料"],
  ["teacher_activities", "教师活动"],
  ["student_activities", "学生活动"],
  ["question_chain", "问题链"],
  ["knowledge_conclusion", "知识结论"],
  ["design_intent", "设计意图"]
];

const KIND_LABELS: Record<string, string> = {
  text: "段落",
  table: "表格",
  image: "图片"
};

const STATUS_LABELS: Record<string, string> = {
  assigned: "已归类",
  ignored: "已忽略"
};

export type ImportReviewApplyPayload = {
  item_index: number;
  action: "assign" | "ignore";
  target?: { section?: string; stage_id?: string; column?: string } | null;
  mode?: "append" | "replace";
};

function assignmentLabel(item: LessonDocxUnclassified): string {
  const assignment = item.assignment;
  if (!assignment) return "";
  if (assignment.kind === "section") return `教案字段：${assignment.label || assignment.section}`;
  if (assignment.kind === "stage_column") {
    const column = DOCX_STAGE_COLUMN_TARGETS.find(([key]) => key === assignment.column)?.[1] || assignment.column;
    return `环节「${assignment.stage_title}」· ${column}`;
  }
  if (assignment.kind === "stage_material") return `环节「${assignment.stage_title}」· 素材列表`;
  return "";
}

function ImportReviewItem({
  item,
  index,
  stages,
  busy,
  onApply
}: {
  item: LessonDocxUnclassified;
  index: number;
  stages: LessonStage[];
  busy: boolean;
  onApply: (payload: ImportReviewApplyPayload) => void;
}) {
  const isImage = item.kind === "image";
  const [targetKind, setTargetKind] = useState<"section" | "stage">("section");
  const [section, setSection] = useState(DOCX_SECTION_TARGETS[0][0]);
  const [stageId, setStageId] = useState(stages[0]?.stage_id || "");
  const [column, setColumn] = useState(DOCX_STAGE_COLUMN_TARGETS[3][0]);
  const [mode, setMode] = useState<"append" | "replace">("append");

  const assignedLabel = assignmentLabel(item);
  const status = item.status || "unassigned";

  function submit() {
    if (isImage) {
      onApply({ item_index: index, action: "assign", target: { stage_id: stageId } });
      return;
    }
    if (targetKind === "section") {
      onApply({ item_index: index, action: "assign", target: { section }, mode });
    } else {
      onApply({ item_index: index, action: "assign", target: { stage_id: stageId, column }, mode });
    }
  }

  return (
    <li className="dir-item" data-testid={`dir-item-${index}`} data-status={status}>
      <div className="dir-item-head">
        <span className="dir-origin">
          {KIND_LABELS[item.kind] || item.kind} · {item.heading || "无标题"} · #{index + 1}
        </span>
        <span className={`dir-status dir-status-${status}`}>
          {status === "unassigned" ? "未归类" : STATUS_LABELS[status]}
        </span>
      </div>
      {isImage ? (
        <div className="dir-body">
          {item.url ? (
            <img className="dir-image" src={buildAuthenticatedUrl(item.url)} alt={item.name || "导入图片"} />
          ) : (
            <span className="dir-note">{item.name || "图片尚未就绪"}</span>
          )}
        </div>
      ) : (
        <p className="dir-body dir-text">{item.text}</p>
      )}
      {assignedLabel ? <p className="dir-result" data-testid={`dir-result-${index}`}>识别结果：已写入 {assignedLabel}</p> : <p className="dir-result" data-testid={`dir-result-${index}`}>识别结果：未归类（原文保留）</p>}
      <div className="dir-controls">
        {isImage ? (
          <>
            <select
              aria-label={`选择图片目标环节（#${index + 1}）`}
              value={stageId}
              disabled={busy}
              onChange={(event) => setStageId(event.target.value)}
            >
              {stages.map((stage, stageIndex) => (
                <option key={stage.stage_id || stageIndex} value={stage.stage_id}>
                  环节{stageIndex + 1}：{stage.title || "未命名"}
                </option>
              ))}
            </select>
            <button type="button" className="toolbar-button compact primary" disabled={busy || !stageId} onClick={submit}>
              绑定到环节素材
            </button>
          </>
        ) : (
          <>
            <select
              aria-label={`选择归类方式（#${index + 1}）`}
              value={targetKind}
              disabled={busy}
              onChange={(event) => setTargetKind(event.target.value as "section" | "stage")}
            >
              <option value="section">写入教案字段</option>
              <option value="stage">写入环节栏目</option>
            </select>
            {targetKind === "section" ? (
              <select
                aria-label={`选择教案字段（#${index + 1}）`}
                value={section}
                disabled={busy}
                onChange={(event) => setSection(event.target.value)}
              >
                {DOCX_SECTION_TARGETS.map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            ) : (
              <>
                <select
                  aria-label={`选择目标环节（#${index + 1}）`}
                  value={stageId}
                  disabled={busy}
                  onChange={(event) => setStageId(event.target.value)}
                >
                  {stages.map((stage, stageIndex) => (
                    <option key={stage.stage_id || stageIndex} value={stage.stage_id}>
                      环节{stageIndex + 1}：{stage.title || "未命名"}
                    </option>
                  ))}
                </select>
                <select
                  aria-label={`选择环节栏目（#${index + 1}）`}
                  value={column}
                  disabled={busy}
                  onChange={(event) => setColumn(event.target.value)}
                >
                  {DOCX_STAGE_COLUMN_TARGETS.map(([key, label]) => (
                    <option key={key} value={key}>{label}</option>
                  ))}
                </select>
              </>
            )}
            <select
              aria-label={`选择写入效果（#${index + 1}）`}
              value={mode}
              disabled={busy}
              onChange={(event) => setMode(event.target.value as "append" | "replace")}
            >
              <option value="append">追加（保留原内容）</option>
              <option value="replace">替换（覆盖原内容）</option>
            </select>
            <button type="button" className="toolbar-button compact primary" disabled={busy} onClick={submit}>
              采用
            </button>
          </>
        )}
        <button
          type="button"
          className="toolbar-button compact"
          disabled={busy || status === "ignored"}
          onClick={() => onApply({ item_index: index, action: "ignore" })}
        >
          忽略
        </button>
      </div>
    </li>
  );
}

export function DocxImportReview({
  mapping,
  unclassified,
  stages,
  busy,
  onApply
}: {
  mapping: LessonDocxImportMapping[];
  unclassified: LessonDocxUnclassified[];
  stages: LessonStage[];
  busy: boolean;
  onApply: (payload: ImportReviewApplyPayload) => void;
}) {
  const pending = unclassified.filter((item) => (item.status || "unassigned") === "unassigned").length;
  return (
    <div className="dir" data-testid="docx-import-review">
      <p className="dir-summary">
        共映射 {mapping.length} 处；待归类 {unclassified.length} 条，其中未处理 {pending} 条。全部归类后请整份核对再确认发布。
      </p>
      {mapping.length ? (
        <details className="dir-mapping">
          <summary>自动映射明细（{mapping.length} 处）</summary>
          <ul className="dir-mapping-list">
            {mapping.map((item, index) => (
              <li key={index}>
                <strong>{item.label}</strong>
                <small>{item.origin}</small>
                <span>{item.content}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <ul className="dir-list">
        {unclassified.map((item, index) => (
          <ImportReviewItem
            key={index}
            item={item}
            index={index}
            stages={stages}
            busy={busy}
            onApply={onApply}
          />
        ))}
        {!unclassified.length ? <li className="dir-empty">没有待归类内容。</li> : null}
      </ul>
    </div>
  );
}
