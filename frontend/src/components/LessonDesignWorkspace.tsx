import { ThinkingIndicator } from "./ThinkingIndicator";
import "./LessonDesignWorkspace.css";
import { LessonCellEditor } from "./LessonCellEditor";
import { LessonProcessTable } from "./LessonProcessTable";
import { DocxImportReview, type ImportReviewApplyPayload } from "./DocxImportReview";
import type { LibraryAsset } from "./PresentationLayoutEditor";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  applyLessonImportReview,
  applyLessonMigration,
  buildAuthenticatedUrl,
  bindLessonDesignQuestion,
  createLessonDesign,
  exportDesignDocx,
  exportDesignPdf,
  exportLessonDocx,
  exportLessonPdf,
  fetchJob,
  fetchLesson,
  fetchLessonDesign,
  fetchLessonMigrationPreview,
  fetchOutputs,
  fetchQuestionBanks,
  finalizeLessonDesign,
  importLessonDocx,
  importQuestionBanks,
  resolveLessonDesignSection,
  searchQuestionBanks,
  turnLessonDesign
} from "../api";
import type {
  DesignPlanItem,
  LessonDesignSession,
  LessonDocxImportResult,
  LessonMigrationPreview,
  LessonPlanProfile,
  LessonQuestion,
  LessonRecord,
  LessonStage,
  QuestionBankQuestion,
  QuestionBankSummary,
  SceneSnapshot
} from "../types";
import { PRESET_METHODS, STEP_FOR_SECTION, diffStages, formatQuestion, splitLines, stageList } from "../lib/lessonSheet";

type Props = {
  projectId: string;
  initialDesignId?: string;
  onClose: () => void;
  onFinalized?: (lesson: LessonRecord) => void;
  /** 定稿后直接进入该课时的模拟测试（试讲 → 发布为可上课版本）。 */
  onEnterRehearsal?: (lesson: LessonRecord) => void;
  /** 读取当前地图/地球场景快照（供环节绑定当前场景）。 */
  getSceneSnapshot?: () => SceneSnapshot;
};

type DesignRehearsalReport = {
  ready: boolean;
  errors?: string[];
  warnings?: string[];
  total_minutes?: number;
  duration_minutes?: number;
};

type DiffModalState = {
  sectionId: string;
  sectionLabel: string;
  before: unknown;
  after: unknown;
  stageDiffs: ReturnType<typeof diffStages>;
  oldText: string;
  newText: string;
};

const SECTION_LABELS: Record<string, string> = {
  title: "课题", grade: "年级", duration_minutes: "课时", subject: "学科",
  requirements: "教学需求", curriculum_interpretation: "课标解读", student_analysis: "学情分析",
  textbook_analysis: "教材分析", objectives: "教学目标", key_difficulties: "教学重难点",
  methods: "教学方法", knowledge_structure: "知识结构", board_design: "板书设计",
  homework: "课后作业", design_thinking: "设计思路", reflection: "教学反思", references: "参考资料",
  stages: "教学过程"
};

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function openArtifactUrl(url: unknown) {
  if (typeof url === "string" && url) window.open(buildAuthenticatedUrl(url), "_blank", "noopener,noreferrer");
}

function draftRecord(draft: LessonPlanProfile): Record<string, unknown> {
  return (draft || {}) as Record<string, unknown>;
}

