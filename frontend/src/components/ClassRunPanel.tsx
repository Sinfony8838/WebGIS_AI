import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
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
  /** 全屏投屏本题：服务端计时 + 课堂大屏同步（题目投影模式）。 */
  onProjectQuestion?: (questionId: string, stageId: string) => void;
  onLaunchAdhocQuestion: (text: string, options: string[]) => void;
  onObservation: (verdict: ObservationVerdict, tag: string, note: string, questionId: string) => void;
  onSnapshot: () => void;
  onEndSession: () => void;
  visibleCatalogLayerIds?: string[];
  onFocusEvidenceLayer?: (datasetId: string, stageDatasetIds: string[]) => void;
  onRequestPlaneView?: () => void;
  /** 以隐藏的内部提示驱动 GeoBot，课堂对话只显示简短的头脑风暴标题。 */
  onAssistantPrompt?: (prompt: string, displayMessage?: string) => void;
};

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

const OPTION_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H"];
const EVIDENCE_LAYER_LABELS: Record<string, string> = {
  china_climate_types: "气候",
  china_terrain_steps: "地形",
  china_major_rivers: "河流",
  china_vegetation_zones: "植被",
  china_province_gdp_per_capita: "经济"
};

type KnowledgePosition = { x: number; y: number };

function defaultKnowledgePosition(): KnowledgePosition {
  if (typeof window === "undefined") {
    return { x: 28, y: 92 };
  }
  return { x: Math.max(20, Math.min(72, window.innerWidth * 0.035)), y: Math.max(72, window.innerHeight * 0.1) };
}

function BasicKnowledgeOverlay({
  title,
  points,
  position,
  onPositionChange,
  onClose
}: {
  title: string;
  points: string[];
  position: KnowledgePosition;
  onPositionChange: (next: KnowledgePosition) => void;
  onClose: () => void;
}) {
  const overlayRef = useRef<HTMLElement | null>(null);
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; origin: KnowledgePosition } | null>(null);

  function clampPosition(next: KnowledgePosition): KnowledgePosition {
    const rect = overlayRef.current?.getBoundingClientRect();
    const width = rect?.width || Math.min(880, Math.max(420, window.innerWidth * 0.56));
    const height = rect?.height || Math.min(680, window.innerHeight * 0.7);
    return {
      x: Math.max(12, Math.min(Math.max(12, window.innerWidth - width - 12), next.x)),
      y: Math.max(12, Math.min(Math.max(12, window.innerHeight - height - 12), next.y))
    };
  }

  useEffect(() => {
    const keepInViewport = () => {
      const clamped = clampPosition(position);
      if (clamped.x !== position.x || clamped.y !== position.y) {
        onPositionChange(clamped);
      }
    };
    keepInViewport();
    window.addEventListener("resize", keepInViewport);
    return () => window.removeEventListener("resize", keepInViewport);
  }, [position.x, position.y]);

  function startDrag(event: ReactPointerEvent<HTMLElement>) {
    const clientX = Number.isFinite(event.clientX) ? event.clientX : 0;
    const clientY = Number.isFinite(event.clientY) ? event.clientY : 0;
    dragRef.current = {
      pointerId: event.pointerId,
      startX: clientX,
      startY: clientY,
      origin: position
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function moveDrag(event: ReactPointerEvent<HTMLElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    const clientX = Number.isFinite(event.clientX) ? event.clientX : drag.startX;
    const clientY = Number.isFinite(event.clientY) ? event.clientY : drag.startY;
    onPositionChange(clampPosition({
      x: drag.origin.x + clientX - drag.startX,
      y: drag.origin.y + clientY - drag.startY
    }));
  }

  function endDrag(event: ReactPointerEvent<HTMLElement>) {
    if (dragRef.current?.pointerId === event.pointerId) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      dragRef.current = null;
    }
  }

  return createPortal(
    <section
      ref={overlayRef}
      className="basic-knowledge-overlay glass-panel"
      style={{ left: position.x, top: position.y }}
      role="dialog"
      aria-label={`${title}基础知识讲解`}
      data-testid="basic-knowledge-overlay"
    >
      <header
        className="basic-knowledge-overlay-header"
        onPointerDown={startDrag}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div>
          <span>基础知识讲解</span>
          <strong>{title}</strong>
        </div>
        <span className="basic-knowledge-drag-hint">拖动调整位置</span>
        <button type="button" className="mini-control" onPointerDown={(event) => event.stopPropagation()} onClick={onClose} aria-label="关闭基础知识讲解">
          ×
        </button>
      </header>
      <ol className="basic-knowledge-points">
        {points.map((point, index) => <li key={`${index}_${point}`}>{point}</li>)}
      </ol>
    </section>,
    document.body
  );
}

