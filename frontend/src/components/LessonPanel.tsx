import { useState } from "react";
import type { LessonRecord, LessonStage, SceneSnapshot } from "../types";

type TopicMetadata = {
  topic_pack?: { name?: string; teaching_mode?: string; source_policy?: string };
  evidence_layer?: Array<{ evidence_id: string; label: string; type?: string }>;
  visualizations?: Array<{ id: string; status: string; reason?: string }>;
};

type EvidenceQuestion = {
  question_evidence_rules?: { required?: boolean; evidence_options?: Array<{ evidence_id: string; label: string }> };
  argument_chain?: string[];
  remediation_task?: string;
};

type Props = {
  lessons: LessonRecord[];
  activeLesson: LessonRecord | null;
  busy: boolean;
  onSelectLesson: (lessonId: string) => void;
  onApplyScene: (stageId: string) => void;
  onCaptureScene: (stageId: string) => Promise<SceneSnapshot | null>;
  onSaveStages: (stages: LessonStage[]) => void;
  onImportText: (text: string) => void;
  onStartClass: () => void;
  onClose: () => void;
};

function sceneSummary(stage: LessonStage): string {
  const parts: string[] = [];
  if (stage.scene.basemap_id) {
    parts.push(`底图 ${stage.scene.basemap_id.replace("amap_", "")}`);
  }
  if (stage.scene.templates.length) {
    parts.push(`${stage.scene.templates.length} 个模板`);
  }
  const visible = Object.values(stage.scene.layer_visibility).filter(Boolean).length;
  if (visible) {
    parts.push(`${visible} 个可见图层`);
  }
  if (stage.scene.annotations.length) {
    parts.push(`${stage.scene.annotations.length} 处标注`);
  }
  if (stage.scene.visual_query) {
    parts.push("指标查询");
  }
  return parts.length ? parts.join(" · ") : "尚未绑定场景";
}

