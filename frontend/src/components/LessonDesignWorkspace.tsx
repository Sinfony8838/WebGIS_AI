import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  bindLessonDesignQuestion,
  createLessonDesign,
  exportLessonDocx,
  fetchJob,
  fetchLesson,
  fetchLessonDesign,
  fetchQuestionBanks,
  finalizeLessonDesign,
  importQuestionBanks,
  resolveLessonDesignSection,
  searchQuestionBanks,
  turnLessonDesign
} from "../api";
import type {
  DesignPlanItem,
  LessonDesignSession,
  LessonQuestion,
  LessonRecord,
  LessonStage,
  QuestionBankQuestion,
  QuestionBankSummary,
  QuestionRetrievalCandidate
} from "../types";

type Props = {
  projectId: string;
  initialDesignId?: string;
  onClose: () => void;
  onFinalized?: (lesson: LessonRecord) => void;
  /** 定稿后直接进入该课时的模拟测试（试讲 → 发布为可上课版本）。 */
  onEnterRehearsal?: (lesson: LessonRecord) => void;
};

// 九步固定流程（与后端 STEP_KEYS / STEP_LABELS 一致）
const STEPS: Array<[string, string]> = [
  ["requirements", "需求确认"],
  ["analysis", "课标与学情"],
  ["objectives", "目标与重难点"],
  ["core_questions", "核心问题与问题链"],
  ["process", "教学过程"],
  ["question_matching", "题目匹配"],
  ["capabilities", "GIS/AI能力"],
  ["rehearsal", "预演检查"],
  ["confirmation", "确认发布"]
];
const STEP_SECTION_KEYS: Record<string, string[]> = {
  requirements: ["requirements"],
  analysis: ["curriculum_interpretation", "student_analysis", "textbook_analysis"],
  objectives: ["objectives", "key_difficulties", "methods", "knowledge_structure"],
  core_questions: ["core_questions"],
  process: ["stages", "board_design"],
  question_matching: ["question_citations", "homework"],
  capabilities: ["capabilities"],
  rehearsal: [],
  confirmation: ["design_thinking", "reflection"]
};
const SECTION_LABELS: Record<string, string> = {
  requirements: "教学需求", curriculum_interpretation: "课标解读", student_analysis: "学情分析",
  textbook_analysis: "教材分析", objectives: "教学目标", key_difficulties: "教学重难点",
  methods: "教学方法", knowledge_structure: "知识结构", core_questions: "核心问题与问题链",
  stages: "教学过程", board_design: "板书设计", question_citations: "题库引用",
  homework: "课后作业", capabilities: "GIS/AI能力", design_thinking: "设计思路", reflection: "教学反思"
};

const splitItems = (value: string) => value.split(/\r?\n|[；;]/).map((item) => item.trim()).filter(Boolean);
const asText = (value: unknown): string => (typeof value === "string" ? value : "");

