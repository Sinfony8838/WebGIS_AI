import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { LessonWorkflowShell } from "../components/LessonWorkflowShell";
import type { ClassSessionRecord, LayersResponse, LessonQuestion, LessonRecord, ProjectRecord } from "../types";

const api = vi.hoisted(() => ({
  fetchLessons: vi.fn(), fetchLesson: vi.fn(), fetchClassSessions: vi.fn(),
  fetchPopulationSources: vi.fn(), fetchPopulationSourceVersions: vi.fn(),
  enterSessionStage: vi.fn(), createClassSession: vi.fn(),
  updateSessionQuestionTimer: vi.fn(), revealSessionQuestion: vi.fn(), closeSessionQuestion: vi.fn()
}));
vi.mock("../api", async () => ({ ...await vi.importActual<typeof import("../api")>("../api"), ...api }));
vi.mock("../components/ReportPanel", () => ({ ReportPanel: () => <div data-testid="report-panel">课堂复盘报告</div> }));

const project = { project_id: "project_projection" } as ProjectRecord;
const question = (): LessonQuestion => ({
  question_id: "question_1", type: "choice", text: "观察人口密度变化后再说明原因", options: ["选项甲", "选项乙"],
  answer: "选项甲", answer_letter: "A", answer_index: 0, explanation: "只能在揭示后出现的答案解析",
  expected_points: [], misconceptions: [], suggested_seconds: 120,
  timer: { status: "running", suggested_seconds: 120, elapsed_seconds: 33, running_since: "2026-10-01T01:00:00Z",
    question_source: "lesson", revealed: false, revealed_at: "", actual_seconds: null, overtime_seconds: 0, reset_count: 0, ai_explanation: null }
});
const lesson = (): LessonRecord => ({
  lesson_id: "lesson_1", title: "人口分布", subject: "地理", grade: "高一", objectives: [], source: "lesson_design",
  metadata: { created_from: "lesson_design", ready_for_class: true }, created_at: "", updated_at: "",
  stages: ["观察", "解释"].map((title, index) => ({
    stage_id: `s${index + 1}`, title, minutes: 5, script: [], questions: [question()], assistant_prompts: ["教师专用AI预案"],
    teacher_guidance: { teacher_talk: "教师专用提示内容" }, knowledge_conclusion: `${title}环节的隐藏结论`,
    scene: { basemap_id: "", templates: [], layer_visibility: {}, view: {}, annotations: [], visual_query: null }
  }))
});
function session(item = lesson(), activeQuestion: Record<string, unknown> = {}): ClassSessionRecord {
  return { session_id: "session_1", project_id: project.project_id, lesson_id: item.lesson_id, status: "running",
    current_stage_id: "s1", join_code: "123456", started_at: "2026-10-01T01:00:00Z", ended_at: "", events: [],
    active_question: activeQuestion, responses: {}, metadata: { lesson_snapshot: item } };
}
function mount(item = lesson(), current: ClassSessionRecord | null = session(item), layerState: LayersResponse | null = null) {
  api.fetchLessons.mockResolvedValue({ items: [item] });
  api.fetchLesson.mockResolvedValue(item);
  api.fetchClassSessions.mockResolvedValue({ items: current ? [current] : [] });
  const onStudentDisplayChange = vi.fn();
  const result = render(<LessonWorkflowShell project={project} layerState={layerState} onRefresh={vi.fn()}
    onStudentDisplayChange={onStudentDisplayChange} />);
  return { ...result, onStudentDisplayChange };
}
beforeEach(() => {
  vi.resetAllMocks();
  window.localStorage.clear();
  api.fetchPopulationSources.mockResolvedValue({ items: [] });
  api.fetchPopulationSourceVersions.mockResolvedValue({ versions: [] });
});
afterEach(() => { cleanup(); window.localStorage.clear(); document.getElementById("teaching-menu-slot")?.remove(); });

