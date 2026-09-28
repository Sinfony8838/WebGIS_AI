import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LessonDesignWorkspace } from "../components/LessonDesignWorkspace";
import type { LessonDesignSession, LessonDesignTurnResult, LessonPlanProfile } from "../types";

const createMock = vi.fn();
const fetchDesignMock = vi.fn();
const turnMock = vi.fn();
const resolveMock = vi.fn();
const finalizeMock = vi.fn();
const bindMock = vi.fn();
const searchMock = vi.fn();
const fetchBanksMock = vi.fn();
const importDocxMock = vi.fn();
const exportDesignDocxMock = vi.fn();
const exportDesignPdfMock = vi.fn();
const exportLessonPdfMock = vi.fn();
const migrationPreviewMock = vi.fn();
const migrationApplyMock = vi.fn();

vi.mock("../api", () => ({
  createLessonDesign: (...args: unknown[]) => createMock(...args),
  fetchLessonDesign: (...args: unknown[]) => fetchDesignMock(...args),
  turnLessonDesign: (...args: unknown[]) => turnMock(...args),
  resolveLessonDesignSection: (...args: unknown[]) => resolveMock(...args),
  finalizeLessonDesign: (...args: unknown[]) => finalizeMock(...args),
  bindLessonDesignQuestion: (...args: unknown[]) => bindMock(...args),
  searchQuestionBanks: (...args: unknown[]) => searchMock(...args),
  fetchQuestionBanks: (...args: unknown[]) => fetchBanksMock(...args),
  importLessonDocx: (...args: unknown[]) => importDocxMock(...args),
  exportDesignDocx: (...args: unknown[]) => exportDesignDocxMock(...args),
  exportDesignPdf: (...args: unknown[]) => exportDesignPdfMock(...args),
  exportLessonDocx: vi.fn().mockResolvedValue({ status: "success", artifact: { metadata: { public_url: "/files/lesson.docx" } } }),
  exportLessonPdf: (...args: unknown[]) => exportLessonPdfMock(...args),
  fetchLessonMigrationPreview: (...args: unknown[]) => migrationPreviewMock(...args),
  applyLessonMigration: (...args: unknown[]) => migrationApplyMock(...args),
  fetchLesson: vi.fn().mockResolvedValue({ lesson_id: "lesson_1", title: "人口分布", metadata: {} }),
  importQuestionBanks: vi.fn().mockResolvedValue({ job_id: "j1" }),
  fetchJob: vi.fn().mockResolvedValue({ status: "completed", stages: {} })
}));

const baseDraft = {
  title: "人口分布",
  topic: "人口分布",
  grade: "高一",
  duration_minutes: 40,
  objectives: ["观察人口分布"],
  stages: [{ stage_id: "s1", title: "地图观察", minutes: 10, questions: [{ question_id: "q1", text: "人口集中在哪里？" }] }]
} as LessonPlanProfile;

const session = (overrides: Partial<LessonDesignSession> = {}): LessonDesignSession => ({
  design_id: "design_1",
  project_id: "p1",
  owner_user_id: "u1",
  base_lesson_id: "",
  current_step: "requirements",
  requirements: {},
  draft: { ...baseDraft },
  base_draft: {},
  diff_summary: [],
  section_status: {},
  source_refs: [],
  capability_bindings: [],
  turns: [],
  status: "active",
  revision: 0,
  final_lesson_id: "",
  pending_next_step: "",
  created_at: "",
  updated_at: "",
  plan_items: [],
  active_design_question: "点击单元格即可修改教案。",
  ...overrides
});

const turnResult = (overrides: Partial<LessonDesignTurnResult> = {}): LessonDesignTurnResult => ({
  status: "success",
  assistant_message: "已按要求修改。",
  next_step: "process",
  step_label: "教学过程",
  draft: { ...baseDraft },
  section_status: { stages: "proposed" },
  source_refs: [],
  capability_bindings: [],
  revision: 1,
  suggestions: [],
  plan_items: [],
  retrieval_candidates: [],
  auto_bound_questions: [],
  active_design_question: "",
  ...overrides
});

