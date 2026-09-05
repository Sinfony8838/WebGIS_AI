import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RehearsalPanel } from "../components/RehearsalPanel";
import type {
  LessonPlanProfile,
  LessonQuestion,
  LessonRecord,
  LessonRehearsalRecord,
  LessonRehearsalReport,
  LessonStage,
  QuestionBankQuestion
} from "../types";

const createRehearsalMock = vi.fn();
const updateMock = vi.fn();
const searchMock = vi.fn();
const reportMock = vi.fn();
const completeMock = vi.fn();
const cancelMock = vi.fn();
const applySceneMock = vi.fn();

vi.mock("../api", () => ({
  createLessonRehearsal: (...args: unknown[]) => createRehearsalMock(...args),
  updateLessonRehearsal: (...args: unknown[]) => updateMock(...args),
  searchQuestionBanks: (...args: unknown[]) => searchMock(...args),
  fetchLessonRehearsalReport: (...args: unknown[]) => reportMock(...args),
  completeLessonRehearsal: (...args: unknown[]) => completeMock(...args),
  cancelLessonRehearsal: (...args: unknown[]) => cancelMock(...args),
  applyRehearsalStageScene: (...args: unknown[]) => applySceneMock(...args),
  fetchLessonRehearsal: vi.fn(),
  listLessonRehearsals: vi.fn(),
  uploadImageLibraryAsset: vi.fn()
}));

const question = (overrides: Partial<LessonQuestion> = {}): LessonQuestion => ({
  question_id: "q1",
  type: "choice",
  text: "影响人口分布的主要自然因素是？",
  options: ["气候和地形", "宗教信仰"],
  answer_index: 0,
  expected_points: [],
  misconceptions: [],
  source: "question_bank",
  number: "5",
  year: "2024",
  answer_complete: true,
  ...overrides
});

const stage = (stageId: string, title: string, minutes: number, questions: LessonQuestion[]): LessonStage => ({
  stage_id: stageId,
  title,
  minutes,
  scene: { basemap_id: "", templates: [], layer_visibility: {}, view: {}, annotations: [] },
  script: [],
  questions,
  assistant_prompts: []
});

const baseLesson = (): LessonRecord => ({
  lesson_id: "lesson_1",
  title: "人口分布",
  subject: "地理",
  grade: "高一",
  objectives: [],
  stages: [],
  source: "lesson_design",
  metadata: { created_from: "lesson_design", lesson_version: 1, ready_for_class: false },
  created_at: "",
  updated_at: ""
});

const workingCopy = (): LessonPlanProfile => ({
  title: "人口分布",
  duration_minutes: 40,
  stages: [
    stage("s1", "情境导入", 12, [question()]),
    stage("s2", "探究活动", 28, [])
  ]
});

const record = (overrides: Partial<LessonRehearsalRecord> = {}): LessonRehearsalRecord => ({
  rehearsal_id: "reh_1",
  project_id: "p1",
  owner_user_id: "u1",
  lesson_id: "lesson_1",
  base_version: 1,
  working_copy: workingCopy(),
  modification_events: [],
  test_results: {},
  revision: 0,
  status: "active",
  committed_version: 0,
  completed_at: "",
  created_at: "",
  updated_at: "",
  ...overrides
});

const bankQuestion = (overrides: Partial<QuestionBankQuestion> = {}): QuestionBankQuestion => ({
  question_id: "qb_9",
  bank_id: "bank_1",
  group_id: "g1",
  group_key: "gk1",
  number: "9",
  type: "choice",
  is_composite: false,
  section_index: 0,
  section_title: "人口分布",
  knowledge_points: [],
  year: "2023",
  region: "浙江",
  source_paper: "",
  material: "",
  stem: "浙江沿海人口稠密的主要自然原因是？",
  task_text: "",
  options: [],
  answer: "B",
  answer_letter: "B",
  answer_index: 1,
  explanation: "沿海地形平坦、气候湿润。",
  sub_questions: [],
  answer_complete: true,
  images: [],
  ...overrides
});

const report = (overrides: Partial<LessonRehearsalReport> = {}): LessonRehearsalReport => ({
  ready: true,
  errors: [],
  warnings: [],
  total_minutes: 40,
  duration_minutes: 40,
  ...overrides
});

const props = {
  projectId: "p1",
  lesson: baseLesson(),
  getSceneSnapshot: vi.fn(() => ({}) as never),
  onApplyGlobeScene: vi.fn(),
  onRefresh: vi.fn(),
  onLessonCommitted: vi.fn(),
  onClose: vi.fn()
};

function renderPanel(overrides: Partial<typeof props> = {}) {
  return render(<RehearsalPanel {...props} {...overrides} />);
}