describe("classroom student display integration", () => {
  it("puts teaching commands in the header portal and has one bottom navigation", async () => {
    const slot = document.createElement("div");
    slot.id = "teaching-menu-slot";
    document.body.append(slot);
    mount();
    await screen.findByTestId("class-run-panel");
    expect(slot.contains(screen.getByTestId("lesson-design-launcher"))).toBe(true);
    expect(screen.getByTestId("class-run-panel").contains(screen.getByTestId("classroom-teacher-controls"))).toBe(true);
    const bottom = screen.getByTestId("classroom-bottom-navigation");
    expect(within(bottom).queryByText("教案设计")).toBeNull();
    expect(screen.getAllByTestId("class-prev-stage")).toHaveLength(1);
    expect(screen.getAllByTestId("class-next-stage")).toHaveLength(1);
    expect(api.enterSessionStage).not.toHaveBeenCalled();
  });

  it("keeps lesson selection reachable and enforces the rehearsal start gate", async () => {
    const item = lesson();
    item.metadata.ready_for_class = false;
    mount(item, null);
    fireEvent.click(screen.getByTestId("class-mode-toggle"));
    await screen.findByTestId("lesson-select");
    expect(screen.getAllByTestId("start-class")).toHaveLength(1);
    expect((screen.getByTestId("start-class") as HTMLButtonElement).disabled).toBe(true);
    expect(api.createClassSession).not.toHaveBeenCalled();
  });

  it("unmounts teacher notes, preserves the running server timer, and controls reveal externally", async () => {
    const active = question();
    const item = lesson();
    const { onStudentDisplayChange, unmount } = mount(item, session(item, { ...active }));
    await screen.findByTestId("question-practice-modal");
    expect(screen.getByTestId("qpm-clock").textContent).toContain("1:27");
    fireEvent.click(screen.getByTestId("student-display-toggle"));
    await waitFor(() => expect(onStudentDisplayChange).toHaveBeenLastCalledWith(true));
    expect(screen.queryByTestId("class-run-panel")).toBeNull();
    expect(screen.queryByText("教师专用提示内容")).toBeNull();
    expect(screen.queryByTestId("qpm-note-correct")).toBeNull();
    expect(screen.queryByTestId("qpm-reveal")).toBeNull();
    expect(screen.queryByTestId("qpm-answer")).toBeNull();
    expect(screen.queryByTestId("stage-presentation-surface")).toBeNull();
    expect(screen.getByTestId("student-stage-navigation").hasAttribute("open")).toBe(false);
    expect(api.enterSessionStage).not.toHaveBeenCalled();
    expect(api.updateSessionQuestionTimer).not.toHaveBeenCalled();

    api.updateSessionQuestionTimer.mockResolvedValue({ timer: { ...active.timer, status: "paused", elapsed_seconds: 58 } });
    fireEvent.click(screen.getByTestId("teacher-question-timer"));
    await waitFor(() => expect(api.updateSessionQuestionTimer).toHaveBeenCalledWith("session_1", "pause"));
    await waitFor(() => expect(screen.getByTestId("qpm-clock").textContent).toContain("1:02"));
    api.revealSessionQuestion.mockResolvedValue({ timer: { ...active.timer, revealed: true, status: "revealed", actual_seconds: 58 } });
    fireEvent.click(screen.getByTestId("teacher-question-reveal"));
    await screen.findByTestId("qpm-answer");
    expect(api.revealSessionQuestion).toHaveBeenCalledWith("session_1");
    expect(screen.getByText("只能在揭示后出现的答案解析")).toBeTruthy();
    expect(screen.queryByTestId("qpm-note-correct")).toBeNull();
    api.closeSessionQuestion.mockResolvedValue({});
    fireEvent.click(screen.getByTestId("teacher-question-close"));
    await waitFor(() => expect(screen.queryByTestId("question-practice-modal")).toBeNull());
    unmount();
    expect(onStudentDisplayChange).toHaveBeenLastCalledWith(false);
  });

  it("applies the shared font setting and resets the revealed conclusion when leaving and returning to a stage", async () => {
    const item = lesson();
    const current = session(item);
    mount(item, current);
    await screen.findByTestId("class-run-panel");
    fireEvent.click(screen.getByTestId("student-display-toggle"));
    fireEvent.click(screen.getByTestId("class-toggle-presentation"));
    expect(screen.queryByText("结论：观察环节的隐藏结论")).toBeNull();
    fireEvent.change(screen.getByLabelText("展示字号"), { target: { value: "40" } });
    expect(screen.getByTestId("stage-presentation-surface").style.getPropertyValue("--sps-font-size")).toBe("40px");
    fireEvent.click(screen.getByTestId("reveal-stage-conclusions"));
    expect(screen.getByText("结论：观察环节的隐藏结论")).toBeTruthy();
    api.enterSessionStage.mockResolvedValueOnce({ session: { ...current, current_stage_id: "s2" }, scene: {} });
    fireEvent.click(screen.getByTestId("class-next-stage"));
    await waitFor(() => expect(screen.getByTestId("reveal-stage-conclusions").getAttribute("aria-pressed")).toBe("false"));
    expect(screen.queryByText("结论：解释环节的隐藏结论")).toBeNull();
    api.enterSessionStage.mockResolvedValueOnce({ session: current, scene: {} });
    fireEvent.click(screen.getByTestId("class-prev-stage"));
    await waitFor(() => expect(api.enterSessionStage).toHaveBeenLastCalledWith("session_1", "s1"));
    expect(screen.queryByText("结论：观察环节的隐藏结论")).toBeNull();
    expect(api.updateSessionQuestionTimer).not.toHaveBeenCalled();
  });

  it("restores student visibility for the same session without revealing conclusions or mutating the clock", async () => {
    const item = lesson();
    const current = session(item, { ...question() });
    const first = mount(item, current);
    await screen.findByTestId("class-run-panel");
    fireEvent.click(screen.getByTestId("student-display-toggle"));
    fireEvent.click(screen.getByTestId("reveal-stage-conclusions"));
    first.unmount();
    const restored = mount(item, current);
    await screen.findByTestId("student-stage-navigation");
    expect(restored.onStudentDisplayChange).toHaveBeenLastCalledWith(true);
    expect(screen.queryByTestId("class-run-panel")).toBeNull();
    expect(screen.queryByTestId("qpm-note-correct")).toBeNull();
    expect(screen.getByTestId("reveal-stage-conclusions").getAttribute("aria-pressed")).toBe("false");
    expect(api.enterSessionStage).not.toHaveBeenCalled();
    expect(api.updateSessionQuestionTimer).not.toHaveBeenCalled();
    restored.unmount();
    mount(item, { ...current, session_id: "session_2" });
    await screen.findByTestId("class-run-panel");
    expect(screen.getByTestId("student-display-toggle").getAttribute("aria-pressed")).toBe("false");
  });

  it("keeps a teacher-requested population ranking chart visible to students", async () => {
    const item = lesson();
    const layerState = { items: [{ layer_id: "population_top20", name: "人口排名", visible: true,
      data: { type: "FeatureCollection", features: [] },
      metadata: { visualization: { type: "bar", title: "2020 年人口总量 TOP20", maximum: 24870895, unit: "人",
        items: [{ rank: 1, name: "上海市", value: 24870895, unit: "人", share: 1 }] } }
    }] } as unknown as LayersResponse;
    mount(item, session(item), layerState);
    await screen.findByTestId("class-run-panel");
    fireEvent.click(screen.getByTestId("student-display-toggle"));
    expect(screen.queryByTestId("class-run-panel")).toBeNull();
    expect(screen.getByTestId("visual-query-title").textContent).toBe("2020 年人口总量 TOP20");
    expect(screen.getByTestId("visual-query-popup").classList.contains("shifted")).toBe(false);
    expect(screen.getByTestId("visual-query-bars").textContent).toContain("上海市");
  });

  it("clears the foreground ranking popup while a teacher reads the review report", async () => {
    const item = lesson();
    const layerState = { items: [{ layer_id: "population_top20", visible: true, data: { features: [] },
      metadata: { visualization: { type: "bar", title: "人口 TOP20", maximum: 100, unit: "人",
        items: [{ rank: 1, name: "示例市", value: 100, share: 1 }] } }
    }] } as unknown as LayersResponse;
    mount(item, session(item), layerState);
    await screen.findByTestId("class-run-panel");
    expect(screen.getByTestId("visual-query-popup")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "教学复盘", exact: true }));
    await screen.findByTestId("report-panel");
    expect(screen.queryByTestId("visual-query-popup")).toBeNull();
  });
});
