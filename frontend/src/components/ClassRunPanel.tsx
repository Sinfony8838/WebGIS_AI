import { useEffect, useMemo, useState } from "react";
import type { ClassSessionRecord, LessonQuestion, LessonRecord, LessonStage, ObservationVerdict } from "../types";

type Props = {
  lesson: LessonRecord;
  session: ClassSessionRecord;
  currentStageId: string;
  stageEnteredAt: number | null;
  busy: boolean;
  quizActive: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onEnterStage: (stageId: string) => void;
  onLaunchQuestion: (questionId: string, stageId: string) => void;
  onLaunchAdhocQuestion: (text: string, options: string[]) => void;
  onObservation: (verdict: ObservationVerdict, tag: string, note: string, questionId: string) => void;
  onSnapshot: () => void;
  onEndSession: () => void;
  visibleCatalogLayerIds?: string[];
  onFocusEvidenceLayer?: (datasetId: string, stageDatasetIds: string[]) => void;
  onRequestPlaneView?: () => void;
  /** 把备课时预设的追问一键派发给教学智能体（不传则退化为纯展示）。 */
  onAssistantPrompt?: (prompt: string) => void;
};

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

const OPTION_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H"];
const EVIDENCE_LAYER_LABELS: Record<string, string> = {
  china_climate_types: "① 气候",
  china_terrain_steps: "② 地形",
  china_major_rivers: "③ 河流",
  china_vegetation_zones: "④ 植被验证",
  china_province_gdp_per_capita: "⑤ 经济"
};

