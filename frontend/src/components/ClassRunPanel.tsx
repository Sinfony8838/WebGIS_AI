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
};

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

const OPTION_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H"];

export function ClassRunPanel({
  lesson,
  session,
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
  onEndSession
}: Props) {
  const [nowTick, setNowTick] = useState(Date.now());
  const [recordVerdict, setRecordVerdict] = useState<ObservationVerdict | null>(null);
  const [recordTag, setRecordTag] = useState("");
  const [recordNote, setRecordNote] = useState("");
  const [recordQuestionId, setRecordQuestionId] = useState("");
  const [savedFlash, setSavedFlash] = useState(false);
  const [expandedQuestionId, setExpandedQuestionId] = useState("");
  const [scriptOpen, setScriptOpen] = useState(true);
  const [adhocText, setAdhocText] = useState("");
  const [adhocOptions, setAdhocOptions] = useState("");

  useEffect(() => {
    const interval = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  // 切换环节后回到默认展示状态
  useEffect(() => {
    setExpandedQuestionId("");
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
              课堂码 {session.join_code}
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

        {currentStage?.questions.length ? (
          <div className="class-panel-questions">
            {currentStage.questions.map((question) => {
              const expanded = expandedQuestionId === question.question_id;
              const evidenceQuestion = question as typeof question & {
                question_evidence_rules?: { required?: boolean; evidence_options?: Array<{ label: string }> };
                argument_chain?: string[];
              };
              return (
                <article key={question.question_id} className={`class-question-card ${expanded ? "expanded" : ""}`}>
                  <button
                    type="button"
                    className="class-question-head"
                    onClick={() => setExpandedQuestionId(expanded ? "" : question.question_id)}
                    data-testid={`question-toggle-${question.question_id}`}
                  >
                    <span className={`question-type-badge ${question.type}`}>
                      {question.type === "choice" ? "投票" : "问答"}
                    </span>
                    <span className="class-question-text">{question.text}</span>
                  </button>

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
                      {evidenceQuestion.question_evidence_rules?.required ? (
                        <div className="question-points">
                          <span className="question-detail-label">学生取证</span>
                          {evidenceQuestion.question_evidence_rules.evidence_options?.map((item) => (
                            <span key={item.label} className="point-chip">{item.label}</span>
                          ))}
                          {evidenceQuestion.argument_chain?.length ? (
                            <span className="point-chip">论证：{evidenceQuestion.argument_chain.join(" → ")}</span>
                          ) : null}
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
                    {question.type === "choice" ? (
                      <button
                        type="button"
                        className="toolbar-button compact primary"
                        disabled={busy || quizActive}
                        onClick={() => onLaunchQuestion(question.question_id, currentStage.stage_id)}
                        data-testid={`launch-${question.question_id}`}
                      >
                        发起投票
                      </button>
                    ) : (
                      <button
                        type="button"
                        className={`toolbar-button compact ${recordQuestionId === question.question_id ? "active" : ""}`}
                        onClick={() => setRecordQuestionId(question.question_id)}
                        title="口头提问后，用下方学情速记记录学生表现"
                      >
                        口头提问
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        ) : null}

        <div className="class-panel-adhoc" data-testid="adhoc-question">
          <span className="question-detail-label">临时提问</span>
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
              发起
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
