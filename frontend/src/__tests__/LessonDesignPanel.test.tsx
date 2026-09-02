import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LessonDesignPanel } from "../components/LessonDesignPanel";
import type { LessonDesignSession } from "../types";

const turnMock = vi.fn();
const resolveMock = vi.fn();
const finalizeMock = vi.fn();
const exportMock = vi.fn();

vi.mock("../api", () => ({
  createLessonDesign: vi.fn().mockResolvedValue({
    design_id: "design_1", project_id: "p1", owner_user_id: "u1",
    base_lesson_id: "", current_step: "requirements", requirements: {},
    draft: { title: "", topic: "", grade: "", objectives: [], stages: [] }, base_draft: {}, diff_summary: [],
    section_status: {}, source_refs: [], capability_bindings: [], turns: [], status: "active", revision: 0, final_lesson_id: "", pending_next_step: ""
  }),
  turnLessonDesign: (...args: unknown[]) => turnMock(...args),
  resolveLessonDesignSection: (...args: unknown[]) => resolveMock(...args),
  finalizeLessonDesign: (...args: unknown[]) => finalizeMock(...args),
  exportLessonDocx: (...args: unknown[]) => exportMock(...args)
}));

const base = (): LessonDesignSession => ({
  status: "active", design_id: "design_1", project_id: "p1", owner_user_id: "u1",
  base_lesson_id: "", current_step: "requirements", requirements: {},
  draft: { title: "", topic: "", grade: "", objectives: [], stages: [] }, base_draft: {}, diff_summary: [],
  section_status: {}, source_refs: [], capability_bindings: [], turns: [], revision: 0,
  final_lesson_id: "", pending_next_step: "", created_at: "", updated_at: ""
});

describe("LessonDesignPanel", () => {
  beforeEach(() => {
    turnMock.mockResolvedValue({
      status: "success", assistant_message: "我理解你的课题。", next_step: "analysis",
      step_label: "课标与学情", draft: { title: "人口分布", topic: "人口分布", grade: "高一", objectives: [], stages: [] },
      section_status: { requirements: "proposed" }, source_refs: [], capability_bindings: [], revision: 1, suggestions: []
    });
    resolveMock.mockResolvedValue({ status: "success", design: { ...base(), revision: 2, current_step: "analysis" } });
    finalizeMock.mockResolvedValue({ status: "success", lesson: { lesson_id: "lesson_1", title: "人口分布" }, design: { ...base(), status: "finalized", final_lesson_id: "lesson_1" }, capability_report: { ready: true } });
    exportMock.mockResolvedValue({ status: "success", artifact: { artifact_id: "a1", metadata: { public_url: "/files/out.docx" } }, job_id: "j1" });
  });

  it("guides one turn and resolves a section", async () => {
    render(<LessonDesignPanel projectId="p1" activeLesson={null} onFinalized={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText("教案共创助手")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText(/告诉我你的修改想法/), { target: { value: "高一、40分钟、人口分布" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(turnMock).toHaveBeenCalled());
    expect(await screen.findByText("我理解你的课题。")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "接受本节" }));
    await waitFor(() => expect(resolveMock).toHaveBeenCalled());
  });
});