describe("RehearsalPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createRehearsalMock.mockResolvedValue({ status: "success", rehearsal: record(), resumed: false });
    updateMock.mockResolvedValue({ status: "success", rehearsal: record({ revision: 1 }) });
  });

  afterEach(cleanup);

  it("opens a rehearsal with the simulation marker and working-copy stages", async () => {
    renderPanel();
    expect(await screen.findByTestId("rehearsal-marker")).toBeTruthy();
    expect(createRehearsalMock).toHaveBeenCalledWith("p1", "lesson_1");
    expect(screen.getByText("模拟测试工作台")).toBeTruthy();
    expect(screen.getByText("情境导入")).toBeTruthy();
    expect(screen.getByText("探究活动")).toBeTruthy();
    expect(screen.getByTestId("rehearsal-marker").textContent).toContain("模拟测试");
  });

  it("adjusts a stage's minutes through a staged patch", async () => {
    renderPanel();
    await screen.findByText("情境导入");

    fireEvent.click(screen.getByText("情境导入"));
    fireEvent.click(screen.getAllByText("调整时长")[0]);
    fireEvent.change(screen.getByTestId("rehearsal-minutes-s1"), { target: { value: "15" } });
    fireEvent.click(screen.getByTestId("rehearsal-minutes-save-s1"));

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    const payload = updateMock.mock.calls[0][1];
    expect(payload.expected_revision).toBe(0);
    expect(payload.patch.stages[0].minutes).toBe(15);
    expect(payload.patch.stages[1].minutes).toBe(28);
  });

  it("swaps a stage question with a searched bank question", async () => {
    searchMock.mockResolvedValue({ status: "success", items: [bankQuestion()], candidates_count: 1, generator: "test", query: {} });
    renderPanel();
    await screen.findByText("情境导入");

    fireEvent.click(screen.getByText("情境导入"));
    fireEvent.click(screen.getByTestId("rehearsal-swap-s1-0"));
    fireEvent.change(screen.getByTestId("rehearsal-swap-input"), { target: { value: "人口分布 自然因素" } });
    fireEvent.click(screen.getByTestId("rehearsal-swap-search"));

    const swapButton = await screen.findByTestId("rehearsal-swap-in-qb_9");
    fireEvent.click(swapButton);

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(searchMock).toHaveBeenCalledWith({ project_id: "p1", topic: "人口分布 自然因素", limit: 8 });
    expect(updateMock.mock.calls[0][1].question_bind).toEqual({
      stage_id: "s1",
      question_id: "qb_9",
      position: 0
    });
  });

  it("adds a manual question with answer and explanation", async () => {
    renderPanel();
    await screen.findByText("情境导入");

    fireEvent.click(screen.getByText("情境导入"));
    fireEvent.click(screen.getByText("手动加题"));
    fireEvent.change(screen.getByLabelText("手动题目题干"), { target: { value: "说明胡焕庸线的地理意义。" } });
    fireEvent.change(screen.getByLabelText("手动题目参考答案"), { target: { value: "人口分布分界线。" } });
    fireEvent.change(screen.getByLabelText("手动题目解析"), { target: { value: "两侧密度差异显著。" } });
    fireEvent.click(screen.getByTestId("rehearsal-manual-bind-s1"));

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(updateMock.mock.calls[0][1].question_bind).toEqual({
      stage_id: "s1",
      manual: { text: "说明胡焕庸线的地理意义。", type: "open", answer: "人口分布分界线。", explanation: "两侧密度差异显著。" }
    });
  });

  it("records checklist results and shows the validation report", async () => {
    reportMock.mockResolvedValue({ status: "success", rehearsal_id: "reh_1", revision: 0, report: report() });
    renderPanel();
    await screen.findByTestId("rehearsal-checklist");

    fireEvent.click(screen.getByTestId("rehearsal-test-pass-map_test"));
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(updateMock.mock.calls[0][1].test_result).toEqual({ key: "map_test", passed: true, note: "通过" });

    fireEvent.click(screen.getByTestId("rehearsal-report-button"));
    expect(await screen.findByTestId("rehearsal-report")).toBeTruthy();
    expect(screen.getByTestId("rehearsal-report").textContent).toContain("校验通过");
    expect(screen.getByTestId("rehearsal-report").textContent).toContain("环节合计 40 / 课时 40");
  });

  it("completes the rehearsal and publishes the new lesson version", async () => {
    const published = baseLesson();
    published.metadata = { created_from: "lesson_design", lesson_version: 2, ready_for_class: true };
    completeMock.mockResolvedValue({
      status: "success",
      lesson: published,
      rehearsal: record({ status: "completed", committed_version: 2, revision: 1 }),
      report: report(),
      export: { status: "success", artifact: { metadata: { public_url: "/files/lesson_v2.docx" } } }
    });
    renderPanel();
    await screen.findByTestId("rehearsal-complete-button");

    fireEvent.click(screen.getByTestId("rehearsal-complete-button"));

    expect(await screen.findByTestId("rehearsal-complete")).toBeTruthy();
    expect(completeMock).toHaveBeenCalledWith("reh_1", 0);
    expect(props.onLessonCommitted).toHaveBeenCalledWith(expect.objectContaining({ lesson_id: "lesson_1" }));
    expect(screen.getByTestId("rehearsal-complete").textContent).toContain("v2");
    const link = screen.getByText("下载新版教案 Word") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/files/lesson_v2.docx");
  });

  it("cancels the rehearsal only after confirmation", async () => {
    cancelMock.mockResolvedValue({ status: "success", rehearsal: record({ status: "cancelled" }) });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPanel();
    await screen.findByTestId("rehearsal-cancel");

    fireEvent.click(screen.getByTestId("rehearsal-cancel"));
    expect(cancelMock).not.toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    fireEvent.click(screen.getByTestId("rehearsal-cancel"));
    await waitFor(() => expect(cancelMock).toHaveBeenCalledWith("reh_1"));
    await waitFor(() => expect(props.onClose).toHaveBeenCalled());
    confirmSpy.mockRestore();
  });
});