export function ClassRunPanel({
  session,
  lesson,
  currentStageId,
  stageEnteredAt,
  busy,
  quizActive,
  collapsed,
  onToggleCollapsed,
  onEnterStage,
  onLaunchQuestion,
  onProjectQuestion,
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
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [knowledgePosition, setKnowledgePosition] = useState<KnowledgePosition>(defaultKnowledgePosition);
  const [brainstormRegion, setBrainstormRegion] = useState("");
  const [brainstormSpinning, setBrainstormSpinning] = useState(false);
  const brainstormTimerRef = useRef<number | null>(null);
  const [adhocText, setAdhocText] = useState("");
  const [adhocOptions, setAdhocOptions] = useState("");

  useEffect(() => {
    const interval = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  // 切换环节后回到默认展示状态
  useEffect(() => {
    return () => {
      if (brainstormTimerRef.current !== null) {
        window.clearInterval(brainstormTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    setExpandedQuestionId("");
    setOralQuestionId("");
    setKnowledgeOpen(false);
    setKnowledgePosition(defaultKnowledgePosition());
    setBrainstormRegion("");
    setBrainstormSpinning(false);
    if (brainstormTimerRef.current !== null) {
      window.clearInterval(brainstormTimerRef.current);
      brainstormTimerRef.current = null;
    }
    resetRecord();
  }, [currentStageId, session.session_id]);

  const currentStage: LessonStage | undefined = useMemo(
    () => lesson.stages.find((stage) => stage.stage_id === currentStageId),
    [lesson, currentStageId]
  );
  const currentStageIndex = lesson.stages.findIndex((stage) => stage.stage_id === currentStageId);
  const brainstorm = currentStage?.brainstorm;
  const brainstormRegions = Array.isArray(brainstorm?.regions)
    ? [...new Set(brainstorm.regions.filter((region) => typeof region === "string" && region.trim()).map((region) => region.trim()))]
    : [];
  const hasBrainstorm = Boolean(brainstorm?.prompt?.trim() && brainstormRegions.length);


  const elapsedSeconds = stageEnteredAt ? Math.max(0, (nowTick - stageEnteredAt) / 1000) : 0;
  const plannedSeconds = (currentStage?.minutes || 0) * 60;
  const overtime = plannedSeconds > 0 && elapsedSeconds > plannedSeconds;
  const stageProgress = plannedSeconds > 0 ? Math.min(1, elapsedSeconds / plannedSeconds) : 0;

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
      setRecordQuestionId("");
      return;
    }
    // 展开朗读提问卡，同时为学情速记预置该题，便于记录学生表现。
    setOralQuestionId(questionId);
    setRecordQuestionId(questionId);
  }

  function runBrainstorm() {
    if (!currentStage || !brainstorm || !hasBrainstorm || !onAssistantPrompt || brainstormSpinning || busy) {
      return;
    }
    setBrainstormSpinning(true);
    let tick = 0;
    brainstormTimerRef.current = window.setInterval(() => {
      const preview = brainstormRegions[tick % brainstormRegions.length];
      setBrainstormRegion(preview);
      tick += 1;
      if (tick < 15) {
        return;
      }
      if (brainstormTimerRef.current !== null) {
        window.clearInterval(brainstormTimerRef.current);
        brainstormTimerRef.current = null;
      }
      const selected = brainstormRegions[Math.floor(Math.random() * brainstormRegions.length)] || preview;
      setBrainstormRegion(selected);
      setBrainstormSpinning(false);
      const prompt = [
        `GeoBot 头脑风暴：围绕“${currentStage.title}”开展随机地区探究。`,
        `随机抽中的地区是：${selected}。`,
        `本课：${lesson.title}；当前环节：${currentStage.title}。`,
        `本环节候选地区：${brainstormRegions.join("、")}。只围绕抽中的地区，保持本环节的比较尺度。`,
        `本环节讲解材料：${currentStage.script.join("；")}。`,
        "以下是教案原题的参考材料，不是学生回答，也不能当作本次课堂观察：",
        ...currentStage.questions.slice(0, 3).map((question) => [question.text, question.material, question.answer, question.explanation].filter(Boolean).join("\n")),
        brainstorm.prompt,
        "请生成一个与当前问题链衔接的追问，并提供教师参考回答；不替学生作答，不推断学生掌握情况。",
        "问题必须体现区域差异、条件变化、尺度转换或反直觉比较中的至少一种；资料不足时明确说明限制，不得编造数据。",
        "只输出“头脑风暴问题”“回答”“回答总结”三部分；回答总结必须是一句话。",
        "不要输出地图中心坐标、缩放级别、可见范围、证据或观察点、给学生的问题、教师收束语。"
      ].join("\n");
      onAssistantPrompt(prompt, `GeoBot 头脑风暴 · ${selected}`);
    }, 70);
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
          const done = !active && session.events.some(event => event.type === "stage_enter" && event.stage_id === stage.stage_id);
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
        {currentStage?.script?.length ? (
          <div className="basic-knowledge-launcher" data-testid="basic-knowledge-launcher">
            <div>
              <span className="question-detail-label">基础知识讲解</span>
              <strong>课本知识 × 当前真实地图</strong>
              <small>点击后放大投屏，可拖动且不会锁住地图。</small>
            </div>
            <button type="button" className="toolbar-button compact primary" onClick={() => setKnowledgeOpen(true)}>
              放大展示
            </button>
          </div>
        ) : null}

        {currentStage?.scene?.globe?.enabled && onRequestPlaneView ? (
          <div className="class-stage-view-handoff" data-testid="stage-view-handoff">
            <span>3D 用于宏观导入；开始读图和答题时回到二维规范专题图。</span>
            <button type="button" className="toolbar-button compact" onClick={onRequestPlaneView}>
              切回二维判读
            </button>
          </div>
        ) : null}

        {currentStage?.scene?.catalog_layers && currentStage.scene.catalog_layers.filter(id => EVIDENCE_LAYER_LABELS[id]).length > 1 && onFocusEvidenceLayer ? (
          <div className="class-evidence-layer-steps" data-testid="evidence-layer-steps">
            <div className="class-evidence-layer-heading">
              <span className="question-detail-label">切换地图</span>

            </div>
            <div className="class-evidence-layer-buttons">
              {currentStage.scene.catalog_layers.filter(id => EVIDENCE_LAYER_LABELS[id]).map((datasetId) => (
                <button
                  key={datasetId}
                  type="button"
                  className={`evidence-layer-step ${visibleCatalogLayerIds.includes(datasetId) ? "active" : ""}`}
                  disabled={busy}
                  onClick={() => onFocusEvidenceLayer(datasetId, currentStage.scene?.catalog_layers || [])}
                  data-testid={`evidence-layer-${datasetId}`}
                >
                  {EVIDENCE_LAYER_LABELS[datasetId] || datasetId}
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
                      <p className="class-oral-prompt-note">学情速记已就绪，下方可记录学生表现。</p>
                    </div>
                  ) : null}

                  {expanded ? (
                    <div className="class-question-detail">
                      {question.options.length ? (
                        <ul className="question-options">
                          {question.options.map((option, index) => (
                            <li key={index}>
                              <span className="option-label">{OPTION_LABELS[index] || index + 1}</span>
                              <span>{option}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="class-question-actions">
                    {onProjectQuestion ? (
                      <button
                        type="button"
                        className="toolbar-button compact"
                        disabled={busy}
                        onClick={() => onProjectQuestion(question.question_id, currentStage?.stage_id || "")}
                        data-testid={`project-toggle-${question.question_id}`}
                        title="全屏投屏本题：服务端计时，课堂大屏同步，可暂停/重置/提前揭示"
                      >
                        投屏答题
                      </button>
                    ) : null}
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

        {hasBrainstorm && brainstorm && onAssistantPrompt ? (
          <div className="class-brainstorm-card" data-testid="stage-brainstorm">
            <div className="class-brainstorm-identity">
              <span className="class-brainstorm-mark" aria-hidden="true">✦</span>
              <div>
                <span>GeoBot AI</span>
                <strong>{brainstorm.title || "头脑风暴"}</strong>
              </div>
            </div>
            <p>从本环节的地区中抽取一个，生成追问与教师参考回答。</p>
            <div className={`brainstorm-region-wheel ${brainstormSpinning ? "spinning" : ""}`} aria-live="polite">
              <span>{brainstormRegion || "等待抽取地区"}</span>
            </div>
            <button
              type="button"
              className="toolbar-button compact primary class-brainstorm-run"
              disabled={busy || brainstormSpinning}
              onClick={runBrainstorm}
              data-testid="run-brainstorm"
            >
              {brainstormSpinning ? "GeoBot 正在转动…" : brainstorm.button_label || "转动并生成探究"}
            </button>
          </div>
        ) : null}
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
              <input
                value={recordTag}
                placeholder="教师现场输入误区标签"
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
      {knowledgeOpen && currentStage?.script?.length ? (
        <BasicKnowledgeOverlay
          title={currentStage.title}
          points={currentStage.script}
          position={knowledgePosition}
          onPositionChange={setKnowledgePosition}
          onClose={() => setKnowledgeOpen(false)}
        />
      ) : null}
    </section>
  );
}
