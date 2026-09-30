import { useState } from "react";
import type { LessonPlanProfile, LessonStage, QuestionBankQuestion } from "../types";
import { LessonCellEditor } from "./LessonCellEditor";
import { formatQuestion, splitLines, stageList } from "../lib/lessonSheet";

type Props = {
  draft: LessonPlanProfile;
  busy: boolean;
  searchResults: QuestionBankQuestion[];
  searchText: string;
  onStageFieldChange: (stageIndex: number, field: string, value: unknown) => void;
  onAddStage: () => void;
  onRemoveStage: (stageIndex: number) => void;
  onRemoveQuestion: (stageId: string, questionId: string) => void;
  onBindSearchResult: (stageId: string, questionId: string) => void;
  onBindManual: (stageId: string, manual: { text: string; answer: string; explanation: string }) => void;
  onSearchText: (value: string) => void;
  onRunSearch: () => void;
  onStageAiEdit: (stageIndex: number) => void;
};

const STAGE_TEXT_FIELDS: Array<[string, string, boolean]> = [
  ["material", "材料", true],
  ["teacher_activities", "教师活动（每行一条）", true],
  ["student_activities", "学生活动（每行一条）", true],
  ["question_chain", "问题链（每行一问）", true],
  ["knowledge_conclusion", "知识结论", true],
  ["design_intent", "设计意图", true],
  ["knowledge_point", "知识点", false]
];

