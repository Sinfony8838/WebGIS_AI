import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LessonWorkflowShell } from "../components/LessonWorkflowShell";
import type { ClassSessionRecord, LessonRecord, ProjectRecord } from "../types";

const fetchLessonsMock = vi.fn();
const createDesignMock = vi.fn();
const fetchClassSessionsMock = vi.fn();
const fetchLessonMock = vi.fn();
const launchSessionQuestionMock = vi.fn();
const updateTimerMock = vi.fn();
const revealMock = vi.fn();
const explanationMock = vi.fn();
const closeQuestionMock = vi.fn();
const addObservationMock = vi.fn();

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    createLessonDesign: (...args: unknown[]) => createDesignMock(...args),
    fetchPopulationSources: async () => ({items: []}),
    fetchPopulationSourceVersions: async () => ({items: []}),
    fetchLessons: (...args: unknown[]) => fetchLessonsMock(...args),
    fetchClassSessions: (...args: unknown[]) => fetchClassSessionsMock(...args),
    fetchLesson: (...args: unknown[]) => fetchLessonMock(...args),
    launchSessionQuestion: (...args: unknown[]) => launchSessionQuestionMock(...args),
    updateSessionQuestionTimer: (...args: unknown[]) => updateTimerMock(...args),
    revealSessionQuestion: (...args: unknown[]) => revealMock(...args),
    fetchQuestionExplanation: (...args: unknown[]) => explanationMock(...args),
    closeSessionQuestion: (...args: unknown[]) => closeQuestionMock(...args),
    addSessionObservation: (...args: unknown[]) => addObservationMock(...args)
  };
});

function makeLesson(): LessonRecord {
  return {
    lesson_id: "lesson_1",
    title: "人口分布",
    subject: "地理",
    grade: "高一",
    objectives: [],
    source: "lesson_design",
    metadata: { created_from: "lesson_design", lesson_version: 2, ready_for_class: true },
    created_at: "",
    updated_at: "",
    stages: [
      {
        stage_id: "s1",
        title: "读图探究",
        minutes: 10,
        scene: {
          basemap_id: "",
          templates: [],
          layer_visibility: {},
          view: {},
          annotations: [],
          visual_query: null
        },
        script: [],
        questions: [
          {
            question_id: "qb_1",
            type: "choice",
            source: "question_bank",
            text: "影响人口分布的主要自然因素是？",
            options: ["气候和地形", "宗教信仰"],
            answer: "气候和地形",
            answer_letter: "A",
            answer_index: 0,
            explanation: "中低纬度沿海平原气候适宜、地形平坦。",
            knowledge_points: ["人口分布"],
            answer_complete: true,
            suggested_seconds: 120,
            expected_points: [],
            misconceptions: []
          }
        ],
        assistant_prompts: []
      }
    ]
  };
}

function makeSession(activeQuestion: Record<string, unknown>): ClassSessionRecord {
  return {
    session_id: "session_1",
    lesson_id: "lesson_1",
    project_id: "project_1",
    status: "running",
    join_code: "123456",
    current_stage_id: "s1",
    started_at: "2026-09-05T01:00:00+00:00",
    ended_at: "",
    events: [],
    active_question: activeQuestion,
    responses: {},
    metadata: {}
  };
}

const projectedQuestion = (): Record<string, unknown> => ({
  question_id: "qb_1",
  type: "choice",
  source: "question_bank",
  text: "影响人口分布的主要自然因素是？",
  options: ["气候和地形", "宗教信仰"],
  answer: "气候和地形",
  answer_letter: "A",
  answer_index: 0,
  explanation: "中低纬度沿海平原气候适宜、地形平坦。",
  knowledge_points: ["人口分布"],
  answer_complete: true,
  suggested_seconds: 120,
  stage_id: "s1",
  launched_at: "2026-09-05T01:05:00+00:00",
  delivery: "student",
  timer: {
    status: "idle",
    suggested_seconds: 120,
    elapsed_seconds: 0,
    running_since: "",
    question_source: "question_bank",
    revealed: false,
    revealed_at: "",
    actual_seconds: null,
    overtime_seconds: 0,
    reset_count: 0,
    ai_explanation: null
  }
});

const project = { project_id: "project_1", title: "演示项目" } as unknown as ProjectRecord;

