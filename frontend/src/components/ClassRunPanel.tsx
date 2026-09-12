import { useEffect, useMemo, useRef, useState } from "react";
import type { ClassroomPresentationTarget } from "../api";
import { ShanghaiPopulationInquiry } from "./ShanghaiPopulationInquiry";
import type { ClassSessionRecord, LessonQuestion, LessonRecord, LessonStage, ObservationVerdict } from "../types";

type Props = {
  lesson: LessonRecord;
  session: ClassSessionRecord;
  currentStageId: string;
  stageEnteredAt: number | null;
  busy: boolean;
  assistantBusy?: boolean;
  quizActive: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onEnterStage: (stageId: string) => void;
  onPresentScene?: (target: ClassroomPresentationTarget) => Promise<void>;
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
  /** 以隐藏的内部提示驱动 GeoBot，课堂对话显示完整的探究问题。 */
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

export function ClassRunPanel({
  session,
  lesson,
  currentStageId,
  stageEnteredAt,
  busy,
  assistantBusy = false,
  quizActive,
  collapsed,
  onToggleCollapsed,
  onEnterStage,
  onPresentScene,
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
  const [inquiryOpen, setInquiryOpen] = useState(false);
  const [presentationBusy, setPresentationBusy] = useState(false);
  const [presentationError, setPresentationError] = useState("");
  const presentationEpoch = useRef(0);
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
    setInquiryOpen(false);
    setPresentationError("");
    setPresentationBusy(false);
    presentationEpoch.current += 1;
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
  const shanghaiSupplement = currentStageId === "shanghai_intro" && lesson.title.includes("上海") && lesson.title.includes("人口");
  const shanghaiVerification = currentStageId === "shanghai_verify" && lesson.title.includes("上海") && lesson.title.includes("人口");
  async function openMapPresentation(target: ClassroomPresentationTarget = "stage") {
    if (!onPresentScene || presentationBusy) return;
    const epoch = presentationEpoch.current;
    setPresentationBusy(true); setPresentationError("");
    try {
      await onPresentScene(target);

    } catch (error) {
      if (epoch === presentationEpoch.current) setPresentationError(error instanceof Error ? error.message : "地图展示失败，请重试");
    } finally { if (epoch === presentationEpoch.current) setPresentationBusy(false); }
  }

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
    if (!currentStage || !brainstorm || !hasBrainstorm || !onAssistantPrompt || brainstormSpinning || busy || assistantBusy) {
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
      const regionalQuestions:Record<string,string> = {
        "青藏高原河谷":"青藏高原总体人口较少，为什么一些河谷仍有人口集聚？请从热量、地形和交通中选择两项说明。",
        "塔里木盆地":"塔里木盆地很干旱，为什么人口和城镇多分布在盆地边缘的绿洲？请从水源、地形和生产方式中选择两项说明。",
        "河西走廊":"河西走廊较干旱，为什么仍能形成绿洲城市？请从水源、地形和交通中选择两项说明。"
      };
      const inquiryQuestion = regionalQuestions[selected] || `以${selected}为例，${brainstorm.prompt}`;
      const prompt = [
        `GeoBot 头脑风暴：围绕“${currentStage.title}”补充一个小组讨论案例。`,
        `随机抽中的地区是：${selected}。`,
        "【本次探究任务】",
        inquiryQuestion,
        brainstorm.prompt,
        "请围绕抽中的地区解释，不转去泛泛介绍胡焕庸线。",
        "提供教师参考追问和参考回答；先保留学生思考空间，不替学生作答，不推断学生掌握情况。",
        "【课堂参考材料】",
        `本课：${lesson.title}；当前环节：${currentStage.title}。`,
        `本环节候选地区：${brainstormRegions.join("、")}。只围绕抽中的地区，保持本环节的比较尺度。`,
        `本环节讲解材料：${currentStage.script.join("；")}。`,
        "以下是教案原题的参考材料，不是学生回答，也不能当作本次课堂观察：",
        ...currentStage.questions.slice(0, 3).map((question) => [question.text, question.material, question.answer, question.explanation].filter(Boolean).join("\n")),
        "【回答格式】",
        "问题要聚焦一个清楚的地区差异；信息不足时直接说明，不得编造数据。",
        "只输出“头脑风暴问题”“回答”“回答总结”三部分；回答总结必须是一句话。",
        "不要输出地图中心坐标、缩放级别、可见范围、证据或观察点、给学生的问题、教师收束语。"
      ].join("\n");
      onAssistantPrompt(prompt, inquiryQuestion);
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
        {currentStage?.scene ? (
          <div className="basic-knowledge-launcher" data-testid="class-map-launcher">
            <div>
              <span className="question-detail-label">课堂地图</span>
              <strong>先看图，再说发现</strong>
              <small>进入环节会自动准备对应地图。先让学生描述看到的现象，再一起解释。</small>
            </div>
            <div className="class-presentation-actions">
              <button type="button" className="toolbar-button compact primary" disabled={busy || presentationBusy || !onPresentScene} onClick={() => void openMapPresentation()}>
                {presentationBusy ? "正在定位…" : "地图展示"}
              </button>
            </div>
          </div>
        ) : null}

        {shanghaiVerification && <div className="class-local-comparison" role="group" aria-label="上海局部影像对照">
          <span className="question-detail-label">同级缩放 · 局部影像对照</span>
          <div>
            <button className="toolbar-button compact" disabled={busy || presentationBusy || !onPresentScene} onClick={() => void openMapPresentation("huangpu_detail")}>黄浦局部</button>
            <button className="toolbar-button compact" disabled={busy || presentationBusy || !onPresentScene} onClick={() => void openMapPresentation("chongming_detail")}>崇明局部</button>
            <button className="toolbar-button compact" disabled={busy || presentationBusy || !onPresentScene} onClick={() => void openMapPresentation()}>返回全市</button>
          </div>
          <small>参考点周边的景观样例，不代表全区；影像年份以提供方资料为准。</small>
        </div>}
        {presentationError && <p role="alert">{presentationError}</p>}
        {shanghaiSupplement && onPresentScene && <div className="shanghai-supplement-launcher">
          <div><strong>基础讲完后 · 真题拓展</strong><small>2025 河南卷：人口分布与“年轻环”</small></div>
          <button className="toolbar-button compact" disabled={busy || presentationBusy} onClick={() => setInquiryOpen(true)}>进入补充探究</button>
        </div>}

        {currentStage?.scene?.globe?.enabled && onRequestPlaneView ? (
          <div className="class-stage-view-handoff" data-testid="stage-view-handoff">
            <span>三维地球适合整体观察；需要读图和答题时，请回到清晰的二维专题图。</span>
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
              const groupDiscussion = question.text.startsWith("【小组讨论");
              const displayText = groupDiscussion ? question.text.replace(/^【小组讨论[一二]】\s*/, "") : question.text;
              return (
                <article key={question.question_id} className={`class-question-card ${expanded ? "expanded" : ""}`}>
                  <button
                    type="button"
                    className="class-question-head"
                    onClick={() => setExpandedQuestionId(expanded ? "" : question.question_id)}
                    data-testid={`question-toggle-${question.question_id}`}
                  >
                    <span className={`question-type-badge ${groupDiscussion ? "discussion" : question.type}`}>
                      {groupDiscussion ? "小组讨论" : question.type === "choice" ? "选择" : "问答"}
                    </span>
                    <span className="class-question-text">{displayText}</span>
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
            placeholder="写下想追问学生的话…"
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
              记录并提问
            </button>
          </div>
        </div>

        {hasBrainstorm && brainstorm && onAssistantPrompt ? (
          <div className="class-brainstorm-card" data-testid="stage-brainstorm">
            <div className="class-brainstorm-identity">
              <span className="class-brainstorm-mark" aria-hidden="true">✦</span>
              <div>
                <span>GeoBot · 讨论助手</span>
                <strong>{brainstorm.title || "小组讨论"}</strong>
              </div>
            </div>
            <p>先让小组充分讨论，再抽取一个案例，由 GeoBot 提供教师追问和参考。</p>
            <div className={`brainstorm-region-wheel ${brainstormSpinning ? "spinning" : ""}`} aria-live="polite">
              <span>{brainstormRegion || "等待抽取案例"}</span>
            </div>
            <button
              type="button"
              className="toolbar-button compact primary class-brainstorm-run"
              disabled={busy || assistantBusy || brainstormSpinning}
              onClick={runBrainstorm}
              data-testid="run-brainstorm"
            >
              {brainstormSpinning ? "GeoBot 正在抽取…" : brainstorm.button_label || "抽取案例并生成追问"}
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
      {inquiryOpen && shanghaiSupplement && onPresentScene && <ShanghaiPopulationInquiry
        key={session.session_id + currentStageId} projectId={session.project_id}
        onPresent={onPresentScene} assistantBusy={assistantBusy} onAssistantPrompt={onAssistantPrompt} onClose={() => setInquiryOpen(false)} />}

    </section>
  );
}
