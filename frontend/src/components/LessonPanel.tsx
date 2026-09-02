import { useEffect, useState } from "react";
import type {
  LessonRecord,
  LessonStage,
  PopulationLessonPrepInput,
  PopulationLessonPrepResult,
  PopulationSourceCard,
  PopulationSourceVersion,
  SceneSnapshot
} from "../types";

const EMPTY_POPULATION_SOURCES: PopulationSourceCard[] = [];
const EMPTY_POPULATION_SOURCE_VERSIONS: PopulationSourceVersion[] = [];

type Props = {
  lessons: LessonRecord[];
  activeLesson: LessonRecord | null;
  busy: boolean;
  onSelectLesson: (lessonId: string) => void;
  onApplyScene: (stageId: string) => void;
  onCaptureScene: (stageId: string) => Promise<SceneSnapshot | null>;
  onSaveStages: (stages: LessonStage[]) => void;
  onImportText: (text: string) => void;
  prepResult?: PopulationLessonPrepResult | null;
  prepProgress?: string;
  onPrepareLesson?: (input: PopulationLessonPrepInput) => void;
  populationSources?: PopulationSourceCard[];
  populationSourceVersions?: PopulationSourceVersion[];
  populationSourceVersion?: string;
  onChangePopulationSourceVersion?: (version: string) => void;
  onResolvePrepChangeSet?: (decision: "apply" | "reject", acceptedStageIds: string[]) => void;
  onStartClass: () => void;
  onStartDesign?: () => void;
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
  if (stage.scene.globe?.enabled) {
    parts.push(`3D ${stage.scene.globe.themes?.length || 0} 个主题`);
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
  prepResult = null,
  prepProgress = "",
  onPrepareLesson,
  populationSources = EMPTY_POPULATION_SOURCES,
  populationSourceVersions = EMPTY_POPULATION_SOURCE_VERSIONS,
  populationSourceVersion = "",
  onChangePopulationSourceVersion,
  onResolvePrepChangeSet,
  onStartClass,
  onStartDesign,
  onClose
}: Props) {
  const [expandedStageId, setExpandedStageId] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [editingStageId, setEditingStageId] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [editMinutes, setEditMinutes] = useState(5);
  const [captureHint, setCaptureHint] = useState("");
  const [prepOpen, setPrepOpen] = useState(false);
  const [prepObjective, setPrepObjective] = useState("");
  const [prepDuration, setPrepDuration] = useState(40);
  const [prepRegion, setPrepRegion] = useState("中国");
  const [acceptedStageIds, setAcceptedStageIds] = useState<string[]>([]);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);

  const totalMinutes = activeLesson?.stages.reduce((sum, stage) => sum + (stage.minutes || 0), 0) || 0;

  useEffect(() => {
    if (!prepResult?.change_set) {
      setAcceptedStageIds([]);
      return;
    }
    setAcceptedStageIds(prepResult.change_set.changes.map((change) => change.stage_id));
  }, [prepResult]);

  useEffect(() => {
    setSelectedSourceIds(populationSources.map((source) => source.id));
  }, [populationSources]);

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
        {onStartDesign ? (
          <button type="button" className="toolbar-button compact primary" onClick={onStartDesign} disabled={busy} data-testid="lesson-design-toggle">
            共创教案
          </button>
        ) : null}
        {onPrepareLesson ? (
          <button
            type="button"
            className="toolbar-button compact"
            disabled={!activeLesson || busy}
            onClick={() => {
              setPrepObjective(activeLesson?.objectives.join("；") || activeLesson?.title || "");
              setPrepDuration(Math.max(10, totalMinutes || 40));
              setPrepOpen((value) => !value);
            }}
            data-testid="population-prep-toggle"
          >
            人口专题智能备课
          </button>
        ) : null}
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

      {prepOpen && activeLesson && onPrepareLesson ? (
        <div className="population-prep-box" data-testid="population-prep-form">
          <div className="population-prep-heading">
            <div>
              <strong>题—图—证据备课</strong>
              <span>只生成草稿；预演通过后仍需教师逐环节确认。</span>
            </div>
            <span className="population-scope-chip">教师端 · 人口地理</span>
          </div>
          <label>
            教学目标
            <textarea
              value={prepObjective}
              onChange={(event) => setPrepObjective(event.target.value)}
              placeholder="例如：运用人口密度图和胡焕庸线，描述并解释中国人口分布格局。"
            />
          </label>
          <div className="population-prep-grid">
            <label>
              课时长度（分钟）
              <input
                type="number"
                min={10}
                max={180}
                value={prepDuration}
                onChange={(event) => setPrepDuration(Number(event.target.value) || 40)}
              />
            </label>
            <label>
              目标区域
              <input value={prepRegion} onChange={(event) => setPrepRegion(event.target.value)} />
            </label>
            {populationSourceVersions.length ? (
              <label>
                来源包版本
                <select
                  value={populationSourceVersion}
                  onChange={(event) => onChangePopulationSourceVersion?.(event.target.value)}
                  disabled={busy}
                >
                  {populationSourceVersions.map((version) => (
                    <option key={version.version} value={version.version}>
                      {version.version} · {version.released_at}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
          {populationSources.length ? (
            <details className="population-source-picker">
              <summary>
                教学来源 {selectedSourceIds.length}/{populationSources.length}
              </summary>
              <div className="population-source-list">
                {populationSources.map((source) => (
                  <label key={source.id} className="population-source-item">
                    <input
                      type="checkbox"
                      checked={selectedSourceIds.includes(source.id)}
                      onChange={(event) =>
                        setSelectedSourceIds((previous) =>
                          event.target.checked
                            ? [...previous, source.id]
                            : previous.filter((sourceId) => sourceId !== source.id)
                        )
                      }
                    />
                    <span>
                      <strong>{source.title}</strong>
                      <em>
                        {source.source_year || "年份待核"} · {source.status} · {source.field_unit || source.spatial_scale || "教学资料"}
                      </em>
                      {source.limitations[0] ? <small>{source.limitations[0]}</small> : null}
                    </span>
                  </label>
                ))}
              </div>
            </details>
          ) : null}
          <div className="lesson-import-actions">
            <button
              type="button"
              className="toolbar-button compact primary"
              disabled={busy || !prepObjective.trim() || (populationSources.length > 0 && selectedSourceIds.length === 0)}
              onClick={() =>
                onPrepareLesson({
                  objective: prepObjective.trim(),
                  grade: activeLesson.grade,
                  duration_minutes: prepDuration,
                  region: prepRegion.trim() || "中国",
                  years: ["2020"],
                  source_ids: selectedSourceIds,
                  source_version: populationSourceVersion
                })
              }
              data-testid="population-prep-submit"
            >
              生成并预演
            </button>
            <button type="button" className="toolbar-button compact" onClick={() => setPrepOpen(false)}>
              收起
            </button>
          </div>
          {prepProgress ? <p className="population-prep-progress">{prepProgress}</p> : null}
        </div>
      ) : null}

      {prepResult?.change_set && onResolvePrepChangeSet ? (
        <div className="population-change-set" data-testid="population-change-set">
          <div className="population-prep-heading">
            <div>
              <strong>教师确认式变更草稿</strong>
              <span>
                来源包 {prepResult.change_set.source_version} · 预演 {prepResult.rehearsal.status === "passed" ? "通过" : "未通过"}
              </span>
            </div>
            <span className="population-scope-chip">{prepResult.change_set.source_refs.length} 条来源</span>
          </div>
          {prepResult.warnings.length ? (
            <details className="population-prep-warnings">
              <summary>{prepResult.warnings.length} 条来源或教学限制提示</summary>
              <ul>
                {prepResult.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </details>
          ) : null}
          <div className="population-change-list">
            {prepResult.change_set.changes.map((change) => {
              const checked = acceptedStageIds.includes(change.stage_id);
              return (
                <label key={change.stage_id} className="population-change-item">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(event) =>
                      setAcceptedStageIds((previous) =>
                        event.target.checked
                          ? [...previous, change.stage_id]
                          : previous.filter((stageId) => stageId !== change.stage_id)
                      )
                    }
                  />
                  <span>
                    <strong>{change.title}</strong>
                    <em>
                      {change.change_types.join(" · ")} · {change.evidence_count} 条证据
                    </em>
                  </span>
                </label>
              );
            })}
          </div>
          <div className="lesson-import-actions">
            <button
              type="button"
              className="toolbar-button compact primary"
              disabled={busy || acceptedStageIds.length === 0}
              onClick={() => onResolvePrepChangeSet("apply", acceptedStageIds)}
              data-testid="population-prep-apply"
            >
              应用选中环节
            </button>
            <button
              type="button"
              className="toolbar-button compact"
              disabled={busy}
              onClick={() => onResolvePrepChangeSet("reject", [])}
            >
              放弃草稿
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
                          {stage.questions.map((question) => (
                            <div key={question.question_id} className="lesson-question">
                              <p>
                                {question.type === "choice" ? "🗳️" : "💬"} {question.text}
                              </p>
                              {question.misconceptions.length ? (
                                <em>预设误区：{question.misconceptions.map((item) => item.tag).join("、")}</em>
                              ) : null}
                            </div>
                          ))}
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