function renderShell(session: ClassSessionRecord) {
  fetchLessonsMock.mockResolvedValue({ items: [makeLesson()] });
  fetchLessonMock.mockResolvedValue(makeLesson());
  fetchClassSessionsMock.mockResolvedValue({ items: [session] });
  return render(
    <LessonWorkflowShell
      project={project}
      layerState={null}
      onRefresh={vi.fn().mockResolvedValue(undefined)}
    />
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("LessonWorkflowShell question projection", () => {
  it("restores an in-flight projection after refresh and drives timer/reveal/observe/close", async () => {
    renderShell(makeSession(projectedQuestion()));

    // 刷新后：进行中的投屏题自动恢复为全屏弹窗（服务端计时状态）。
    await waitFor(() => expect(screen.getByTestId("question-practice-modal")).toBeTruthy());
    expect(screen.getByTestId("qpm-clock").textContent).toContain("2:00");

    // 开始计时 → 服务端状态机推进 → 暂停按钮出现。
    updateTimerMock.mockResolvedValue({
      status: "success",
      server_now: "2026-09-05T01:06:00+00:00",
      timer: { ...(projectedQuestion().timer as Record<string, unknown>), status: "running", elapsed_seconds: 5, running_since: "2026-09-05T01:05:55+00:00" }
    });
    fireEvent.click(screen.getByTestId("qpm-start"));
    await waitFor(() => expect(updateTimerMock).toHaveBeenCalledWith("session_1", "start"));
    await waitFor(() => expect(screen.getByTestId("qpm-pause")).toBeTruthy());

    // 提前查看答案：服务端记录用时并返回官方答案 + AI 讲解。
    revealMock.mockResolvedValue({
      status: "success",
      server_now: "2026-09-05T01:07:00+00:00",
      timer: {
        ...(projectedQuestion().timer as Record<string, unknown>),
        status: "revealed",
        revealed: true,
        actual_seconds: 65,
        overtime_seconds: 0,
        ai_explanation: { text: "【讲解要点】官方答案：气候和地形", generator: "rules" }
      },
      official: {},
      ai_explanation: { text: "【讲解要点】官方答案：气候和地形", generator: "rules" }
    });
    fireEvent.click(screen.getByTestId("qpm-reveal"));
    await waitFor(() => expect(revealMock).toHaveBeenCalledWith("session_1"));
    await waitFor(() => expect(screen.getByTestId("qpm-answer").textContent).toContain("A. 气候和地形"));
    expect(screen.getByTestId("qpm-ai").textContent).toContain("官方答案：气候和地形");

    // 揭示后快速记录学情。
    fireEvent.click(screen.getByTestId("qpm-note-correct"));
    await waitFor(() =>
      expect(addObservationMock).toHaveBeenCalledWith("session_1", expect.objectContaining({ verdict: "correct", question_id: "qb_1" }))
    );

    // 收题关闭：未揭示状态已由服务端记录，前端清除活跃题并卸载弹窗。
    closeQuestionMock.mockResolvedValue({ status: "success" });
    fireEvent.click(screen.getByTestId("qpm-close-footer"));
    await waitFor(() => expect(closeQuestionMock).toHaveBeenCalledWith("session_1"));
    await waitFor(() => expect(screen.queryByTestId("question-practice-modal")).toBeNull());
  });

  it("launches a projection from the class run panel and opens the modal", async () => {
    renderShell(makeSession({}));

    await waitFor(() => expect(screen.getByTestId("class-run-panel")).toBeTruthy());
    expect(screen.queryByTestId("question-practice-modal")).toBeNull();

    launchSessionQuestionMock.mockResolvedValue({
      status: "success",
      active_question: projectedQuestion()
    });
    fireEvent.click(screen.getByTestId("project-toggle-qb_1"));
    await waitFor(() =>
      expect(launchSessionQuestionMock).toHaveBeenCalledWith("session_1", {
        question_id: "qb_1",
        stage_id: "s1",
        delivery: "student"
      })
    );
    await waitFor(() => expect(screen.getByTestId("question-practice-modal")).toBeTruthy());
    // 投屏启动时题目事件只带题面字段（投屏弹窗中的答案区块在揭示前不渲染）。
    expect(screen.queryByTestId("qpm-answer")).toBeNull();
  });
});

describe("LessonWorkflowShell classroom mini window", () => {
  it("moves the projected question between the fullscreen modal and the mini window", async () => {
    renderShell(makeSession(projectedQuestion()));
    await waitFor(() => expect(screen.getByTestId("qpm-minimize")).toBeTruthy());

    // 全屏 → 小窗：同一道题出现在小窗里，计时控件齐全，服务端计时照常工作。
    fireEvent.click(screen.getByTestId("qpm-minimize"));
    expect(screen.getByTestId("class-mini-window")).toBeTruthy();
    expect(screen.getByTestId("qpm-expand")).toBeTruthy();
    expect(screen.getByTestId("qpm-clock").textContent).toContain("2:00");
    updateTimerMock.mockResolvedValue({
      status: "success",
      server_now: "2026-09-05T01:06:00+00:00",
      timer: { ...(projectedQuestion().timer as Record<string, unknown>), status: "running", elapsed_seconds: 5, running_since: "2026-09-05T01:05:55+00:00" }
    });
    fireEvent.click(screen.getByTestId("qpm-start"));
    await waitFor(() => expect(updateTimerMock).toHaveBeenCalledWith("session_1", "start"));
    await waitFor(() => expect(screen.getByTestId("qpm-pause")).toBeTruthy());

    // 小窗 → 大屏：回到全屏投屏；小窗保持打开（口头提问区仍在）。
    fireEvent.click(screen.getByTestId("qpm-expand"));
    await waitFor(() => expect(screen.getByTestId("qpm-minimize")).toBeTruthy());
    expect(screen.getByTestId("class-mini-window")).toBeTruthy();
    expect(screen.getByTestId("mini-oral")).toBeTruthy();
  });

  it("collapses to a tab while a projection question is in flight and reopens", async () => {
    renderShell(makeSession(projectedQuestion()));
    await waitFor(() => expect(screen.getByTestId("qpm-minimize")).toBeTruthy());
    fireEvent.click(screen.getByTestId("qpm-minimize"));
    expect(screen.getByTestId("class-mini-window")).toBeTruthy();

    fireEvent.click(screen.getByTestId("class-mini-window-close"));
    const tab = screen.getByTestId("class-mini-window-tab");
    expect(tab.textContent).toContain("投屏题进行中");
    fireEvent.click(tab);
    await waitFor(() => expect(screen.getByTestId("class-mini-window")).toBeTruthy());
  });

  it("queues ad-hoc oral questions with 1-2-3 switching in the mini window", async () => {
    renderShell(makeSession({}));
    await waitFor(() => expect(screen.getByTestId("class-run-panel")).toBeTruthy());

    launchSessionQuestionMock.mockResolvedValueOnce({
      status: "success",
      active_question: {},
      presented_question: { question_id: "adhoc_a", text: "第一问：胡焕庸线两侧差异？", options: ["东部密", "西部疏"] }
    });
    fireEvent.change(screen.getAllByPlaceholderText("写下想追问学生的话…")[0], {
      target: { value: "第一问：胡焕庸线两侧差异？" }
    });
    fireEvent.click(screen.getByTestId("launch-adhoc"));
    await waitFor(() =>
      expect(launchSessionQuestionMock).toHaveBeenCalledWith("session_1", expect.objectContaining({
        delivery: "teacher_oral",
        adhoc: { text: "第一问：胡焕庸线两侧差异？", options: [] }
      }))
    );
    // 记录并提问后小窗自动打开，当前题即第 1 问。
    await waitFor(() => expect(screen.getByTestId("class-mini-window")).toBeTruthy());
    expect(screen.getByTestId("mini-oral-question").textContent).toContain("第一问");

    launchSessionQuestionMock.mockResolvedValueOnce({
      status: "success",
      active_question: {},
      presented_question: { question_id: "adhoc_b", text: "第二问：影响因素有哪些？", options: [] }
    });
    const inputs = screen.getAllByPlaceholderText("写下想追问学生的话…");
    fireEvent.change(inputs[inputs.length - 1], { target: { value: "第二问：影响因素有哪些？" } });
    fireEvent.click(screen.getByTestId("launch-adhoc-mini"));
    await waitFor(() => expect(screen.getByTestId("oral-queue-2")).toBeTruthy());
    expect(screen.getByTestId("mini-oral-question").textContent).toContain("第二问");

    fireEvent.click(screen.getByTestId("oral-queue-1"));
    expect(screen.getByTestId("mini-oral-question").textContent).toContain("第一问");
    expect(screen.getByTestId("mini-oral-question").textContent).toContain("东部密");
  });

  it("opens the mini window from the class run panel for oral-only use", async () => {
    renderShell(makeSession({}));
    await waitFor(() => expect(screen.getByTestId("class-run-panel")).toBeTruthy());

    fireEvent.click(screen.getByTestId("open-class-mini-window"));
    expect(screen.getByTestId("class-mini-window")).toBeTruthy();
    expect(screen.getByTestId("mini-oral")).toBeTruthy();
    expect(screen.queryByTestId("qpm-clock")).toBeNull();
  });

  it("renders ✍ practice icons from the stage kind in the stage navigation", async () => {
    const lesson = makeLesson();
    lesson.stages = [
      { ...lesson.stages[0], kind: "practice" as const },
      { ...lesson.stages[0], stage_id: "s2", kind: "question" as const, questions: [] }
    ];
    fetchLessonsMock.mockResolvedValue({ items: [lesson] });
    fetchLessonMock.mockResolvedValue(lesson);
    fetchClassSessionsMock.mockResolvedValue({ items: [makeSession({})] });
    render(<LessonWorkflowShell project={project} layerState={null} onRefresh={vi.fn()} />);

    await waitFor(() => expect(screen.getByTestId("stage-chip-s1")).toBeTruthy());
    expect(screen.getByTestId("stage-chip-s1").textContent).toContain("✍");
    expect(screen.getByTestId("stage-chip-s2").textContent).toContain("？");
  });
});

it("adopts completed commentary after reveal without blocking classroom controls", async () => {
  const q=projectedQuestion();
  const pending={...(q.timer as object),status:"revealed",revealed:true,ai_explanation_status:"pending",ai_request_id:"request-a"};
  explanationMock.mockResolvedValue({question_id:"qb_1",timer:{...pending,ai_explanation_status:"ready",ai_explanation:{text:"上海人口材料补充讲解",generator:"minimax"}}});
  renderShell(makeSession({...q,timer:pending}));
  await waitFor(()=>expect(screen.getByTestId("qpm-answer")).toBeTruthy());
  expect(screen.getByTestId("qpm-close")).not.toBeDisabled();
  await waitFor(()=>expect(screen.getByText("上海人口材料补充讲解")).toBeTruthy(),{timeout:2000});
  expect(explanationMock).toHaveBeenCalledWith("session_1");
});

it("ignores a commentary response arriving after the teacher closes the question", async () => {
  const q=projectedQuestion();
  const pending={...(q.timer as object),status:"revealed",revealed:true,ai_explanation_status:"pending",ai_request_id:"request-b"};
  let resolve!: (value: unknown) => void;
  explanationMock.mockReturnValue(new Promise(done=>{resolve=done;}));
  closeQuestionMock.mockResolvedValue({status:"success"});
  renderShell(makeSession({...q,timer:pending}));
  await waitFor(()=>expect(explanationMock).toHaveBeenCalled(),{timeout:2000});
  fireEvent.click(screen.getByTestId("qpm-close"));
  await waitFor(()=>expect(screen.queryByTestId("question-practice-modal")).toBeNull());
  await act(async()=>resolve({question_id:"qb_1",timer:{...pending,ai_explanation_status:"ready",ai_explanation:{text:"迟到结果",generator:"minimax"}}}));
  expect(screen.queryByText("迟到结果")).toBeNull();
  expect(screen.queryByTestId("question-practice-modal")).toBeNull();
});


it("opens a separate co-design session seeded by the selected built-in lesson", async () => {
  const lesson={...makeLesson(), source:"builtin"};
  fetchLessonsMock.mockResolvedValue({items:[lesson]});
  fetchLessonMock.mockResolvedValue(lesson);
  fetchClassSessionsMock.mockResolvedValue({items:[]});
  createDesignMock.mockResolvedValue({design_id:"design_shanghai"});
  const openDesign=vi.fn();
  render(<LessonWorkflowShell project={project} layerState={null} onRefresh={vi.fn()} onOpenDesignWorkspace={openDesign}/>);
  fireEvent.click(screen.getByTestId("class-mode-toggle"));
  await waitFor(() => expect(screen.getByTestId("design-from-lesson")).toBeEnabled());
  fireEvent.click(screen.getByTestId("design-from-lesson"));
  await waitFor(() => expect(openDesign).toHaveBeenCalledWith("design_shanghai"));
  expect(createDesignMock).toHaveBeenCalledWith("project_1", "lesson_1");
  expect(screen.queryByTestId("lesson-panel")).toBeNull();
});