function formatQuestion(q: LessonQuestion): string {
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

export function LessonDesignWorkspace({ projectId, initialDesignId = "", onClose, onFinalized, onEnterRehearsal }: Props) {
  const [design, setDesign] = useState<LessonDesignSession | null>(null);
  const [planItems, setPlanItems] = useState<DesignPlanItem[]>([]);
  const [activeQuestion, setActiveQuestion] = useState("");
  const [candidates, setCandidates] = useState<QuestionRetrievalCandidate[]>([]);
  const [messages, setMessages] = useState<Array<{ role: "assistant" | "teacher"; text: string }>>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [focusStep, setFocusStep] = useState("");
  const [banks, setBanks] = useState<QuestionBankSummary[]>([]);
  const [importBusy, setImportBusy] = useState(false);
  const [importNote, setImportNote] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [manualForm, setManualForm] = useState({ text: "", answer: "", explanation: "" });
  const [searchText, setSearchText] = useState("");
  const [searchResults, setSearchResults] = useState<QuestionBankQuestion[]>([]);
  const [finalResult, setFinalResult] = useState<{ lesson: LessonRecord; export?: { status: string; artifact?: { metadata?: { public_url?: string } } } } | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const applySession = useCallback((payload: LessonDesignSession & Partial<{ plan_items: DesignPlanItem[]; active_design_question: string }>) => {
    setDesign(payload);
    if (payload.plan_items) setPlanItems(payload.plan_items);
    if (payload.active_design_question !== undefined) setActiveQuestion(payload.active_design_question);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError("");
    const load = initialDesignId
      ? fetchLessonDesign(initialDesignId)
      : createLessonDesign(projectId, "", { trigger: "workspace" });
    load
      .then((payload) => {
        if (cancelled) return;
        applySession(payload);
        const history = (payload.turns || []).flatMap((turn) => [
          { role: "teacher" as const, text: turn.message },
          { role: "assistant" as const, text: turn.reply }
        ]);
        setMessages(
          history.length
            ? history
            : [{ role: "assistant", text: "我们开始教案设计。先告诉我年级、课题与课时，我会按九步流程逐步推进，每轮只问一个关键问题。" }]
        );
        // 已定稿的会话：回读课时，恢复「下载 Word / 进入模拟测试」入口。
        if (payload.status === "finalized" && payload.final_lesson_id) {
          fetchLesson(payload.final_lesson_id)
            .then((lesson) => {
              if (!cancelled) setFinalResult({ lesson });
            })
            .catch(() => undefined);
        }
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setBusy(false));
    fetchQuestionBanks(projectId)
      .then((result) => {
        if (!cancelled) setBanks(result.items || []);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [applySession, initialDesignId, projectId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const draft = design?.draft || {};
  const currentStep = design?.current_step || "requirements";
  const viewStep = focusStep || currentStep;
  const currentLabel = STEPS.find(([key]) => key === viewStep)?.[1] || "需求确认";
  const stepIndex = STEPS.findIndex(([key]) => key === currentStep);
  const confirmedCount = useMemo(
    () => Object.values(design?.section_status || {}).filter((status) => status === "confirmed").length,
    [design?.section_status]
  );

  function stepState(key: string): "done" | "active" | "todo" {
    const sections = STEP_SECTION_KEYS[key] || [];
    if (!sections.length) return key === currentStep ? "active" : "todo";
    const statuses = sections.map((section) => design?.section_status?.[section] || "pending");
    if (statuses.every((status) => status === "confirmed")) return "done";
    if (key === currentStep || statuses.some((status) => status === "proposed")) return "active";
    return "todo";
  }

  async function runTurn(text: string, step = "") {
    if (!design || !text.trim() || busy) return;
    setMessages((previous) => [...previous, { role: "teacher", text }]);
    setBusy(true);
    setError("");
    try {
      const result = await turnLessonDesign(design.design_id, text, design.revision, step || viewStep);
      applySession({
        ...design,
        draft: result.draft,
        section_status: result.section_status,
        source_refs: result.source_refs,
        capability_bindings: result.capability_bindings,
        diff_summary: result.diff_summary || design.diff_summary,
        current_step: result.next_step,
        revision: result.revision
      });
      setPlanItems(result.plan_items || []);
      setActiveQuestion(result.active_design_question || "");
      setCandidates(result.retrieval_candidates || []);
      setMessages((previous) => [...previous, { role: "assistant", text: result.assistant_message }]);
      setInput("");
      if (result.rehearsal_report) {
        const report = result.rehearsal_report as { ready?: boolean };
        setMessages((previous) => [
          ...previous,
          { role: "assistant", text: `预演检查：${report.ready ? "结构已通过" : "仍有需要补充的内容"}。` }
        ]);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function acceptStep(step = viewStep) {
    if (!design) return;
    setBusy(true);
    setError("");
    try {
      const result = await resolveLessonDesignSection(design.design_id, step, "accept", "", design.revision);
      applySession(result.design);
      setPlanItems(result.design.plan_items || []);
      setActiveQuestion(result.design.active_design_question || "");
      setMessages((previous) => [...previous, { role: "assistant", text: "这一部分已确认，我们继续下一步。" }]);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function directEdit(sectionId: string, value: unknown) {
    if (!design) return;
    setBusy(true);
    setError("");
    try {
      const result = await resolveLessonDesignSection(design.design_id, sectionId, "edit", "", design.revision, value);
      applySession(result.design);
      setPlanItems(result.design.plan_items || []);
      setActiveQuestion(result.design.active_design_question || "");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function bindQuestion(stageId: string, questionId = "", manual?: Record<string, unknown>) {
    if (!design) return;
    setBusy(true);
    setError("");
    try {
      const result = await bindLessonDesignQuestion(design.design_id, {
        stage_id: stageId,
        question_id: questionId || undefined,
        manual: manual || undefined,
        expected_revision: design.revision
      });
      applySession(result.design);
      setCandidates([]);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function removeQuestion(stageId: string, questionId: string) {
    if (!design) return;
    setBusy(true);
    setError("");
    try {
      const result = await bindLessonDesignQuestion(design.design_id, {
        stage_id: stageId,
        question_id: questionId,
        action: "remove",
        expected_revision: design.revision
      });
      applySession(result.design);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function importBanks(files: FileList | null) {
    if (!files || !files.length) return;
    setImportBusy(true);
    setImportNote("正在上传并解析题库…");
    setError("");
    try {
      const start = await importQuestionBanks(projectId, Array.from(files));
      let job = await fetchJob(start.job_id);
      let guard = 0;
      while (job.status !== "completed" && job.status !== "failed" && guard < 240) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        job = await fetchJob(start.job_id);
        guard += 1;
        setImportNote(`正在解析题库…（${Object.values(job.stages || {}).find((stage) => stage.status === "running")?.summary || job.status}）`);
      }
      if (job.status === "failed") {
        setImportNote("");
        setError(job.error || "题库导入失败。");
        return;
      }
      const result = job.result as { banks?: QuestionBankSummary[]; summary?: string; assistant_message?: string } | undefined;
      const note = result?.summary || result?.assistant_message || "题库导入完成。";
      setImportNote(note);
      const list = await fetchQuestionBanks(projectId);
      setBanks(list.items || []);
      if (viewStep === "question_matching") {
        await runTurn("刷新题目匹配");
      }
    } catch (exc) {
      setImportNote("");
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setImportBusy(false);
    }
  }

  async function runSearch() {
    if (!searchText.trim()) return;
    setBusy(true);
    setError("");
    try {
      const result = await searchQuestionBanks({
        project_id: projectId,
        topic: draft.topic || draft.title || "",
        knowledge: searchText.trim(),
        objectives: draft.objectives || []
      });
      setSearchResults(result.items || []);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function finalize() {
    if (!design) return;
    setBusy(true);
    setError("");
    try {
      const result = await finalizeLessonDesign(design.design_id, design.revision);
      applySession(result.design);
      setPlanItems(result.design.plan_items || []);
      setFinalResult({ lesson: result.lesson, export: (result as { export?: { status: string; artifact?: { metadata?: { public_url?: string } } } }).export });
      setMessages((previous) => [...previous, { role: "assistant", text: "教案草稿已生成第一版 Word。进入「模拟测试」试讲一遍，通过后即可发布为正式课堂。" }]);
      onFinalized?.(result.lesson);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function exportWord() {
    if (!design?.final_lesson_id && !finalResult?.lesson) return;
    const lessonId = finalResult?.lesson.lesson_id || design?.final_lesson_id || "";
    setBusy(true);
    setError("");
    try {
      const result = await exportLessonDocx(lessonId, projectId, design?.design_id || "");
      const url = result.artifact.metadata?.public_url;
      if (typeof url === "string") window.open(url, "_blank", "noopener,noreferrer");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  // ------------------------------------------------------------------
  // 中栏：各章节编辑卡片
  // ------------------------------------------------------------------
  function renderSectionEditor(sectionId: string) {
    const status = design?.section_status?.[sectionId] || "pending";
    const label = SECTION_LABELS[sectionId] || sectionId;
    const card = (
      <div key={sectionId} className="ldw-card" data-testid={`ldw-section-${sectionId}`}>
        <div className="ldw-card-head">
          <strong>{label}</strong>
          <span className={`ldw-status ldw-status-${status}`}>{status === "confirmed" ? "已确认" : status === "proposed" ? "待确认" : "待补充"}</span>
        </div>
        <SectionBody
          sectionId={sectionId}
          design={design}
          busy={busy}
          onSave={(value) => void directEdit(sectionId, value)}
          onRemoveQuestion={(stageId, questionId) => void removeQuestion(stageId, questionId)}
          onBindCandidate={(stageId, questionId) => void bindQuestion(stageId, questionId)}
        />
      </div>
    );
    return card;
  }

  const viewSections = STEP_SECTION_KEYS[viewStep] || [];
  const stages = stageList(draft);

  return (
    <section className="ldw-backdrop" data-testid="lesson-design-workspace">
      <div className="ldw-shell">
        <aside className="ldw-left">
          <header className="ldw-header">
            <div>
              <p className="panel-tag">Lesson Design</p>
              <h2>教案设计</h2>
              <p className="ldw-sub">
                {draft.title || draft.topic || "未命名课时"} · {draft.grade || "年级待定"} · {draft.duration_minutes || 40}分钟
              </p>
            </div>
            <button type="button" className="mini-control" onClick={onClose} aria-label="关闭教案设计" data-testid="ldw-close">
              ×
            </button>
          </header>
          <nav className="ldw-steps" aria-label="教案设计九步流程" data-testid="ldw-steps">
            {STEPS.map(([key, label], index) => {
              const state = stepState(key);
              return (
                <button
                  key={key}
                  type="button"
                  className={`ldw-step ${state} ${key === viewStep ? "viewing" : ""}`}
                  onClick={() => setFocusStep(key === currentStep ? "" : key)}
                  data-testid={`ldw-step-${key}`}
                >
                  <span className="ldw-step-no">{index + 1}</span>
                  <em>{label}</em>
                  <i className={`ldw-step-dot ldw-dot-${state}`} />
                </button>
              );
            })}
          </nav>
          <div className="ldw-banks" data-testid="ldw-banks">
            <div className="ldw-card-head">
              <strong>题库</strong>
              <button
                type="button"
                className="toolbar-button compact"
                disabled={importBusy}
                onClick={() => fileInputRef.current?.click()}
                data-testid="ldw-import-bank"
              >
                导入题库
              </button>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".docx"
              multiple
              hidden
              onChange={(event) => {
                void importBanks(event.target.files);
                event.target.value = "";
              }}
            />
            {importNote ? <p className="ldw-import-note">{importNote}</p> : null}
            {banks.length ? (
              <ul className="ldw-bank-list">
                {banks.map((bank) => (
                  <li key={bank.bank_id}>
                    <strong>{bank.title}</strong>
                    <small>
                      {bank.question_count} 题 · 答案覆盖 {Math.round(bank.answer_coverage * 100)}%
                      {bank.answer_missing ? " · 答案缺失" : ""}
                      {bank.image_count ? ` · ${bank.image_count} 图` : ""}
                    </small>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="ldw-hint">尚未导入题库。支持 原卷版 + 解析版 成对上传（.docx，最多 4 个文件）。</p>
            )}
          </div>
        </aside>

        <main className="ldw-mid">
          <header className="ldw-mid-head">
            <h3>
              第 {stepIndex < 0 ? 1 : stepIndex + 1} 步 · {currentLabel}
              {focusStep && focusStep !== currentStep ? "（回看）" : ""}
            </h3>
            <span className="ldw-progress">已确认 {confirmedCount} 项</span>
            {focusStep && focusStep !== currentStep ? (
              <button type="button" className="toolbar-button compact" onClick={() => setFocusStep("")}>
                回到当前步骤
              </button>
            ) : null}
          </header>
          <div className="ldw-mid-scroll" data-testid="ldw-plan">
            {viewStep === "rehearsal" ? <RehearsalCard design={design} onRun={() => void runTurn("请运行完整预演检查", "rehearsal")} busy={busy} /> : null}
            {viewSections.map((sectionId) => renderSectionEditor(sectionId))}
            {viewStep === "question_matching" ? (
              <QuestionMatchingCard
                design={design}
                banks={banks}
                candidates={candidates}
                searchText={searchText}
                searchResults={searchResults}
                busy={busy}
                manualOpen={manualOpen}
                manualForm={manualForm}
                onSearchText={setSearchText}
                onRunSearch={() => void runSearch()}
                onToggleManual={() => setManualOpen((value) => !value)}
                onManualForm={(patch) => setManualForm((previous) => ({ ...previous, ...patch }))}
                onBindManual={(stageId) => {
                  const manual: Record<string, unknown> = { text: manualForm.text };
                  if (manualForm.answer.trim()) manual.answer = manualForm.answer.trim();
                  if (manualForm.explanation.trim()) manual.explanation = manualForm.explanation.trim();
                  void bindQuestion(stageId, "", manual).then(() => setManualForm({ text: "", answer: "", explanation: "" }));
                }}
                onBindSearchResult={(stageId, questionId) => void bindQuestion(stageId, questionId)}
              />
            ) : null}
            {viewStep === "confirmation" ? (
              <div className="ldw-card ldw-finalize-card" data-testid="ldw-finalize">
                <div className="ldw-card-head">
                  <strong>发布</strong>
                </div>
                {design?.status === "finalized" || finalResult ? (
                  <div className="ldw-final-result">
                    <p>
                      已生成课时草稿：<strong>{finalResult?.lesson.title || draft.title || ""}</strong>
                      （版本 {String((finalResult?.lesson.metadata || {}).lesson_version || 1)}，
                      {String((finalResult?.lesson.metadata || {}).ready_for_class) === "true" ? "可进入课堂" : "待模拟测试"}）
                    </p>
                    <div className="ldw-actions">
                      <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => void exportWord()}>
                        下载教案 Word
                      </button>
                      {onEnterRehearsal && finalResult ? (
                        <button
                          type="button"
                          className="toolbar-button compact primary"
                          disabled={busy}
                          onClick={() => onEnterRehearsal(finalResult.lesson)}
                          data-testid="ldw-enter-rehearsal"
                        >
                          进入模拟测试
                        </button>
                      ) : null}
                    </div>
                    <p className="ldw-hint">进入「模拟测试」试讲一遍，通过后即可发布为正式课堂。</p>
                  </div>
                ) : (
                  <div className="ldw-actions">
                    <button
                      type="button"
                      className="toolbar-button compact primary"
                      disabled={busy || !design}
                      onClick={() => void finalize()}
                      data-testid="ldw-finalize-button"
                    >
                      确认发布为课时草稿
                    </button>
                    <span className="ldw-hint">发布前会再次运行预演检查；通过后生成第一版 Word。</span>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        </main>

        <aside className="ldw-right">
          <header className="ldw-right-head">
            <strong>AI 共创</strong>
            {activeQuestion ? <p className="ldw-active-question" data-testid="ldw-active-question">{activeQuestion}</p> : null}
          </header>
          <div className="ldw-chat" aria-live="polite" data-testid="ldw-chat">
            {messages.map((message, index) => (
              <div key={`${message.role}-${index}`} className={`lesson-design-message ${message.role}`}>
                <span>{message.role === "assistant" ? "助手" : "教师"}</span>
                <p>{message.text}</p>
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>
          {error ? <p className="lesson-design-error" data-testid="ldw-error">{error}</p> : null}
          <div className="ldw-composer">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                  event.preventDefault();
                  void runTurn(input);
                }
              }}
              placeholder={activeQuestion || "告诉我你的教学想法；Ctrl/⌘ + Enter 发送"}
              disabled={busy}
              aria-label="教案设计对话输入"
            />
            <div className="ldw-actions">
              <button type="button" className="toolbar-button compact" disabled={busy || !design} onClick={() => void runTurn("返回上一步，重新讨论上一部分")}>
                返回上一步
              </button>
              <button
                type="button"
                className="toolbar-button compact"
                disabled={busy || !design || !STEP_SECTION_KEYS[viewStep]?.length}
                onClick={() => void acceptStep()}
                data-testid="ldw-accept-step"
              >
                接受本节
              </button>
              <button
                type="button"
                className="toolbar-button compact primary"
                disabled={busy || !input.trim()}
                onClick={() => void runTurn(input)}
                data-testid="ldw-send"
              >
                发送
              </button>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------
// 章节编辑卡片内容（按 sectionId 分发）
// ----------------------------------------------------------------------
function SectionBody({
  sectionId,
  design,
  busy,
  onSave,
  onRemoveQuestion,
  onBindCandidate
}: {
  sectionId: string;
  design: LessonDesignSession | null;
  busy: boolean;
  onSave: (value: unknown) => void;
  onRemoveQuestion: (stageId: string, questionId: string) => void;
  onBindCandidate: (stageId: string, questionId: string) => void;
}) {
  const draft = design?.draft || {};
  const [text, setText] = useState("");
  useEffect(() => {
    setText(serializeSection(sectionId, draft));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectionId, design?.revision]);

  if (sectionId === "stages") {
    return (
      <div className="ldw-stages" data-testid="ldw-stages">
        {stageList(draft).map((stage, index) => (
          <div key={stage.stage_id || index} className="ldw-stage">
            <div className="ldw-card-head">
              <strong>
                环节{index + 1}｜{stage.title}｜{stage.minutes}分钟
              </strong>
              <span className="ldw-hint">{stage.knowledge_point || ""}</span>
            </div>
            <dl className="ldw-stage-fields">
              {stage.material ? <div><dt>材料</dt><dd>{stage.material}</dd></div> : null}
              {stage.question_chain?.length ? <div><dt>问题链</dt><dd>{stage.question_chain.join("；")}</dd></div> : null}
              {stage.teacher_activities?.length ? <div><dt>教师活动</dt><dd>{stage.teacher_activities.join("；")}</dd></div> : null}
              {stage.student_activities?.length ? <div><dt>学生活动</dt><dd>{stage.student_activities.join("；")}</dd></div> : null}
              {stage.knowledge_conclusion ? <div><dt>知识结论</dt><dd>{stage.knowledge_conclusion}</dd></div> : null}
              {stage.design_intent ? <div><dt>设计意图</dt><dd>{stage.design_intent}</dd></div> : null}
            </dl>
            {stage.questions?.length ? (
              <ul className="ldw-question-list">
                {stage.questions.map((question) => (
                  <li key={question.question_id}>
                    <p>{formatQuestion(question)}</p>
                    <button
                      type="button"
                      className="mini-control"
                      disabled={busy}
                      onClick={() => onRemoveQuestion(stage.stage_id, question.question_id)}
                      aria-label="移除题目"
                    >
                      移除
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ))}
        <details className="ldw-direct-edit">
          <summary>直接编辑教学过程</summary>
          <textarea value={text} onChange={(event) => setText(event.target.value)} aria-label="直接编辑教学过程" />
          <button
            type="button"
            className="toolbar-button compact"
            disabled={busy || !text.trim()}
            onClick={() => onSave(parseStages(text, draft))}
          >
            保存教学过程
          </button>
        </details>
      </div>
    );
  }

  if (sectionId === "question_citations") {
    const citations = draft.question_citations || [];
    if (!citations.length) {
      return <p className="ldw-hint">还没有引用题库题目。在下方按环节检索并选用，或录入手动题目。</p>;
    }
    return (
      <ul className="ldw-citation-list" data-testid="ldw-citations">
        {citations.map((citation, index) => (
          <li key={`${citation.question_id}-${index}`}>
            <strong>{citation.number || citation.question_id.slice(-12)}</strong>
            <small>
              {[citation.year, citation.region, citation.source_paper].filter(Boolean).join(" · ")}
              {citation.selection_reason ? ` · ${citation.selection_reason}` : ""}
            </small>
          </li>
        ))}
      </ul>
    );
  }

  if (sectionId === "capabilities") {
    const bindings = design?.capability_bindings || [];
    return (
      <div>
        <ul className="ldw-cap-list">
          {bindings.map((binding) => (
            <li key={binding.id}>
              <strong>{binding.label || binding.id}</strong>
              <small>{binding.reason || ""}</small>
            </li>
          ))}
          {!bindings.length ? <li className="ldw-hint">尚未匹配系统能力。</li> : null}
        </ul>
        <details className="ldw-direct-edit">
          <summary>直接编辑能力配置</summary>
          <textarea value={text} onChange={(event) => setText(event.target.value)} aria-label="直接编辑能力配置" />
          <button
            type="button"
            className="toolbar-button compact"
            disabled={busy || !text.trim()}
            onClick={() =>
              onSave({
                capabilities: text
                  .split(/\r?\n/)
                  .map((line) => line.split("｜"))
                  .map(([id, reason]) => ({ id: (id || "").trim(), reason: (reason || "").trim() || "教师直接配置" }))
                  .filter((item) => item.id)
              })
            }
          >
            保存能力配置
          </button>
        </details>
      </div>
    );
  }

  if (sectionId === "requirements") {
    return (
      <div>
        <p className="ldw-section-text">{asText((draft.requirements as { raw?: unknown } | undefined)?.raw) || "尚未填写教学需求。"}</p>
        <details className="ldw-direct-edit">
          <summary>直接编辑教学需求</summary>
          <textarea value={text} onChange={(event) => setText(event.target.value)} aria-label="直接编辑教学需求" />
          <button type="button" className="toolbar-button compact" disabled={busy || !text.trim()} onClick={() => onSave({ requirements: { ...(draft.requirements as object), raw: text.trim() } })}>
            保存教学需求
          </button>
        </details>
      </div>
    );
  }

  // 纯文本 / 列表型章节的通用编辑器
  return (
    <div>
      <p className="ldw-section-text">{text || "待补充。"}</p>
      <details className="ldw-direct-edit">
        <summary>直接编辑{SECTION_LABELS[sectionId] || "本节内容"}</summary>
        <textarea value={text} onChange={(event) => setText(event.target.value)} aria-label={`直接编辑${SECTION_LABELS[sectionId] || sectionId}`} />
        <button type="button" className="toolbar-button compact" disabled={busy || !text.trim()} onClick={() => onSave(parseSection(sectionId, text))}>
          保存{SECTION_LABELS[sectionId] || "本节"}
        </button>
      </details>
    </div>
  );
}

function serializeSection(sectionId: string, draft: Record<string, unknown> & { [key: string]: any }): string {
  switch (sectionId) {
    case "requirements":
      return asText((draft.requirements as { raw?: unknown } | undefined)?.raw);
    case "curriculum_interpretation":
    case "student_analysis":
    case "textbook_analysis":
    case "board_design":
    case "design_thinking":
    case "reflection":
      return asText(draft[sectionId]);
    case "objectives":
      return (draft.objectives || []).join("\n");
    case "key_difficulties": {
      const kd = draft.key_difficulties || {};
      return [`重点：${(kd.key || []).join("；")}`, `难点：${(kd.difficult || []).join("；")}`].join("\n");
    }
    case "methods":
      return (draft.methods || []).join("；");
    case "knowledge_structure":
      return (draft.knowledge_structure || []).join(" → ");
    case "core_questions": {
      const cq = draft.core_questions || { core: "", sub_questions: [] };
      return [`核心问题：${cq.core || ""}`, ...(cq.sub_questions || []).map((item: string, index: number) => `子问题${index + 1}：${item}`)].join("\n");
    }
    case "homework": {
      const hw = draft.homework || { basic: [], inquiry: [] };
      return [`基础作业：${(hw.basic || []).join("；")}`, `探究作业：${(hw.inquiry || []).join("；")}`].join("\n");
    }
    case "capabilities":
      return (draft.capabilities || []).map((item: { id: string; reason?: string; label?: string }) => `${item.id}｜${item.reason || item.label || ""}`).join("\n");
    case "stages":
      return stageList(draft).map((stage: LessonStage, index: number) =>
        [
          `环节${index + 1}｜${stage.title}｜${stage.minutes}分钟`,
          `知识点：${stage.knowledge_point || ""}`,
          `材料：${stage.material || ""}`,
          `问题链：${(stage.question_chain || []).join("；")}`,
          `教师活动：${(stage.teacher_activities || []).join("；")}`,
          `学生活动：${(stage.student_activities || []).join("；")}`,
          `知识结论：${stage.knowledge_conclusion || ""}`,
          `设计意图：${stage.design_intent || ""}`
        ].join("\n")
      ).join("\n\n");
    default:
      return "";
  }
}

function parseSection(sectionId: string, text: string): unknown {
  const lines = () => text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  switch (sectionId) {
    case "curriculum_interpretation":
    case "student_analysis":
    case "textbook_analysis":
    case "board_design":
    case "design_thinking":
    case "reflection":
      return text.trim();
    case "objectives":
      return splitItems(text);
    case "key_difficulties":
      return {
        key: splitItems(text.split(/\r?\n/).find((line) => line.startsWith("重点"))?.split("：")[1] || ""),
        difficult: splitItems(text.split(/\r?\n/).find((line) => line.startsWith("难点"))?.split("：")[1] || "")
      };
    case "methods":
      return splitItems(text);
    case "knowledge_structure":
      return text.split(/→|->/).map((item) => item.trim()).filter(Boolean);
    case "core_questions":
      return {
        core: text.split(/\r?\n/).find((line) => line.startsWith("核心问题"))?.split("：").slice(1).join("：").trim() || "",
        sub_questions: lines()
          .filter((line) => line.startsWith("子问题"))
          .map((line) => line.split("：").slice(1).join("：").trim())
          .filter(Boolean)
      };
    case "homework":
      return {
        basic: splitItems(text.split(/\r?\n/).find((line) => line.startsWith("基础作业"))?.split("：")[1] || ""),
        inquiry: splitItems(text.split(/\r?\n/).find((line) => line.startsWith("探究作业"))?.split("：")[1] || "")
      };
    default:
      return text.trim();
  }
}

function stageList(draft: { stages?: unknown } | undefined): LessonStage[] {
  // 历史数据可能存在被写坏的非数组 stages（直接编辑缺陷），渲染层统一容错。
  return Array.isArray(draft?.stages) ? (draft.stages as LessonStage[]) : [];
}

function parseStages(text: string, draft: { stages?: Array<Record<string, any>> }): unknown {
  const previous = Array.isArray(draft.stages) ? draft.stages : [];
  const blocks = text.split(/\r?\n\s*\r?\n/);
  const stages = blocks
    .map((block, index) => {
      const header = (block.split(/\r?\n/)[0] || "").split("｜");
      const old = previous[index] || {};
      const minutes = Number.parseInt(String(header[2] || "").replace(/[^0-9]/g, ""), 10);
      const lineValue = (label: string) => {
        const line = block.split(/\r?\n/).find((item) => item.trim().startsWith(label));
        return line ? line.split("：").slice(1).join("：").trim() : "";
      };
      return {
        ...old,
        stage_id: old.stage_id || `s${index + 1}`,
        title: (header[1] || "").trim() || old.title || `环节${index + 1}`,
        minutes: Number.isFinite(minutes) ? minutes : old.minutes || 0,
        knowledge_point: lineValue("知识点") || old.knowledge_point || "",
        material: lineValue("材料"),
        question_chain: splitItems(lineValue("问题链")),
        teacher_activities: splitItems(lineValue("教师活动")),
        student_activities: splitItems(lineValue("学生活动")),
        knowledge_conclusion: lineValue("知识结论"),
        design_intent: lineValue("设计意图") || old.design_intent || ""
      };
    })
    .filter((stage) => stage.title);
  // 直接编辑走 SECTION 级 resolve：value 必须是 stages 数组本身；
  // 包一层 {stages:[…]} 会被原样写入 draft.stages 导致白屏（历史缺陷）。
  return stages;
}

// ----------------------------------------------------------------------
// 预演检查卡片
// ----------------------------------------------------------------------
function RehearsalCard({ design, onRun, busy }: { design: LessonDesignSession | null; onRun: () => void; busy: boolean }) {
  const [report, setReport] = useState<{ ready?: boolean; errors?: string[]; warnings?: string[]; total_minutes?: number } | null>(null);
  const revision = design?.revision || 0;
  useEffect(() => {
    setReport(null);
  }, [revision]);
  return (
    <div className="ldw-card ldw-rehearsal" data-testid="ldw-rehearsal">
      <div className="ldw-card-head">
        <strong>预演检查</strong>
        <button type="button" className="toolbar-button compact" disabled={busy || !design} onClick={() => void runReport()}>
          重新检查
        </button>
      </div>
      <p className="ldw-hint">
        检查环节时间是否与课时完全一致、目标是否有活动支撑、问题链是否递进、题目答案与题图是否完备。
      </p>
      {report ? (
        <div className={`ldw-report ${report.ready ? "ok" : "bad"}`}>
          <strong>{report.ready ? "结构已通过，可进入确认发布" : "仍有需要补充的内容"}</strong>
          {report.errors?.length ? <small className="ldw-report-errors">必须处理：{report.errors.join("；")}</small> : null}
          {report.warnings?.length ? <small>建议关注：{report.warnings.join("；")}</small> : null}
        </div>
      ) : null}
      <button type="button" className="toolbar-button compact primary" disabled={busy || !design} onClick={onRun} data-testid="ldw-run-rehearsal">
        运行完整预演
      </button>
    </div>
  );

  async function runReport() {
    if (!design) return;
    try {
      const result = await turnLessonDesign(design.design_id, "请运行完整预演检查", design.revision, "rehearsal");
      const next = result.rehearsal_report as { ready?: boolean; errors?: string[]; warnings?: string[] } | null;
      setReport(next || null);
    } catch {
      setReport(null);
    }
  }
}

// ----------------------------------------------------------------------
// 题目匹配卡片（检索 / 候选 / 手动录入）
// ----------------------------------------------------------------------
function QuestionMatchingCard({
  design,
  banks,
  candidates,
  searchText,
  searchResults,
  busy,
  manualOpen,
  manualForm,
  onSearchText,
  onRunSearch,
  onToggleManual,
  onManualForm,
  onBindManual,
  onBindSearchResult
}: {
  design: LessonDesignSession | null;
  banks: QuestionBankSummary[];
  candidates: QuestionRetrievalCandidate[];
  searchText: string;
  searchResults: QuestionBankQuestion[];
  busy: boolean;
  manualOpen: boolean;
  manualForm: { text: string; answer: string; explanation: string };
  onSearchText: (value: string) => void;
  onRunSearch: () => void;
  onToggleManual: () => void;
  onManualForm: (patch: Partial<{ text: string; answer: string; explanation: string }>) => void;
  onBindManual: (stageId: string) => void;
  onBindSearchResult: (stageId: string, questionId: string) => void;
}) {
  const stages = stageList(design?.draft || {});
  const [targetStage, setTargetStage] = useState("");
  const activeStage = targetStage && stages.some((stage) => stage.stage_id === targetStage) ? targetStage : stages[0]?.stage_id || "";
  if (!banks.length) {
    return <p className="ldw-hint">先在左侧导入题库（原卷版 + 解析版 成对上传），才能自动匹配题目。</p>;
  }
  return (
    <div className="ldw-card ldw-matching" data-testid="ldw-matching">
      <div className="ldw-card-head">
        <strong>题目检索与绑定</strong>
        <select value={activeStage} onChange={(event) => setTargetStage(event.target.value)} aria-label="目标教学环节">
          {stages.map((stage) => (
            <option key={stage.stage_id} value={stage.stage_id}>
              {stage.title}
            </option>
          ))}
        </select>
      </div>
      <div className="ldw-search-row">
        <input
          value={searchText}
          onChange={(event) => onSearchText(event.target.value)}
          placeholder="输入考点 / 知识点关键词检索，例如：人口分布 自然因素 地形"
          aria-label="题目检索关键词"
          data-testid="ldw-search-input"
        />
        <button type="button" className="toolbar-button compact" disabled={busy || !searchText.trim()} onClick={onRunSearch} data-testid="ldw-search-button">
          检索
        </button>
      </div>
      {searchResults.length ? (
        <ul className="ldw-candidate-list" data-testid="ldw-search-results">
          {searchResults.map((item) => (
            <li key={item.question_id}>
              <div className="ldw-candidate-main">
                <strong>
                  {item.number || ""} {item.stem || item.task_text || ""}
                </strong>
                <small>
                  {[item.year, item.region, item.section_title].filter(Boolean).join(" · ")}
                  {item.answer_complete ? " · 答案完备" : " · 答案缺失"}
                  {item.relevance !== undefined ? ` · 相关度 ${(item.relevance * 100).toFixed(0)}%` : ""}
                </small>
              </div>
              <button
                type="button"
                className="toolbar-button compact"
                disabled={busy || !activeStage}
                onClick={() => onBindSearchResult(activeStage, item.question_id)}
              >
                选用
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {candidates.length ? (
        <div className="ldw-candidate-block">
          <strong>本轮自动检索候选</strong>
          <ul className="ldw-candidate-list" data-testid="ldw-candidates">
            {candidates.map((candidate) => (
              <li key={`${candidate.stage_id}-${candidate.question_id}`}>
                <div className="ldw-candidate-main">
                  <strong>
                    {candidate.number || ""} {candidate.stem}
                  </strong>
                  <small>
                    {candidate.stage_title} · {[candidate.year, candidate.region].filter(Boolean).join(" · ")} · 相关度{" "}
                    {(candidate.relevance * 100).toFixed(0)}%
                    {candidate.auto_selectable ? " · 可自动选用" : ""}
                    {candidate.answer_complete ? "" : " · 答案缺失"}
                  </small>
                  {candidate.selection_reason ? <small className="ldw-hint">{candidate.selection_reason}</small> : null}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="ldw-manual">
        <button type="button" className="toolbar-button compact" onClick={onToggleManual} data-testid="ldw-manual-toggle">
          {manualOpen ? "收起手动录入" : "录入手动题目"}
        </button>
        {manualOpen ? (
          <div className="ldw-manual-form">
            <textarea
              value={manualForm.text}
              onChange={(event) => onManualForm({ text: event.target.value })}
              placeholder="题干（可含材料；如需选项请每行一个写「选项：」开头）"
              aria-label="手动题目题干"
            />
            <textarea
              value={manualForm.answer}
              onChange={(event) => onManualForm({ answer: event.target.value })}
              placeholder="参考答案（进入真实课堂或课后练习前必填）"
              aria-label="手动题目参考答案"
            />
            <textarea
              value={manualForm.explanation}
              onChange={(event) => onManualForm({ explanation: event.target.value })}
              placeholder="解析（建议填写）"
              aria-label="手动题目解析"
            />
            <button
              type="button"
              className="toolbar-button compact primary"
              disabled={busy || !manualForm.text.trim() || !activeStage}
              onClick={() => onBindManual(activeStage)}
              data-testid="ldw-manual-bind"
            >
              加入环节
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