export function LessonDesignWorkspace({ projectId, initialDesignId = "", onClose, onFinalized, onEnterRehearsal, getSceneSnapshot }: Props) {
  const [design, setDesign] = useState<LessonDesignSession | null>(null);
  const [planItems, setPlanItems] = useState<DesignPlanItem[]>([]);
  const [libraryAssets, setLibraryAssets] = useState<LibraryAsset[]>([]);
  const [messages, setMessages] = useState<Array<{ role: "assistant" | "teacher"; text: string }>>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [checkedPlan, setCheckedPlan] = useState<{ designId: string; revision: number; report: DesignRehearsalReport } | null>(null);
  const [banks, setBanks] = useState<QuestionBankSummary[]>([]);
  const [importBusy, setImportBusy] = useState(false);
  const [importNote, setImportNote] = useState("");
  const [searchText, setSearchText] = useState("");
  const [searchResults, setSearchResults] = useState<QuestionBankQuestion[]>([]);
  const [finalResult, setFinalResult] = useState<{ lesson: LessonRecord } | null>(null);
  const [migration, setMigration] = useState<LessonMigrationPreview | null>(null);
  const [migrationDismissed, setMigrationDismissed] = useState(false);
  const [importInfo, setImportInfo] = useState<LessonDocxImportResult | null>(null);
  const [diffModal, setDiffModal] = useState<DiffModalState | null>(null);
  const [aiTarget, setAiTarget] = useState<{ sectionId: string; label: string; stageId?: string } | null>(null);
  const docxInputRef = useRef<HTMLInputElement | null>(null);
  const bankInputRef = useRef<HTMLInputElement | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const applySession = useCallback((payload: LessonDesignSession & Partial<{ plan_items: DesignPlanItem[] }>) => {
    setDesign(payload);
    if (payload.plan_items) setPlanItems(payload.plan_items);
    const review = draftRecord(payload.draft).import_review as Pick<LessonDocxImportResult, "mapping" | "unclassified" | "summary"> | undefined;
    setImportInfo(review ? { ...review, status: "success", design: payload } : null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError("");
    setDesign(null);
    setFinalResult(null);
    setCheckedPlan(null);
    setPlanItems([]);
    setMessages([]);
    setInput("");
    setBanks([]);
    setSearchResults([]);
    setSearchText("");
    setImportNote("");
    setImportInfo(null);
    setDiffModal(null);
    setAiTarget(null);
    setMigration(null);
    setMigrationDismissed(false);
    const load = initialDesignId
      ? fetchLessonDesign(initialDesignId)
      : createLessonDesign(projectId);
    load
      .then((payload) => {
        if (cancelled) return;
        applySession(payload);
        setMessages([{ role: "assistant", text: "这是一页表格式教案：点击任意单元格直接修改，也可以让 AI 只改指定环节，展示差异后由你采用。" }]);
        if (payload.status === "finalized" && payload.final_lesson_id) {
          fetchLesson(payload.final_lesson_id)
            .then((lesson) => {
              if (!cancelled) setFinalResult({ lesson });
            })
            .catch(() => undefined);
        }
      })
      .catch((exc) => {
        if (!cancelled) setError(exc instanceof Error ? exc.message : String(exc));
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
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

  // 展示编排素材源：项目图片库（上传图片 + AI 生成图 + Word 导入图），与模拟测试一致。
  useEffect(() => {
    let cancelled = false;
    fetchOutputs(projectId)
      .then((result) => {
        if (cancelled) return;
        const assets = (result.items || [])
          .filter((item) => ["uploaded_image", "generated_image", "lesson_import_image"].includes(item.artifact_type))
          .map((item) => ({
            artifact_id: item.artifact_id,
            title: item.title,
            url: String(item.metadata?.public_url || ""),
            mime_type: String(item.metadata?.mime_type || "image/png")
          }))
          .filter((item) => item.url);
        setLibraryAssets(assets);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // 旧草稿迁移预览：core_questions / capabilities 有内容且未迁移时加载。
  useEffect(() => {
    if (!design || design.status === "finalized" || migrationDismissed) return;
    const values = draftRecord(design.draft);
    const core = values.core_questions as { core?: string; sub_questions?: string[] } | undefined;
    const hasLegacy = Boolean((core?.core || core?.sub_questions?.length) || (Array.isArray(values.capabilities) && values.capabilities.length));
    if (!hasLegacy || values.legacy_migration_applied) {
      setMigration(null);
      return;
    }
    let cancelled = false;
    fetchLessonMigrationPreview(design.design_id)
      .then((preview) => {
        if (!cancelled) setMigration(preview);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [design, migrationDismissed]);

  const draft = design?.draft || {};
  const isFinalized = design?.status === "finalized";
  const values = draftRecord(draft);
  const stages = stageList(draft);
  const currentReport = checkedPlan?.designId === design?.design_id && checkedPlan?.revision === design?.revision ? checkedPlan?.report : null;

  function showError(exc: unknown) {
    setError(exc instanceof Error ? exc.message : String(exc));
  }

  async function directEdit(sectionId: string, value: unknown): Promise<boolean> {
    if (!design || busy || isFinalized) return false;
    setBusy(true);
    setError("");
    try {
      const result = await resolveLessonDesignSection(design.design_id, sectionId, "edit", "", design.revision, value);
      applySession(result.design);
      return true;
    } catch (exc) {
      showError(exc);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function acceptAll() {
    if (!design || busy || isFinalized) return;
    setBusy(true);
    setError("");
    try {
      const result = await resolveLessonDesignSection(design.design_id, "all", "accept", "", design.revision);
      applySession(result.design);
      setMessages((previous) => [...previous, { role: "assistant", text: result.message || "已确认整份教案。" }]);
    } catch (exc) {
      showError(exc);
    } finally {
      setBusy(false);
    }
  }

  async function runPlanCheck() {
    if (!design || busy) return;
    setBusy(true);
    setError("");
    setCheckedPlan(null);
    try {
      const latest: LessonDesignSession & { rehearsal_report?: DesignRehearsalReport } = await fetchLessonDesign(design.design_id);
      if (!latest.rehearsal_report || typeof latest.rehearsal_report.ready !== "boolean") {
        throw new Error("当前后端未返回预演报告，请更新后端后重试。");
      }
      applySession(latest);
      setCheckedPlan({ designId: latest.design_id, revision: latest.revision, report: latest.rehearsal_report });
    } catch (exc) {
      showError(exc);
    } finally {
      setBusy(false);
    }
  }

  async function runTurn(text: string, step = "") {
    if (!design || isFinalized || !text.trim() || busy) return;
    const target = aiTarget;
    const before = target ? JSON.parse(JSON.stringify(design.draft || {})) : null;
    setMessages((previous) => [...previous, { role: "teacher", text }]);
    setBusy(true);
    setError("");
    try {
      const result = await turnLessonDesign(design.design_id, text, design.revision, step || (target ? STEP_FOR_SECTION[target.sectionId] || "" : ""), target?.sectionId, target?.stageId);
      if (!target) applySession({
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
      setMessages((previous) => [...previous, { role: "assistant", text: result.assistant_message }]);
      setInput("");
      if (result.rehearsal_report && typeof (result.rehearsal_report as DesignRehearsalReport).ready === "boolean") {
        setCheckedPlan({ designId: design.design_id, revision: result.revision, report: result.rehearsal_report as DesignRehearsalReport });
      }
      // AI 定位修改：仅当目标明确时给出差异弹层，教师采用或放弃。
      if (target && before) {
        const sectionLabel = target.label;
        const after = result.draft || {};
        if (target.sectionId === "stages") {
          const stageDiffs = diffStages(before, after);
          if (stageDiffs.length) {
            setDiffModal({ sectionId: "stages", sectionLabel, before: (before as { stages?: unknown }).stages ?? [], after: (after as { stages?: unknown }).stages ?? [], stageDiffs, oldText: "", newText: "" });
          }
        } else {
          const oldValue = (before as Record<string, unknown>)[target.sectionId];
          const newValue = (after as Record<string, unknown>)[target.sectionId];
          if (JSON.stringify(oldValue ?? null) !== JSON.stringify(newValue ?? null)) {
            setDiffModal({
              sectionId: target.sectionId,
              sectionLabel,
              before: oldValue,
              after: newValue,
              stageDiffs: [],
              oldText: typeof oldValue === "string" ? oldValue : JSON.stringify(oldValue ?? "", null, 2),
              newText: typeof newValue === "string" ? newValue : JSON.stringify(newValue ?? "", null, 2)
            });
          }
        }
      }
    } catch (exc) {
      showError(exc);
    } finally {
      setBusy(false);
    }
  }

  async function adoptDiff() {
    if (!design || !diffModal) return;
    setBusy(true);
    setError("");
    try {
      const result = await resolveLessonDesignSection(design.design_id, diffModal.sectionId, "edit", "", design.revision, diffModal.after);
      applySession(result.design);
      setDiffModal(null);
      setMessages((previous) => [...previous, { role: "assistant", text: `「${diffModal.sectionLabel}」的 AI 修改已采用，待整份核对确认。` }]);
    } catch (exc) {
      showError(exc);
    } finally {
      setBusy(false);
    }
  }

  async function discardDiff() {
    if (!design || !diffModal) return;
    setDiffModal(null);
  }

  async function finalize() {
    if (!design) return;
    setBusy(true);
    setError("");
    try {
      const result = await finalizeLessonDesign(design.design_id, design.revision);
      applySession(result.design);
      setFinalResult({ lesson: result.lesson });
      setMessages((previous) => [...previous, { role: "assistant", text: "教案草稿已生成第一版 Word。进入「模拟测试」试讲一遍，通过后即可发布为正式课堂。" }]);
      onFinalized?.(result.lesson);
    } catch (exc) {
      showError(exc);
    } finally {
      setBusy(false);
    }
  }

  async function exportDraftWord() {
    if (!design) return;
    setBusy(true);
    setError("");
    try {
      if (design.final_lesson_id) {
        const result = await exportLessonDocx(design.final_lesson_id, projectId, design.design_id);
        openArtifactUrl(result.artifact?.metadata?.public_url);
      } else {
        const result = await exportDesignDocx(design.design_id, projectId);
        openArtifactUrl(result.artifact?.metadata?.public_url);
      }
    } catch (exc) {
      showError(exc);
    } finally {
      setBusy(false);
    }
  }

  async function exportDraftPdf() {
    if (!design) return;
    setBusy(true);
    setError("");
    try {
      if (design.final_lesson_id) {
        const result = await exportLessonPdf(design.final_lesson_id, projectId, design.design_id);
        openArtifactUrl(result.artifact?.metadata?.public_url);
      } else {
        const result = await exportDesignPdf(design.design_id, projectId);
        openArtifactUrl(result.artifact?.metadata?.public_url);
      }
    } catch (exc) {
      showError(exc);
    } finally {
      setBusy(false);
    }
  }

  async function importDocx(file: File | null | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const result = await importLessonDocx(projectId, file);
      applySession(result.design);
      setImportInfo(result);
      setCheckedPlan(null);
      setFinalResult(null);
      setMessages([{ role: "assistant", text: result.summary }]);
      const params = new URLSearchParams(window.location.search);
      params.delete("view");
      params.set("workspace", "lesson-design");
      params.set("design_id", result.design.design_id);
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    } catch (exc) {
      showError(exc);
    } finally {
      setBusy(false);
    }
  }

  async function applyImportReview(payload: ImportReviewApplyPayload) {
    if (!design) return;
    setBusy(true);
    setError("");
    try {
      const result = await applyLessonImportReview(design.design_id, {
        ...payload,
        expected_revision: design.revision
      });
      applySession(result.design);
    } catch (exc) {
      showError(exc);
    } finally {
      setBusy(false);
    }
  }

  async function applyMigration() {
    if (!design) return;
    setBusy(true);
    setError("");
    try {
      const result = await applyLessonMigration(design.design_id, design.revision);
      applySession(result.design);
      setMigration(null);
      setMessages((previous) => [...previous, { role: "assistant", text: result.message || "旧版内容已写入教学环节。" }]);
    } catch (exc) {
      showError(exc);
    } finally {
      setBusy(false);
    }
  }

  async function bindQuestion(stageId: string, questionId = "", manual?: Record<string, unknown>) {
    if (!design) return false;
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
      return true;
    } catch (exc) {
      showError(exc);
      return false;
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
      showError(exc);
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
      }
      if (job.status === "failed") {
        setImportNote("");
        setError(job.error || "题库导入失败。");
        return;
      }
      setImportNote("题库导入完成。");
      const list = await fetchQuestionBanks(projectId);
      setBanks(list.items || []);
    } catch (exc) {
      setImportNote("");
      showError(exc);
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
      showError(exc);
    } finally {
      setBusy(false);
    }
  }

  // ------------------------------------------------------------------
  // 教学过程表操作
  // ------------------------------------------------------------------

  function replaceStages(mutate: (stages: LessonStage[]) => LessonStage[]) {
    if (!design) return;
    const next = mutate(JSON.parse(JSON.stringify(stages)) as LessonStage[]);
    void directEdit("stages", next);
  }

  function handleStageFieldChange(stageIndex: number, field: string, value: unknown) {
    replaceStages((list) => {
      if (list[stageIndex]) (list[stageIndex] as unknown as Record<string, unknown>)[field] = value;
      return list;
    });
  }

  function handleAddStage() {
    replaceStages((list) => [
      ...list,
      {
        ...({
          stage_id: `stage_${Date.now()}_${list.length + 1}`,
          title: `环节${list.length + 1}`,
          minutes: 5,
          kind: "presentation",
          scene: {},
          questions: []
        } as unknown as LessonStage)
      }
    ]);
  }

  function handleRemoveStage(stageIndex: number) {
    replaceStages((list) => list.filter((_, index) => index !== stageIndex));
  }

  // ------------------------------------------------------------------
  // 渲染
  // ------------------------------------------------------------------

  function renderSheetCard(sectionId: string, title: string, content: React.ReactNode) {
    const status = design?.section_status?.[sectionId];
    return (
      <section className="ldw-sheet-card" data-testid={`ldw-sheet-${sectionId}`}>
        <header className="ldw-sheet-card-head">
          <h4>{title}</h4>
          <span className={`ldw-status ldw-status-${status || "pending"}`}>{status === "confirmed" ? "已确认" : status === "proposed" ? "待确认" : "待补充"}</span>
          <button
            type="button"
            className="toolbar-button compact"
            disabled={busy || isFinalized}
            aria-label={`让 AI 修改${title}`}
            onClick={() => {
              setAiTarget({ sectionId, label: title });
              setMessages((previous) => [...previous, { role: "assistant", text: `AI 修改目标已定为「${title}」。在下方输入要求，我会给出修改差异，由你决定是否采用。` }]);
            }}
          >
            AI 改
          </button>
        </header>
        {content}
      </section>
    );
  }

  const requirementsRaw = asText((values.requirements as { raw?: unknown } | undefined)?.raw);
  const difficulties = (values.key_difficulties as { key?: string[]; difficult?: string[] } | undefined) || {};
  const homework = (values.homework as { basic?: string[]; inquiry?: string[] } | undefined) || {};
  const methods = Array.isArray(values.methods) ? (values.methods as string[]) : [];
  const references = Array.isArray(values.references) ? values.references : [];
  const core = (values.core_questions as { core?: string; sub_questions?: string[] } | undefined) || {};

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
          <div className="ldw-sheet-tools">
            <button type="button" className="toolbar-button compact" disabled={busy || isFinalized} onClick={() => docxInputRef.current?.click()} data-testid="ldw-import-docx">
              导入 Word 教案
            </button>
            <input
              ref={docxInputRef}
              type="file"
              accept=".docx"
              hidden
              aria-label="选择 Word 教案文件"
              onChange={(event) => {
                void importDocx(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
            <button type="button" className="toolbar-button compact" disabled={busy || !design} onClick={() => void exportDraftWord()} data-testid="ldw-export-docx">
              下载 Word
            </button>
            <button type="button" className="toolbar-button compact" disabled={busy || !design} onClick={() => void exportDraftPdf()} data-testid="ldw-export-pdf">
              下载 PDF
            </button>
          </div>
          {importInfo ? (
            <details className="ldw-import-card" data-testid="ldw-import-card" open>
              <summary>Word 导入校对（{importInfo.mapping.length} 处映射 · {importInfo.unclassified.length} 条待归类）</summary>
              <DocxImportReview
                mapping={importInfo.mapping}
                unclassified={importInfo.unclassified}
                stages={stages}
                busy={busy}
                onApply={(payload) => void applyImportReview(payload)}
              />
            </details>
          ) : null}
          <div className="ldw-banks" data-testid="ldw-banks">
            <div className="ldw-card-head">
              <strong>题库</strong>
              <button
                type="button"
                className="toolbar-button compact"
                disabled={importBusy}
                onClick={() => bankInputRef.current?.click()}
                data-testid="ldw-import-bank"
              >
                导入题库
              </button>
            </div>
            <input
              ref={bankInputRef}
              type="file"
              accept=".docx"
              multiple
              hidden
              aria-label="选择题库文件"
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
            <h3>表格式教案</h3>
            <span className="ldw-progress">
              {isFinalized ? "已发布课时草稿" : "设计中"}
            </span>
          </header>
          <div className="ldw-mid-scroll" data-testid="ldw-plan">
            <div className="ldw-sheet" data-testid="ldw-sheet">
              {renderSheetCard(
                "requirements",
                "基础信息",
                <div className="ldw-sheet-body">
                  <div className="ldw-sheet-grid">
                    <label>课题
                      <LessonCellEditor value={asText(draft.title || draft.topic)} label="课题" placeholder="待填写课题" disabled={busy || isFinalized} testId="ldw-cell-title" onSave={(value) => void directEdit("title", value)} />
                    </label>
                    <label>年级
                      <LessonCellEditor value={asText(draft.grade)} label="年级" placeholder="如：高一" disabled={busy || isFinalized} testId="ldw-cell-grade" onSave={(value) => void directEdit("grade", value)} />
                    </label>
                    <label>课时（分钟）
                      <LessonCellEditor value={String(draft.duration_minutes ?? "")} label="课时" placeholder="40" numeric disabled={busy || isFinalized} testId="ldw-cell-duration" onSave={(value) => void directEdit("duration_minutes", Number(value))} />
                    </label>
                  </div>
                  <div className="ldw-sheet-field">
                    <span>教学需求</span>
                    <LessonCellEditor
                      value={requirementsRaw}
                      label="教学需求"
                      placeholder="年级、课题、教材与额外要求…"
                      multiline
                      disabled={busy || isFinalized}
                      onSave={(value) => void directEdit("requirements", { ...(draft.requirements as object), raw: value })}
                    />
                  </div>
                </div>
              )}
              {(["curriculum_interpretation", "student_analysis", "textbook_analysis"] as const).map((field) => (
                <div key={field}>
                  {renderSheetCard(field, SECTION_LABELS[field],
                    <LessonCellEditor
                      value={asText(values[field])}
                      label={SECTION_LABELS[field]}
                      placeholder="点击填写"
                      multiline
                      disabled={busy || isFinalized}
                      testId={`ldw-cell-${field}`}
                      onSave={(value) => void directEdit(field, value)}
                    />
                  )}
                </div>
              ))}
              {renderSheetCard(
                "objectives",
                "目标与重难点",
                <div className="ldw-sheet-body">
                  <div className="ldw-sheet-field">
                    <span>教学目标（每行一条）</span>
                    <LessonCellEditor
                      value={Array.isArray(values.objectives) ? (values.objectives as string[]).join("\n") : ""}
                      label="教学目标"
                      multiline
                      disabled={busy || isFinalized}
                      testId="ldw-cell-objectives"
                      onSave={(value) => void directEdit("objectives", splitLines(value))}
                    />
                  </div>
                  <div className="ldw-sheet-grid">
                    <div className="ldw-sheet-field">
                      <span>教学重点（每行一条）</span>
                      <LessonCellEditor
                        value={(difficulties.key || []).join("\n")}
                        label="教学重点"
                        multiline
                        disabled={busy || isFinalized}
                        onSave={(value) => void directEdit("key_difficulties", { key: splitLines(value), difficult: difficulties.difficult || [] })}
                      />
                    </div>
                    <div className="ldw-sheet-field">
                      <span>教学难点（每行一条）</span>
                      <LessonCellEditor
                        value={(difficulties.difficult || []).join("\n")}
                        label="教学难点"
                        multiline
                        disabled={busy || isFinalized}
                        onSave={(value) => void directEdit("key_difficulties", { key: difficulties.key || [], difficult: splitLines(value) })}
                      />
                    </div>
                  </div>
                </div>
              )}
              {renderSheetCard(
                "methods",
                "教学方法",
                <div className="ldw-sheet-body" data-testid="ldw-methods">
                  <div className="ldw-method-chips">
                    {Array.from(new Set([...PRESET_METHODS, ...methods])).map((method) => {
                      const active = methods.includes(method);
                      return (
                        <button
                          key={method}
                          type="button"
                          className={`ldw-method-chip ${active ? "active" : ""}`}
                          disabled={busy || isFinalized}
                          aria-pressed={active}
                          aria-label={`教学方法${method}`}
                          onClick={() => void directEdit("methods", active ? methods.filter((item) => item !== method) : [...methods, method])}
                        >
                          {method}
                        </button>
                      );
                    })}
                  </div>
                  <CustomMethodInput
                    disabled={busy || isFinalized}
                    onAdd={(method) => {
                      if (!methods.includes(method)) void directEdit("methods", [...methods, method]);
                    }}
                  />
                </div>
              )}
              {renderSheetCard(
                "stages",
                "教学过程",
                <LessonProcessTable
                  draft={draft}
                  busy={busy || isFinalized}
                  projectId={projectId}
                  libraryAssets={libraryAssets}
                  searchResults={searchResults}
                  searchText={searchText}
                  onStageFieldChange={handleStageFieldChange}
                  onAddStage={handleAddStage}
                  onRemoveStage={handleRemoveStage}
                  onRemoveQuestion={(stageId, questionId) => void removeQuestion(stageId, questionId)}
                  onBindSearchResult={(stageId, questionId) => void bindQuestion(stageId, questionId)}
                  onBindManual={(stageId, manual) => void bindQuestion(stageId, "", manual)}
                  onSearchText={setSearchText}
                  onRunSearch={() => void runSearch()}
                  onCaptureScene={() => {
                    const snapshot = getSceneSnapshot?.();
                    return (snapshot && Object.keys(snapshot).length ? snapshot : null) as Record<string, unknown> | null;
                  }}
                  onStageAiEdit={(stageIndex) => {
                    setAiTarget({ sectionId: "stages", stageId: stages[stageIndex].stage_id, label: `环节${stageIndex + 1}｜活动与素材` });
                    setMessages((previous) => [...previous, { role: "assistant", text: `AI 修改目标已定为「环节${stageIndex + 1}｜活动与素材」。在下方输入要求，我会给出修改差异，由你决定是否采用。` }]);
                  }}
                />
              )}
              {migration && migration.available && !migrationDismissed ? (
                <section className="ldw-sheet-card ldw-migration" data-testid="ldw-migration">
                  <header className="ldw-sheet-card-head">
                    <h4>旧版内容迁移</h4>
                  </header>
                  <p className="ldw-hint">检测到旧版「核心问题与问题链」「GIS/AI 能力」。确认后将按以下方式写入教学环节（原字段保留可读）：</p>
                  <ul className="ldw-migration-list">
                    {migration.items.map((item, index) => (
                      <li key={index}>
                        {item.kind === "question" ? "问题" : item.kind === "template" ? "教学模板" : item.kind === "dataset" ? "数据图层" : "保留原字段"}
                        ：{item.detail}
                        {item.target_stage_title ? <> → <strong>{item.target_stage_title}</strong></> : null}
                      </li>
                    ))}
                  </ul>
                  <div className="ldw-actions">
                    <button type="button" className="toolbar-button compact" onClick={() => setMigrationDismissed(true)}>
                      暂不迁移
                    </button>
                    <button type="button" className="toolbar-button compact primary" disabled={busy || isFinalized} onClick={() => void applyMigration()} data-testid="ldw-migration-apply">
                      确认写入环节
                    </button>
                  </div>
                </section>
              ) : null}
              <section className="ldw-sheet-card" data-testid="ldw-sheet-extras">
                <header className="ldw-sheet-card-head">
                  <h4>补充栏目</h4>
                </header>
                <details className="ldw-extras">
                  <summary>板书设计 / 作业 / 设计思路 / 反思 / 参考资料 / 独立问题链（旧）</summary>
                  <div className="ldw-sheet-body">
                    {([
                      ["board_design", "板书设计", asText(values.board_design), (value: string) => void directEdit("board_design", value)],
                      ["design_thinking", "设计思路（100-150字）", asText(values.design_thinking), (value: string) => void directEdit("design_thinking", value)],
                      ["reflection", "教学反思", asText(values.reflection), (value: string) => void directEdit("reflection", value)]
                    ] as Array<[string, string, string, (value: string) => void]>).map(([id, label, text, onSave]) => (
                      <div className="ldw-sheet-field" key={id}>
                        <span>{label}</span>
                        <LessonCellEditor value={text} label={label} multiline disabled={busy || isFinalized} onSave={onSave} />
                      </div>
                    ))}
                    <div className="ldw-sheet-grid">
                      <div className="ldw-sheet-field">
                        <span>基础作业（每行一条）</span>
                        <LessonCellEditor
                          value={(homework.basic || []).join("\n")}
                          label="基础作业"
                          multiline
                          disabled={busy || isFinalized}
                          onSave={(value) => void directEdit("homework", { basic: splitLines(value), inquiry: homework.inquiry || [] })}
                        />
                      </div>
                      <div className="ldw-sheet-field">
                        <span>探究作业（每行一条）</span>
                        <LessonCellEditor
                          value={(homework.inquiry || []).join("\n")}
                          label="探究作业"
                          multiline
                          disabled={busy || isFinalized}
                          onSave={(value) => void directEdit("homework", { basic: homework.basic || [], inquiry: splitLines(value) })}
                        />
                      </div>
                    </div>
                    <div className="ldw-sheet-field">
                      <span>参考资料（每行：标题｜年份｜链接）</span>
                      <LessonCellEditor
                        value={references.map((item) => (typeof item === "object" && item ? [item.title || "", item.year || "", item.url || ""].join("｜") : String(item))).join("\n")}
                        label="参考资料"
                        multiline
                        disabled={busy || isFinalized}
                        onSave={(value) =>
                          void directEdit(
                            "references",
                            value.split(/\r?\n/).map((line) => {
                              const [title = "", year = "", url = ""] = line.split("｜").map((part) => part.trim());
                              return { title, year, url };
                            }).filter((item) => item.title || item.url)
                          )
                        }
                      />
                    </div>
                    <div className="ldw-sheet-field">
                      <span>独立问题链（旧字段，已并入环节；可保留）</span>
                      <LessonCellEditor
                        value={[core.core || "", ...(core.sub_questions || [])].filter(Boolean).join("\n")}
                        label="独立问题链"
                        multiline
                        disabled={busy || isFinalized}
                        onSave={(value) => {
                          const lines = value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
                          void directEdit("core_questions", { core: lines[0] || "", sub_questions: lines.slice(1) });
                        }}
                      />
                    </div>
                  </div>
                </details>
              </section>
            </div>
          </div>
          {diffModal ? (
            <div className="ldw-diff-backdrop" role="dialog" aria-label="AI 修改差异" data-testid="ldw-diff-modal">
              <div className="ldw-diff-panel">
                <header>
                  <strong>AI 修改差异 · {diffModal.sectionLabel}</strong>
                  <button type="button" disabled={busy} aria-label="关闭差异" onClick={() => setDiffModal(null)}>×</button>
                </header>
                {diffModal.stageDiffs.length ? (
                  <ul className="ldw-diff-list">
                    {diffModal.stageDiffs.map((item, index) => (
                      <li key={index}>
                        <strong>{item.stageTitle} · {item.fieldLabel}</strong>
                        <div className="ldw-diff-old"><span>原</span><pre>{item.oldValue || "（空）"}</pre></div>
                        <div className="ldw-diff-new"><span>新</span><pre>{item.newValue || "（空）"}</pre></div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div>
                    <div className="ldw-diff-old"><span>原</span><pre>{diffModal.oldText || "（空）"}</pre></div>
                    <div className="ldw-diff-new"><span>新</span><pre>{diffModal.newText || "（空）"}</pre></div>
                  </div>
                )}
                <footer>
                  <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => void discardDiff()} data-testid="ldw-diff-discard">
                    放弃修改
                  </button>
                  <button type="button" className="toolbar-button compact primary" disabled={busy} onClick={() => void adoptDiff()} data-testid="ldw-diff-adopt">
                    采用修改
                  </button>
                </footer>
              </div>
            </div>
          ) : null}
          <footer className="ldw-confirm-bar" data-testid="ldw-action-bar">
            {finalResult || isFinalized ? (
              <div className="ldw-actions ldw-final-actions">
                <span className="ldw-hint">
                  课时草稿：{finalResult?.lesson.title || draft.title}（版本 {String((finalResult?.lesson.metadata || {}).lesson_version || 1)}，
                  {String((finalResult?.lesson.metadata || {}).ready_for_class) === "true" ? "可进入课堂" : "待模拟测试"}）
                </span>
                <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => void exportDraftWord()}>
                  下载 Word
                </button>
                <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => void exportDraftPdf()}>
                  下载 PDF
                </button>
                {onEnterRehearsal && finalResult ? (
                  <button type="button" className="toolbar-button compact primary" disabled={busy} onClick={() => onEnterRehearsal(finalResult.lesson)} data-testid="ldw-enter-rehearsal">
                    进入模拟测试
                  </button>
                ) : null}
              </div>
            ) : (
              <>
                <button type="button" className="toolbar-button compact" disabled={busy || !design} onClick={() => void runPlanCheck()} data-testid="ldw-run-rehearsal">
                  核对整份草稿
                </button>
                <button type="button" className="toolbar-button compact" disabled={busy || !design || isFinalized} onClick={() => void acceptAll()} data-testid="ldw-accept-all">
                  确认整份教案
                </button>
                <button type="button" className="toolbar-button compact primary" disabled={busy || !design || isFinalized} onClick={() => void finalize()} data-testid="ldw-finalize-button">
                  发布为课时草稿
                </button>
              </>
            )}
          </footer>
          {currentReport ? (
            <div className={`ldw-report ${currentReport.ready ? "ok" : "bad"}`} role="status" data-testid="ldw-rehearsal-report">
              <strong>{currentReport.ready ? "结构检查通过，可发布为课时草稿" : "仍有需要补充的内容"}</strong>
              {currentReport.total_minutes !== undefined ? <small>环节合计 {currentReport.total_minutes} 分钟 / 计划 {currentReport.duration_minutes ?? "—"} 分钟</small> : null}
              {currentReport.errors?.length ? <small className="ldw-report-errors">必须处理：{currentReport.errors.join("；")}</small> : null}
              {currentReport.warnings?.length ? <small>建议关注：{currentReport.warnings.join("；")}</small> : null}
            </div>
          ) : null}
        </main>

        <aside className="ldw-right">
          <header className="ldw-right-head"><strong>AI 共创</strong></header>
          {aiTarget ? (
            <p className="ldw-ai-target" data-testid="ldw-ai-target">
              修改目标：<strong>{aiTarget.label}</strong>
              <button type="button" onClick={() => setAiTarget(null)} aria-label="取消 AI 修改目标">取消</button>
            </p>
          ) : null}
          <div className="ldw-chat" aria-live="polite" data-testid="ldw-chat">
            {messages.map((message, index) => (
              <div key={`${message.role}-${index}`} className={`lesson-design-message ${message.role}`}>
                <span>{message.role === "assistant" ? "助手" : "教师"}</span>
                <p>{message.text}</p>
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>
          {busy ? <ThinkingIndicator label="正在处理教案…" testId="lesson-design-thinking" /> : null}
          {error ? <p className="lesson-design-error" data-testid="ldw-error">{error}</p> : null}
          <div className="ldw-composer" data-testid="ldw-composer">
            <div className="ldw-composer-input">
              <textarea
                id="lesson-design-input"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                    event.preventDefault();
                    void runTurn(input);
                  }
                }}
                placeholder={aiTarget ? `描述要如何修改「${aiTarget.label}」…` : "描述要补充或修改的内容…"}
                disabled={busy || isFinalized}
                aria-label="教案设计对话输入"
              />
              <button type="button" className="ldw-send-button" disabled={busy || !input.trim() || isFinalized} onClick={() => void runTurn(input)} aria-label="发送给 AI" title="发送给 AI" data-testid="ldw-send">↑</button>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}

function CustomMethodInput({ disabled, onAdd }: { disabled: boolean; onAdd: (method: string) => void }) {
  const [text, setText] = useState("");
  return (
    <div className="ldw-method-custom">
      <input
        type="text"
        value={text}
        disabled={disabled}
        aria-label="自定义教学方法"
        placeholder="自定义教学方法…"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && text.trim()) {
            event.preventDefault();
            onAdd(text.trim());
            setText("");
          }
        }}
      />
      <button
        type="button"
        className="toolbar-button compact"
        disabled={disabled || !text.trim()}
        onClick={() => {
          onAdd(text.trim());
          setText("");
        }}
      >
        添加
      </button>
    </div>
  );
}

// 保留题目格式化展示（题库绑定 UI 使用）。
export { formatQuestion };