export function LessonPanel({
  lessons,
  activeLesson,
  busy,
  onSelectLesson,
  onApplyScene,
  onCaptureScene,
  onSaveStages,
  onImportText,
  onStartClass,
  onClose
}: Props) {
  const [expandedStageId, setExpandedStageId] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [editingStageId, setEditingStageId] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [editMinutes, setEditMinutes] = useState(5);
  const [captureHint, setCaptureHint] = useState("");

  const totalMinutes = activeLesson?.stages.reduce((sum, stage) => sum + (stage.minutes || 0), 0) || 0;
  const topicMetadata = (activeLesson?.metadata || {}) as TopicMetadata;

  function beginEdit(stage: LessonStage) {
    setEditingStageId(stage.stage_id);
    setEditTitle(stage.title);
    setEditMinutes(stage.minutes);
  }

  function saveEdit() {
    if (!activeLesson || !editingStageId) {
      return;
    }
    const stages = activeLesson.stages.map((stage) =>
      stage.stage_id === editingStageId
        ? { ...stage, title: editTitle.trim() || stage.title, minutes: Math.max(1, editMinutes) }
        : stage
    );
    onSaveStages(stages);
    setEditingStageId("");
  }

  async function captureScene(stageId: string) {
    setCaptureHint("");
    const snapshot = await onCaptureScene(stageId);
    if (snapshot) {
      setCaptureHint(stageId);
      window.setTimeout(() => setCaptureHint(""), 2500);
    }
  }

  return (
    <section className="lesson-panel glass-panel" data-testid="lesson-panel">
      <header className="lesson-panel-header">
        <div>
          <p className="panel-tag">Lesson Workspace</p>
          <h2>备课工作台</h2>
        </div>
        <button type="button" className="mini-control" onClick={onClose} aria-label="关闭备课面板">
          ×
        </button>
      </header>

      <div className="lesson-panel-toolbar">
        <select
          value={activeLesson?.lesson_id || ""}
          onChange={(event) => onSelectLesson(event.target.value)}
          data-testid="lesson-select"
        >
          <option value="" disabled>
            选择课时…
          </option>
          {lessons.map((lesson) => (
            <option key={lesson.lesson_id} value={lesson.lesson_id}>
              {lesson.title}
            </option>
          ))}
        </select>
        <button type="button" className="toolbar-button compact" onClick={() => setImportOpen((value) => !value)}>
          AI 导入教案
        </button>
        <button
          type="button"
          className="toolbar-button compact primary"
          disabled={!activeLesson || busy}
          onClick={onStartClass}
          data-testid="start-class"
        >
          开始上课
        </button>
      </div>

      {importOpen ? (
        <div className="lesson-import-box">
          <textarea
            value={importText}
            placeholder="粘贴教案文本（Markdown / 纯文本），AI 将解析为结构化环节。"
            onChange={(event) => setImportText(event.target.value)}
          />
          <div className="lesson-import-actions">
            <button
              type="button"
              className="toolbar-button compact primary"
              disabled={!importText.trim() || busy}
              onClick={() => {
                onImportText(importText.trim());
                setImportText("");
                setImportOpen(false);
              }}
            >
              解析并导入
            </button>
            <button type="button" className="toolbar-button compact" onClick={() => setImportOpen(false)}>
              取消
            </button>
          </div>
        </div>
      ) : null}

      {activeLesson ? (
        <>
          <div className="lesson-meta">
            <strong>{activeLesson.title}</strong>
            <span>
              {activeLesson.grade || activeLesson.subject} · {activeLesson.stages.length} 个环节 · 共 {totalMinutes} 分钟
            </span>
          </div>

          {topicMetadata.topic_pack ? (
            <div className="topic-pack-card">
              <strong>{topicMetadata.topic_pack.name || "人口专题包"}</strong>
              <p>{topicMetadata.topic_pack.teaching_mode}</p>
              {topicMetadata.evidence_layer?.length ? (
                <div className="topic-evidence-list">
                  {topicMetadata.evidence_layer.map((item) => (
                    <span key={item.evidence_id} title={item.type || "evidence"}>证据：{item.label}</span>
                  ))}
                </div>
              ) : null}
              {topicMetadata.visualizations?.length ? (
                <div className="topic-visualization-list">
                  {topicMetadata.visualizations.map((item) => (
                    <span key={item.id} className={item.status === "ready" ? "ready" : "blocked"} title={item.reason || ""}>
                      {item.status === "ready" ? "可用" : "待数据"}：{item.id}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          <ol className="lesson-stage-list">
            {activeLesson.stages.map((stage, index) => {
              const expanded = expandedStageId === stage.stage_id;
              const editing = editingStageId === stage.stage_id;
              return (
                <li key={stage.stage_id} className={`lesson-stage ${expanded ? "expanded" : ""}`}>
                  <div className="lesson-stage-row" onClick={() => setExpandedStageId(expanded ? "" : stage.stage_id)}>
                    <span className="lesson-stage-index">{index + 1}</span>
                    {editing ? (
                      <span className="lesson-stage-edit" onClick={(event) => event.stopPropagation()}>
                        <input value={editTitle} onChange={(event) => setEditTitle(event.target.value)} />
                        <input
                          type="number"
                          min={1}
                          max={60}
                          value={editMinutes}
                          onChange={(event) => setEditMinutes(Number(event.target.value) || 1)}
                        />
                        <button type="button" className="toolbar-button compact primary" onClick={saveEdit}>
                          保存
                        </button>
                      </span>
                    ) : (
                      <span className="lesson-stage-title">
                        <strong>{stage.title}</strong>
                        <em>{stage.minutes} 分钟 · {sceneSummary(stage)}</em>
                      </span>
                    )}
                  </div>

                  {expanded ? (
                    <div className="lesson-stage-detail">
                      {stage.script.length ? (
                        <div className="lesson-stage-block">
                          <span className="lesson-block-label">教师串联语</span>
                          {stage.script.map((line, lineIndex) => (
                            <p key={lineIndex}>{line}</p>
                          ))}
                        </div>
                      ) : null}
                      {stage.questions.length ? (
                        <div className="lesson-stage-block">
                          <span className="lesson-block-label">课堂提问</span>
                          {stage.questions.map((question) => {
                            const evidenceQuestion = question as typeof question & EvidenceQuestion;
                            const evidenceRules = evidenceQuestion.question_evidence_rules;
                            return (
                            <div key={question.question_id} className="lesson-question">
                              <p>
                                {question.type === "choice" ? "🗳️" : "💬"} {question.text}
                              </p>
                              {question.misconceptions.length ? (
                                <em>预设误区：{question.misconceptions.map((item) => item.tag).join("、")}</em>
                              ) : null}
                              {evidenceRules?.required ? (
                                <div className="lesson-question-evidence">
                                  <strong>学生必须取证：</strong>{evidenceRules.evidence_options?.map((item) => item.label).join("；")}
                                  {evidenceQuestion.argument_chain?.length ? <em>论证链：{evidenceQuestion.argument_chain.join(" → ")}</em> : null}
                                  {evidenceQuestion.remediation_task ? <em>课后变式：{evidenceQuestion.remediation_task}</em> : null}
                                </div>
                              ) : null}
                            </div>
                            );
                          })}
                        </div>
                      ) : null}
                      <div className="lesson-stage-actions">
                        <button
                          type="button"
                          className="toolbar-button compact primary"
                          disabled={busy}
                          onClick={() => onApplyScene(stage.stage_id)}
                          data-testid={`apply-scene-${stage.stage_id}`}
                        >
                          预览场景
                        </button>
                        <button
                          type="button"
                          className="toolbar-button compact"
                          disabled={busy}
                          onClick={() => void captureScene(stage.stage_id)}
                        >
                          {captureHint === stage.stage_id ? "✓ 已保存" : "存当前地图为场景"}
                        </button>
                        <button type="button" className="toolbar-button compact" onClick={() => beginEdit(stage)}>
                          编辑
                        </button>
                      </div>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </>
      ) : (
        <p className="lesson-empty">选择内置课时或导入教案开始备课。</p>
      )}
    </section>
  );
}