export function ClassRunPanel({
  lesson,
  currentStageId,
  stageEnteredAt,
  busy,
  quizActive,
  collapsed,
  onToggleCollapsed,
  onEnterStage,
  onLaunchQuestion,
  onLaunchAdhocQuestion,
  onObservation,
  onSnapshot,
  onEndSession,
  visibleCatalogLayerIds = [],
  onFocusEvidenceLayer,
  onRequestPlaneView,
  onAssistantPrompt
}: Props) {
  const [nowTick, setNowTick] = useState(Date.now());
  const [recordVerdict, setRecordVerdict] = useState<ObservationVerdict | null>(null);
  const [recordTag, setRecordTag] = useState("");
  const [recordNote, setRecordNote] = useState("");
  const [recordQuestionId, setRecordQuestionId] = useState("");
  const [savedFlash, setSavedFlash] = useState(false);
  const [expandedQuestionId, setExpandedQuestionId] = useState("");
  const [oralQuestionId, setOralQuestionId] = useState("");
  const [revealedOralQuestionId, setRevealedOralQuestionId] = useState("");
  const [scriptOpen, setScriptOpen] = useState(false);
  const [adhocText, setAdhocText] = useState("");
  const [adhocOptions, setAdhocOptions] = useState("");

  useEffect(() => {
    const interval = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  // 切换环节后回到默认展示状态
  useEffect(() => {
    setExpandedQuestionId("");
    setOralQuestionId("");
    setRevealedOralQuestionId("");
    setScriptOpen(true);
    resetRecord();
  }, [currentStageId]);

  const currentStage: LessonStage | undefined = useMemo(
    () => lesson.stages.find((stage) => stage.stage_id === currentStageId),
    [lesson, currentStageId]
  );
  const currentStageIndex = lesson.stages.findIndex((stage) => stage.stage_id === currentStageId);

  const elapsedSeconds = stageEnteredAt ? Math.max(0, (nowTick - stageEnteredAt) / 1000) : 0;
  const plannedSeconds = (currentStage?.minutes || 0) * 60;
  const overtime = plannedSeconds > 0 && elapsedSeconds > plannedSeconds;
  const stageProgress = plannedSeconds > 0 ? Math.min(1, elapsedSeconds / plannedSeconds) : 0;

  const misconceptionTags = useMemo(() => {
    const tags = new Set<string>();
    currentStage?.questions.forEach((question) =>
      question.misconceptions.forEach((item) => item.tag && tags.add(item.tag))
    );
    return Array.from(tags);
  }, [currentStage]);

  function submitObservation(verdict: ObservationVerdict) {
    if (verdict !== "misconception") {
      onObservation(verdict, "", recordNote.trim(), recordQuestionId);
      resetRecord();
      flashSaved();
      return;
    }
    // 误区需要选标签，切换到展开态
    setRecordVerdict("misconception");
  }

  function confirmMisconception() {
    onObservation("misconception", recordTag.trim(), recordNote.trim(), recordQuestionId);
    resetRecord();
    flashSaved();
  }

  function recordQuestionMisconception(question: LessonQuestion, tag: string) {
    onObservation("misconception", tag, "", question.question_id);
    flashSaved();
  }

  function resetRecord() {
    setRecordVerdict(null);
    setRecordTag("");
    setRecordNote("");
    setRecordQuestionId("");
  }

  function flashSaved() {
    setSavedFlash(true);
    window.setTimeout(() => setSavedFlash(false), 1800);
  }

  function toggleOral(questionId: string) {
    if (oralQuestionId === questionId) {
      setOralQuestionId("");
      setRevealedOralQuestionId("");
      setRecordQuestionId("");
      return;
    }
    // 展开朗读提问卡，同时为学情速记预置该题，便于记录学生表现。
    setOralQuestionId(questionId);
    setRevealedOralQuestionId("");
    setRecordQuestionId(questionId);
  }

  function presentQuestion(question: LessonQuestion) {
    if (oralQuestionId !== question.question_id) {
      onLaunchQuestion(question.question_id, currentStage?.stage_id || "");
    }
    toggleOral(question.question_id);
  }

  function launchAdhoc() {
    const text = adhocText.trim();
    if (!text) {
      return;
    }
    const options = adhocOptions
      .split(/[/／;；]/)
      .map((item) => item.trim())
      .filter(Boolean);
    onLaunchAdhocQuestion(text, options);
    setAdhocText("");
    setAdhocOptions("");
  }

  if (collapsed) {
    return (
      <button
        type="button"
        className="class-run-panel-tab glass-panel"
        onClick={onToggleCollapsed}
        data-testid="class-run-panel-expand"
        title="展开课中面板"
      >
        <span className="tab-caret">›</span>
        <span className="tab-label">课中</span>
        <span className={`tab-timer ${overtime ? "overtime" : ""}`}>{formatElapsed(elapsedSeconds)}</span>
        <span className="tab-stage-index">
          {currentStageIndex >= 0 ? currentStageIndex + 1 : "-"}/{lesson.stages.length}
        </span>
      </button>
    );
  }

  return (
    <section className="class-run-panel glass-panel" data-testid="class-run-panel">
      <header className="class-panel-header">
        <div className="class-panel-heading">
          <span className="class-panel-kicker">课中 · {lesson.title}</span>
          <div className="class-panel-status">
            <span className={`class-timer ${overtime ? "overtime" : ""}`} data-testid="stage-timer">
              ⏱ {formatElapsed(elapsedSeconds)}
              {currentStage ? ` / ${currentStage.minutes}:00` : ""}
            </span>
            <span className="class-session-label">
              教师端课堂记录 · 仅采集教师观察
              {savedFlash ? <em className="record-saved"> ✓ 已记录</em> : null}
            </span>
          </div>
        </div>
        <button
          type="button"
          className="class-panel-collapse"
          onClick={onToggleCollapsed}
          aria-label="收起课中面板"
          data-testid="class-run-panel-collapse"
        >
          ‹
        </button>
      </header>

      <div className="class-panel-stage-progress">
        <div
          className={`class-panel-stage-progress-fill ${overtime ? "overtime" : ""}`}
          style={{ width: `${Math.round(stageProgress * 100)}%` }}
        />
      </div>

      <nav className="class-panel-stages" aria-label="课堂环节">
        {lesson.stages.map((stage, index) => {
          const active = stage.stage_id === currentStageId;
          const done = currentStageIndex >= 0 && index < currentStageIndex;
          return (
            <button
              key={stage.stage_id}
              type="button"
              className={`class-stage-item ${active ? "active" : ""} ${done ? "done" : ""}`}
              disabled={busy}
              onClick={() => onEnterStage(stage.stage_id)}
              data-testid={`stage-chip-${stage.stage_id}`}
              title={`${stage.title}（计划 ${stage.minutes} 分钟）`}
            >
              <span className="stage-item-track">
                <span className="stage-item-dot">{done ? "✓" : index + 1}</span>
                {index < lesson.stages.length - 1 ? <span className="stage-item-line" /> : null}
              </span>
              <span className="stage-item-body">
                <span className="stage-item-title">{stage.title}</span>
                <span className="stage-item-meta">
                  {stage.minutes}′
                  {stage.questions.length ? ` · ${stage.questions.length} 问` : ""}
                </span>
              </span>
            </button>
          );
        })}
      </nav>

      <div className="class-panel-current">
        {currentStage?.script.length ? (
          <div className="class-panel-script">
            <button type="button" className="class-panel-section-toggle" onClick={() => setScriptOpen((value) => !value)}>
              讲稿提示 {scriptOpen ? "▾" : "▸"}
            </button>
            {scriptOpen ? (
              <ul>
                {currentStage.script.map((line, index) => (
                  <li key={index}>{line}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        {currentStage?.teacher_guidance ? (
          <div className="class-stage-guidance" data-testid="stage-teacher-guidance">
            <div className="class-stage-guidance-head">
              <span className="question-detail-label">教师环节卡</span>
              <strong>{currentStage.teacher_guidance.observation_prompt || "先观察地图，再用证据回答。"}</strong>
            </div>
            {currentStage.teacher_guidance.evidence_points?.length ? (
              <div className="class-stage-evidence-points">
                {currentStage.teacher_guidance.evidence_points.map((point) => (
                  <span key={point}>{point}</span>
                ))}
              </div>
            ) : null}
            <dl className="class-stage-guidance-grid">
              {currentStage.teacher_guidance.oral_question ? (
                <><dt>口头问题</dt><dd>{currentStage.teacher_guidance.oral_question}</dd></>
              ) : null}
              {currentStage.teacher_guidance.expected_response ? (
                <><dt>预期回答</dt><dd>{currentStage.teacher_guidance.expected_response}</dd></>
              ) : null}
              {currentStage.teacher_guidance.misconception_cue ? (
                <><dt>误区提醒</dt><dd>{currentStage.teacher_guidance.misconception_cue}</dd></>
              ) : null}
              {currentStage.teacher_guidance.closing ? (
                <><dt>教师收束</dt><dd>{currentStage.teacher_guidance.closing}</dd></>
              ) : null}
              {currentStage.teacher_guidance.fallback ? (
                <><dt>备用方案</dt><dd>{currentStage.teacher_guidance.fallback}</dd></>
              ) : null}
            </dl>
          </div>
        ) : null}

        {currentStage?.scene.globe?.enabled && onRequestPlaneView ? (
          <div className="class-stage-view-handoff" data-testid="stage-view-handoff">
            <span>3D 用于宏观导入；开始读图和答题时回到二维规范专题图。</span>
            <button type="button" className="toolbar-button compact" onClick={onRequestPlaneView}>
              切回二维判读
            </button>
          </div>
        ) : null}

        {currentStage?.scene.catalog_layers && currentStage.scene.catalog_layers.length > 1 && onFocusEvidenceLayer ? (
          <div className="class-evidence-layer-steps" data-testid="evidence-layer-steps">
            <div className="class-evidence-layer-heading">
              <span className="question-detail-label">证据图层步骤</span>
              <small>逐张聚焦，避免图层堆叠</small>
            </div>
            <div className="class-evidence-layer-buttons">
              {currentStage.scene.catalog_layers.map((datasetId) => (
                <button
                  key={datasetId}
                  type="button"
                  className={`evidence-layer-step ${visibleCatalogLayerIds.includes(datasetId) ? "active" : ""}`}
                  disabled={busy}
                  onClick={() => onFocusEvidenceLayer(datasetId, currentStage.scene.catalog_layers || [])}
                  data-testid={`evidence-layer-${datasetId}`}
                >
                  {EVIDENCE_LAYER_LABELS[datasetId] || datasetId}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {currentStage?.assistant_prompts.length && onAssistantPrompt ? (
          <div className="class-panel-assistant-prompts" data-testid="stage-assistant-prompts">
            <span className="question-detail-label">AI 追问</span>
            <div className="assistant-prompt-chips">
              {currentStage.assistant_prompts.map((prompt, index) => (
                <button
                  key={index}
                  type="button"
                  className="assistant-prompt-chip"
                  disabled={busy}
                  onClick={() => onAssistantPrompt(prompt)}
                  data-testid={`stage-assistant-prompt-${index}`}
                  title={prompt}
                >
                  ✦ {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {currentStage?.questions.length ? (
          <div className="class-panel-questions">
            {currentStage.questions.map((question) => {
              const expanded = expandedQuestionId === question.question_id;
              return (
                <article key={question.question_id} className={`class-question-card ${expanded ? "expanded" : ""}`}>
                  <button
                    type="button"
                    className="class-question-head"
                    onClick={() => setExpandedQuestionId(expanded ? "" : question.question_id)}
                    data-testid={`question-toggle-${question.question_id}`}
                  >
                    <span className={`question-type-badge ${question.type}`}>
                      {question.type === "choice" ? "选择" : "问答"}
                    </span>
                    <span className="class-question-text">{question.text}</span>
                  </button>

                  {oralQuestionId === question.question_id ? (
                    <div className="class-oral-prompt" data-testid={`oral-prompt-${question.question_id}`}>
                      <div className="class-oral-prompt-head">
                        <span className="class-oral-prompt-tag">朗读提问卡 · 教师朗读</span>
                        <button
                          type="button"
                          className="mini-control"
                          onClick={() => toggleOral(question.question_id)}
                          aria-label="结束朗读"
                        >
                          ×
                        </button>
                      </div>
                      <p className="class-oral-prompt-text">{question.text}</p>
                      {question.options.length ? (
                        <ol className="class-oral-options">
                          {question.options.map((option, index) => (
                            <li key={index}>
                              <span>{OPTION_LABELS[index] || index + 1}</span>
                              {option}
                            </li>
                          ))}
                        </ol>
                      ) : null}
                      {revealedOralQuestionId !== question.question_id ? (
                        <button
                          type="button"
                          className="toolbar-button compact class-reveal-answer"
                          onClick={() => setRevealedOralQuestionId(question.question_id)}
                          data-testid={`oral-reveal-${question.question_id}`}
                        >
                          显示答案与教师收束
                        </button>
                      ) : null}
                      {revealedOralQuestionId === question.question_id && question.options.length && question.answer_index !== null ? (
                        <p className="class-oral-answer" data-testid={`oral-answer-${question.question_id}`}>
                          参考答案：{OPTION_LABELS[question.answer_index] || question.answer_index + 1}. {question.options[question.answer_index]}
                        </p>
                      ) : null}
                      {revealedOralQuestionId === question.question_id && question.expected_points.length ? (
                        <div className="question-points">
                          <span className="question-detail-label">答案要点</span>
                          {question.expected_points.map((point) => (
                            <span key={point} className="point-chip">{point}</span>
                          ))}
                        </div>
                      ) : null}
                      {revealedOralQuestionId === question.question_id && question.argument_chain?.length ? (
                        <div className="question-argument-chain">
                          <span className="question-detail-label">标准论证链</span>
                          <ol>
                            {question.argument_chain.map((step) => <li key={step}>{step}</li>)}
                          </ol>
                        </div>
                      ) : null}
                      {revealedOralQuestionId === question.question_id && question.evidence_refs?.length ? (
                        <div className="question-evidence-refs">
                          <span className="question-detail-label">证据来源</span>
                          {question.evidence_refs.map((evidence) => (
                            <span key={evidence.source_id} className="evidence-chip">
                              {evidence.title || evidence.source_id}{evidence.source_year ? ` · ${evidence.source_year}` : ""}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      {revealedOralQuestionId === question.question_id && question.misconceptions.length ? (
                        <div className="question-misconceptions">
                          <span className="question-detail-label">易错提醒</span>
                          {question.misconceptions.map((item) => (
                            <span key={item.tag} className="tag-chip">{item.tag}</span>
                          ))}
                        </div>
                      ) : null}
                      {revealedOralQuestionId === question.question_id && question.remediation_task ? (
                        <p className="question-remediation"><strong>课后补救：</strong>{question.remediation_task}</p>
                      ) : null}
                      {currentStage?.assistant_prompts.length ? (
                        <div className="class-oral-prompt-leads">
                          {currentStage.assistant_prompts.map((prompt, index) =>
                            onAssistantPrompt ? (
                              <button
                                key={index}
                                type="button"
                                className="class-oral-prompt-lead-button"
                                disabled={busy}
                                onClick={() => onAssistantPrompt(prompt)}
                                data-testid={`oral-assistant-prompt-${index}`}
                                title="一键把这条追问交给教学智能体展开"
                              >
                                <span className="assistant-prompt-icon">✦</span>
                                {prompt}
                              </button>
                            ) : (
                              <p key={index} className="class-oral-prompt-lead">
                                {prompt}
                              </p>
                            )
                          )}
                        </div>
                      ) : null}
                      <p className="class-oral-prompt-note">学情速记已就绪，下方可记录学生表现。</p>
                    </div>
                  ) : null}

                  {expanded ? (
                    <div className="class-question-detail">
                      {question.options.length ? (
                        <ul className="question-options">
                          {question.options.map((option, index) => (
                            <li key={index} className={question.answer_index === index ? "answer" : ""}>
                              <span className="option-label">{OPTION_LABELS[index] || index + 1}</span>
                              <span>{option}</span>
                              {question.answer_index === index ? <em>✓ 正确</em> : null}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {question.expected_points.length ? (
                        <div className="question-points">
                          <span className="question-detail-label">要点</span>
                          {question.expected_points.map((point) => (
                            <span key={point} className="point-chip">
                              {point}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      {question.misconceptions.length ? (
                        <div className="question-misconceptions">
                          <span className="question-detail-label">易错</span>
                          {question.misconceptions.map((item) => (
                            <button
                              key={item.tag}
                              type="button"
                              className="tag-chip"
                              title={`${item.description || item.tag}（点击记一次误区）`}
                              onClick={() => recordQuestionMisconception(question, item.tag)}
                            >
                              {item.tag}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="class-question-actions">
                    <button
                      type="button"
                      className={`toolbar-button compact primary ${oralQuestionId === question.question_id ? "active" : ""}`}
                      disabled={busy}
                      onClick={() => presentQuestion(question)}
                      data-testid={`oral-toggle-${question.question_id}`}
                      title="教师口头呈现问题；答案与论证链默认隐藏，学情速记自动就绪"
                    >
                      {oralQuestionId === question.question_id ? "结束提问" : "口头提问"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : null}

        <div className="class-panel-adhoc" data-testid="adhoc-question">
          <span className="question-detail-label">临时口头提问</span>
          <input
            value={adhocText}
            placeholder="输入课堂即兴问题…"
            onChange={(event) => setAdhocText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                launchAdhoc();
              }
            }}
          />
          <div className="class-panel-adhoc-row">
            <input
              value={adhocOptions}
              placeholder="选项用 / 分隔（留空为开放题）"
              onChange={(event) => setAdhocOptions(event.target.value)}
            />
            <button
              type="button"
              className="toolbar-button compact primary"
              disabled={busy || quizActive || !adhocText.trim()}
              onClick={launchAdhoc}
              data-testid="launch-adhoc"
            >
              记录提问
            </button>
          </div>
        </div>
      </div>

      <footer className="class-panel-footer">
        <div className="quick-record" data-testid="quick-record">
          <span className="quick-record-label">学情速记：</span>
          <button type="button" className="record-button correct" onClick={() => submitObservation("correct")}>
            答对
          </button>
          <button type="button" className="record-button partial" onClick={() => submitObservation("partial")}>
            部分
          </button>
          <button
            type="button"
            className={`record-button misconception ${recordVerdict === "misconception" ? "active" : ""}`}
            onClick={() => submitObservation("misconception")}
          >
            误区
          </button>
        </div>

        {recordVerdict === "misconception" ? (
          <div className="misconception-picker" data-testid="misconception-picker">
            <div className="misconception-tags">
              {misconceptionTags.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  className={`tag-chip ${recordTag === tag ? "active" : ""}`}
                  onClick={() => setRecordTag(tag)}
                >
                  {tag}
                </button>
              ))}
              <input
                value={recordTag}
                placeholder="自定义误区标签"
                onChange={(event) => setRecordTag(event.target.value)}
              />
            </div>
            <div className="misconception-note">
              <input
                value={recordNote}
                placeholder="一句话描述学生的表现（可留空）"
                onChange={(event) => setRecordNote(event.target.value)}
              />
              <button type="button" className="toolbar-button compact primary" onClick={confirmMisconception}>
                记录误区
              </button>
              <button type="button" className="toolbar-button compact" onClick={resetRecord}>
                取消
              </button>
            </div>
          </div>
        ) : null}

        <div className="class-panel-footer-actions">
          <button type="button" className="toolbar-button compact" onClick={onSnapshot} disabled={busy}>
            截图存证
          </button>
          <button type="button" className="toolbar-button compact danger" onClick={onEndSession}>
            结束上课
          </button>
        </div>
      </footer>
    </section>
  );
}