describe("LessonDesignWorkspace（一页表格式教案）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createMock.mockResolvedValue(session());
    fetchBanksMock.mockResolvedValue({ status: "success", items: [] });
    migrationPreviewMock.mockResolvedValue({ available: false, items: [] });
    resolveMock.mockImplementation(async (_id: string, _section: string, _decision: string, _note: string, revision: number) => ({
      status: "success",
      message: "已保存。",
      design: session({ revision: revision + 1 })
    }));
  });

  afterEach(cleanup);

  it("renders the one-page sheet and saves a scalar cell", async () => {
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    expect(await screen.findByTestId("ldw-sheet")).toBeVisible();
    expect(screen.getByTestId("ldw-process-table")).toBeVisible();
    expect(screen.queryByTestId("ldw-steps")).toBeNull();
    fireEvent.click(screen.getByTestId("ldw-cell-title"));
    fireEvent.change(screen.getByLabelText("课题"), { target: { value: "人口迁移" } });
    fireEvent.click(screen.getByLabelText("保存课题"));
    await waitFor(() => expect(resolveMock).toHaveBeenCalledWith("design_1", "title", "edit", "", 0, "人口迁移"));
  });

  it("saves duration as a number and objectives as lines", async () => {
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-sheet");
    fireEvent.click(screen.getByTestId("ldw-cell-duration"));
    fireEvent.change(screen.getByLabelText("课时"), { target: { value: "45" } });
    fireEvent.click(screen.getByLabelText("保存课时"));
    await waitFor(() => expect(resolveMock).toHaveBeenCalledWith("design_1", "duration_minutes", "edit", "", 0, 45));
    fireEvent.click(screen.getByTestId("ldw-cell-objectives"));
    fireEvent.change(screen.getByLabelText("教学目标"), { target: { value: "观察人口分布\n解释影响因素" } });
    fireEvent.click(screen.getByLabelText("保存教学目标"));
    await waitFor(() =>
      expect(resolveMock).toHaveBeenCalledWith("design_1", "objectives", "edit", "", 1, ["观察人口分布", "解释影响因素"])
    );
  });

  it("edits a stage field in the process table and preserves bound questions", async () => {
    resolveMock.mockResolvedValue({ status: "success", design: session({ revision: 1 }) });
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-sheet");
    fireEvent.click(screen.getByTestId("lpt-stage-title-0"));
    fireEvent.change(screen.getByLabelText("环节1名称"), { target: { value: "地图观察与描述" } });
    fireEvent.click(screen.getByLabelText("保存环节1名称"));
    await waitFor(() => expect(resolveMock).toHaveBeenCalled());
    const savedStages = resolveMock.mock.calls[0][5] as Array<Record<string, unknown>>;
    expect(savedStages[0]).toMatchObject({ stage_id: "s1", title: "地图观察与描述", minutes: 10 });
    expect(savedStages[0].questions).toEqual([{ question_id: "q1", text: "人口集中在哪里？" }]);
  });

  it("confirms the whole sheet via accept_all and finalizes", async () => {
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-sheet");
    fireEvent.click(screen.getByTestId("ldw-accept-all"));
    await waitFor(() => expect(resolveMock).toHaveBeenCalledWith("design_1", "all", "accept", "", 0));
    fireEvent.click(screen.getByTestId("ldw-finalize-button"));
    await waitFor(() => expect(finalizeMock).toHaveBeenCalledWith("design_1", 1));
  });

  it("runs the rehearsal check and shows the report", async () => {
    fetchDesignMock.mockResolvedValue({
      ...session({ revision: 0 }),
      rehearsal_report: { ready: false, errors: ["环节“地图观察”未设置时长。"], warnings: [], total_minutes: 10, duration_minutes: 40 }
    });
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-sheet");
    fireEvent.click(screen.getByTestId("ldw-run-rehearsal"));
    const report = await screen.findByTestId("ldw-rehearsal-report");
    expect(report).toHaveTextContent("未设置时长");
  });

  it("targets AI edits at a stage, shows the diff and adopts it", async () => {
    const beforeStages = [{ stage_id: "s1", title: "地图观察", minutes: 10, questions: [{ question_id: "q1", text: "人口集中在哪里？" }] }];
    const afterDraft = {
      ...baseDraft,
      stages: [{ stage_id: "s1", title: "地图观察", minutes: 10, material: "中国人口密度图", questions: [{ question_id: "q1", text: "人口集中在哪里？" }] }]
    };
    turnMock.mockResolvedValue(turnResult({ draft: afterDraft, revision: 1 }));
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-sheet");
    fireEvent.click(screen.getByRole("button", { name: "让 AI 修改环节1" }));
    expect(screen.getByTestId("ldw-ai-target")).toHaveTextContent("环节1｜活动与素材");
    fireEvent.change(screen.getByLabelText("教案设计对话输入"), { target: { value: "补充材料：中国人口密度图" } });
    fireEvent.click(screen.getByTestId("ldw-send"));
    await waitFor(() => expect(turnMock).toHaveBeenCalledWith("design_1", "补充材料：中国人口密度图", 0, "process"));
    const modal = await screen.findByTestId("ldw-diff-modal");
    expect(modal).toHaveTextContent("材料");
    expect(modal).toHaveTextContent("中国人口密度图");
    fireEvent.click(screen.getByTestId("ldw-diff-adopt"));
    await waitFor(() => expect(resolveMock).toHaveBeenCalledWith("design_1", "stages", "accept", "", 1));
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("discards the AI diff by restoring the previous stages", async () => {
    const afterDraft = {
      ...baseDraft,
      stages: [{ stage_id: "s1", title: "地图观察", minutes: 10, material: "被 AI 添加的材料", questions: [{ question_id: "q1", text: "人口集中在哪里？" }] }]
    };
    turnMock.mockResolvedValue(turnResult({ draft: afterDraft, revision: 1 }));
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-sheet");
    fireEvent.click(screen.getByRole("button", { name: "让 AI 修改环节1" }));
    fireEvent.change(screen.getByLabelText("教案设计对话输入"), { target: { value: "随便加个材料" } });
    fireEvent.click(screen.getByTestId("ldw-send"));
    await screen.findByTestId("ldw-diff-modal");
    fireEvent.click(screen.getByTestId("ldw-diff-discard"));
    await waitFor(() => expect(resolveMock).toHaveBeenCalledWith("design_1", "stages", "edit", "", 1, baseDraft.stages));
  });

  it("shows the migration card for legacy drafts and applies it once", async () => {
    migrationPreviewMock.mockResolvedValue({
      available: true,
      applied: false,
      items: [
        { kind: "question", detail: "人口为何迁移？", position: 0, target_stage_id: "s1", target_stage_title: "地图观察" },
        { kind: "unmappable", detail: "map_2d", target_stage_id: "", target_stage_title: "" }
      ]
    });
    migrationApplyMock.mockResolvedValue({ status: "success", message: "已写入。", design: session({ revision: 1, draft: { ...baseDraft, legacy_migration_applied: true } }) });
    fetchDesignMock.mockResolvedValue(session({
      revision: 0,
      draft: { ...baseDraft, core_questions: { core: "人口为何迁移？", sub_questions: [] } } as LessonPlanProfile
    }));
    render(
      <LessonDesignWorkspace
        projectId="p1"
        onClose={vi.fn()}
        initialDesignId="design_legacy"
      />
    );
    const card = await screen.findByTestId("ldw-migration");
    expect(card).toHaveTextContent("人口为何迁移？");
    expect(card).toHaveTextContent("保留原字段");
    fireEvent.click(screen.getByTestId("ldw-migration-apply"));
    await waitFor(() => expect(migrationApplyMock).toHaveBeenCalledWith("design_1", 0));
    await waitFor(() => expect(screen.queryByTestId("ldw-migration")).toBeNull());
  });

  it("imports a Word lesson into a fresh unconfirmed design and shows the mapping card", async () => {
    importDocxMock.mockResolvedValue({
      status: "success",
      summary: "Word 导入：映射 6 处，待归类文本 1 条。请逐项校对后再确认。",
      design: session({ design_id: "design_import", revision: 0, draft: { ...baseDraft, title: "人口的空间变化" } }),
      mapping: [{ field: "title", label: "课题", content: "人口的空间变化", origin: "inline:课题" }],
      unclassified: [{ kind: "text", heading: "教学过程", text: "多余段落" }]
    });
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-sheet");
    const file = new File(["docx-bytes"], "教案.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
    fireEvent.change(screen.getByLabelText("选择 Word 教案文件"), { target: { files: [file] } });
    await waitFor(() => expect(importDocxMock).toHaveBeenCalledWith("p1", file));
    const card = await screen.findByTestId("ldw-import-card");
    expect(card).toHaveTextContent("人口的空间变化");
    expect(card).toHaveTextContent("多余段落");
  });

  it("exports the draft as Word and PDF", async () => {
    exportDesignDocxMock.mockResolvedValue({ status: "success", artifact: { metadata: { public_url: "/files/draft.docx" } } });
    exportDesignPdfMock.mockResolvedValue({ status: "success", artifact: { metadata: { public_url: "/files/draft.pdf" } } });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-sheet");
    fireEvent.click(screen.getByTestId("ldw-export-docx"));
    await waitFor(() => expect(exportDesignDocxMock).toHaveBeenCalledWith("design_1", "p1"));
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith("/files/draft.docx", "_blank", "noopener,noreferrer"));
    fireEvent.click(screen.getByTestId("ldw-export-pdf"));
    await waitFor(() => expect(exportDesignPdfMock).toHaveBeenCalledWith("design_1", "p1"));
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith("/files/draft.pdf", "_blank", "noopener,noreferrer"));
  });

  it("searches the bank and binds a question to a stage", async () => {
    fetchBanksMock.mockResolvedValue({ status: "success", items: [{ bank_id: "b1", title: "人口题库", question_count: 10, answer_coverage: 0.9, answer_missing: false, image_count: 0 }] });
    searchMock.mockResolvedValue({ status: "success", items: [{ question_id: "q9", number: "T1", stem: "影响人口迁移的因素？", answer_complete: true }] });
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-sheet");
    fireEvent.click(screen.getByText("添加题目"));
    fireEvent.change(screen.getByLabelText("题目检索关键词（地图观察）"), { target: { value: "人口迁移" } });
    fireEvent.click(screen.getByRole("button", { name: "检索" }));
    await screen.findByText(/影响人口迁移的因素？/);
    fireEvent.click(screen.getByRole("button", { name: "选用" }));
    await waitFor(() => expect(bindMock).toHaveBeenCalledWith("design_1", { stage_id: "s1", question_id: "q9", expected_revision: 0 }));
  });

  it("binds a manual question with answer and explanation", async () => {
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-sheet");
    fireEvent.click(screen.getByText("添加题目"));
    fireEvent.click(screen.getByText("录入手动题目"));
    fireEvent.change(screen.getByLabelText("手动题目题干（地图观察）"), { target: { value: "人口分布特点？" } });
    fireEvent.change(screen.getByLabelText("手动题目参考答案（地图观察）"), { target: { value: "东多西少" } });
    fireEvent.change(screen.getByLabelText("手动题目解析（地图观察）"), { target: { value: "胡焕庸线" } });
    fireEvent.click(screen.getByText("加入本环节"));
    await waitFor(() =>
      expect(bindMock).toHaveBeenCalledWith("design_1", {
        stage_id: "s1",
        manual: { text: "人口分布特点？", answer: "东多西少", explanation: "胡焕庸线" },
        expected_revision: 0
      })
    );
  });

  it("toggles preset teaching methods and saves the list", async () => {
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-sheet");
    fireEvent.click(screen.getByRole("button", { name: "教学方法情境教学" }));
    await waitFor(() => expect(resolveMock).toHaveBeenCalledWith("design_1", "methods", "edit", "", 0, ["情境教学"]));
  });

  it("enters rehearsal from the finalized result", async () => {
    createMock.mockResolvedValue(
      session({ status: "finalized", final_lesson_id: "lesson_1", revision: 3, draft: { ...baseDraft, title: "已定稿教案" } })
    );
    const onEnterRehearsal = vi.fn();
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} onEnterRehearsal={onEnterRehearsal} />);
    const button = await screen.findByTestId("ldw-enter-rehearsal");
    fireEvent.click(button);
    await waitFor(() => expect(onEnterRehearsal).toHaveBeenCalledWith(expect.objectContaining({ lesson_id: "lesson_1" })));
  });
});