function StageQuestionTools({
  stage,
  busy,
  searchResults,
  searchText,
  onSearchText,
  onRunSearch,
  onBindSearchResult,
  onBindManual
}: {
  stage: LessonStage;
  busy: boolean;
  searchResults: QuestionBankQuestion[];
  searchText: string;
  onSearchText: (value: string) => void;
  onRunSearch: () => void;
  onBindSearchResult: (stageId: string, questionId: string) => void;
  onBindManual: (stageId: string, manual: { text: string; answer: string; explanation: string }) => void;
}) {
  const [manualOpen, setManualOpen] = useState(false);
  const [manual, setManual] = useState({ text: "", answer: "", explanation: "" });
  return (
    <details className="lpt-question-tools">
      <summary>添加题目</summary>
      <div className="lpt-question-search">
        <input
          value={searchText}
          onChange={(event) => onSearchText(event.target.value)}
          placeholder="考点关键词检索题库，例如：人口迁移 推拉力"
          aria-label={`题目检索关键词（${stage.title}）`}
        />
        <button type="button" className="toolbar-button compact" disabled={busy} onClick={onRunSearch}>
          检索
        </button>
      </div>
      {searchResults.length ? (
        <ul className="lpt-question-candidates">
          {searchResults.map((item) => (
            <li key={item.question_id}>
              <span>
                {item.number || ""} {item.stem || item.task_text || ""}
                {item.answer_complete ? "" : "（答案缺失）"}
              </span>
              <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => onBindSearchResult(stage.stage_id, item.question_id)}>
                选用
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <button type="button" className="toolbar-button compact" onClick={() => setManualOpen((value) => !value)}>
        {manualOpen ? "收起手动录入" : "录入手动题目"}
      </button>
      {manualOpen ? (
        <div className="lpt-manual-form">
          <textarea aria-label={`手动题目题干（${stage.title}）`} value={manual.text} onChange={(event) => setManual({ ...manual, text: event.target.value })} placeholder="题干" />
          <textarea aria-label={`手动题目参考答案（${stage.title}）`} value={manual.answer} onChange={(event) => setManual({ ...manual, answer: event.target.value })} placeholder="参考答案（真实课堂必填）" />
          <textarea aria-label={`手动题目解析（${stage.title}）`} value={manual.explanation} onChange={(event) => setManual({ ...manual, explanation: event.target.value })} placeholder="解析（建议填写）" />
          <button
            type="button"
            className="toolbar-button compact primary"
            disabled={busy || !manual.text.trim()}
            onClick={() => {
              onBindManual(stage.stage_id, manual);
              setManual({ text: "", answer: "", explanation: "" });
            }}
          >
            加入本环节
          </button>
        </div>
      ) : null}
    </details>
  );
}

// 两列教学过程表：环节列（名称/时长/知识点）＋ 活动与素材列。
export function LessonProcessTable({
  draft,
  busy,
  searchResults,
  searchText,
  onStageFieldChange,
  onAddStage,
  onRemoveStage,
  onRemoveQuestion,
  onBindSearchResult,
  onBindManual,
  onSearchText,
  onRunSearch,
  onStageAiEdit
}: Props) {
  const stages = stageList(draft);
  return (
    <div className="lpt-table" data-testid="ldw-process-table">
      <div className="lpt-head" aria-hidden="true">
        <span>环节</span>
        <span>活动与素材</span>
      </div>
      {stages.map((stage, index) => (
        <div className="lpt-row" key={stage.stage_id || index} data-testid={`lpt-row-${index}`}>
          <div className="lpt-stage-col">
            <div className="lpt-stage-head">
              <strong>环节{index + 1}</strong>
              <span className="lpt-stage-actions">
                <button type="button" className="toolbar-button compact" disabled={busy} aria-label={`让 AI 修改环节${index + 1}`} onClick={() => onStageAiEdit(index)}>
                  AI 改
                </button>
                <button type="button" className="toolbar-button compact" disabled={busy} aria-label={`删除环节${index + 1}`} onClick={() => onRemoveStage(index)}>
                  删除
                </button>
              </span>
            </div>
            <LessonCellEditor
              value={stage.title || ""}
              label={`环节${index + 1}名称`}
              placeholder="环节名称"
              disabled={busy}
              testId={`lpt-stage-title-${index}`}
              onSave={(value) => onStageFieldChange(index, "title", value)}
            />
            <label className="lpt-minutes">
              时长
              <LessonCellEditor
                value={String(stage.minutes ?? "")}
                label={`环节${index + 1}时长`}
                placeholder="分钟"
                numeric
                disabled={busy}
                testId={`lpt-stage-minutes-${index}`}
                onSave={(value) => onStageFieldChange(index, "minutes", Number(value))}
              />
              分钟
            </label>
            <LessonCellEditor
              value={stage.knowledge_point || ""}
              label={`环节${index + 1}知识点`}
              placeholder="知识点"
              disabled={busy}
              onSave={(value) => onStageFieldChange(index, "knowledge_point", value)}
            />
          </div>
          <div className="lpt-content-col">
            {STAGE_TEXT_FIELDS.map(([field, label]) =>
              field === "knowledge_point" ? null : (
                <div className="lpt-field" key={field}>
                  <span className="lpt-field-label">{label.replace("（每行一条）", "").replace("（每行一问）", "")}</span>
                  <LessonCellEditor
                    value={Array.isArray((stage as unknown as Record<string, unknown>)[field])
                      ? ((stage as unknown as Record<string, unknown>)[field] as unknown[]).map((item) => String(item)).join("\n")
                      : String((stage as unknown as Record<string, unknown>)[field] ?? "")}
                    label={`环节${index + 1}${label}`}
                    multiline
                    disabled={busy}
                    onSave={(value) =>
                      onStageFieldChange(
                        index,
                        field,
                        field === "teacher_activities" || field === "student_activities" || field === "question_chain" ? splitLines(value) : value
                      )
                    }
                  />
                </div>
              )
            )}
            <div className="lpt-field">
              <span className="lpt-field-label">环节题目</span>
              {stage.questions?.length ? (
                <ul className="lpt-question-list">
                  {stage.questions.map((question) => (
                    <li key={question.question_id}>
                      <p>{formatQuestion(question)}</p>
                      <button type="button" className="toolbar-button compact" disabled={busy} aria-label={`移除环节${index + 1}题目`} onClick={() => onRemoveQuestion(stage.stage_id, question.question_id)}>
                        移除
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="lse-cell-empty">本环节还没有题目</p>
              )}
              <StageQuestionTools
                stage={stage}
                busy={busy}
                searchResults={searchResults}
                searchText={searchText}
                onSearchText={onSearchText}
                onRunSearch={onRunSearch}
                onBindSearchResult={onBindSearchResult}
                onBindManual={onBindManual}
              />
            </div>
          </div>
        </div>
      ))}
      <button type="button" className="toolbar-button compact" disabled={busy} onClick={onAddStage} data-testid="lpt-add-stage">
        ＋ 添加环节
      </button>
    </div>
  );
}
