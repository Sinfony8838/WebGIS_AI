import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StagePresentationSurface } from "../components/StagePresentationSurface";
import { defaultLayoutFromStage } from "../lib/presentationLayout";
import type { LessonStage } from "../types";

vi.mock("../api", () => ({
  buildAuthenticatedUrl: (path: string) => path
}));

const stage = (overrides: Partial<LessonStage> = {}): LessonStage =>
  ({
    stage_id: "s1",
    title: "情境导入",
    minutes: 8,
    knowledge_point: "人口分布",
    material: "人口密度图",
    student_activities: ["读图圈画"],
    knowledge_conclusion: "东多西少",
    questions: [
      {
        question_id: "q1",
        text: "人口集中在哪里？",
        options: ["A. 东南沿海", "B. 西北内陆"],
        answer: "A",
        answer_index: 0,
        explanation: "自然环境优越。"
      }
    ],
    script: [],
    assistant_prompts: [],
    scene: {}
  }) as LessonStage;

describe("StagePresentationSurface", () => {
  afterEach(cleanup);

  it("renders a readable default presentation for stages without a layout", () => {
    render(<StagePresentationSurface stage={stage()} />);
    const surface = screen.getByTestId("stage-presentation-surface");
    expect(surface).toHaveTextContent("情境导入");
    expect(surface).toHaveTextContent("材料：人口密度图");
    expect(surface).not.toHaveTextContent("东多西少");
    fireEvent.click(screen.getByRole("button", { name: "显示本环节结论" }));
    expect(surface).toHaveTextContent("东多西少");
    fireEvent.click(screen.getByRole("button", { name: "收起结论" }));
    expect(surface).not.toHaveTextContent("东多西少");
  });

  it("shows question stems and options but never answers or explanations", () => {
    const stageWithLayout = stage();
    const layout = defaultLayoutFromStage(stageWithLayout);
    stageWithLayout.presentation = layout;
    render(<StagePresentationSurface stage={stageWithLayout} onProjectQuestion={vi.fn()} />);
    expect(screen.getByTestId("sps-question-q1")).toHaveTextContent("人口集中在哪里？");
    expect(screen.getByTestId("sps-question-q1")).toHaveTextContent("A. 东南沿海");
    expect(screen.queryByText("A")).toBeNull();
    expect(screen.queryByText(/自然环境优越/)).toBeNull();
  });

  it("projects a question via the existing reveal flow", () => {
    const onProjectQuestion = vi.fn();
    const stageWithLayout = stage();
    stageWithLayout.presentation = defaultLayoutFromStage(stageWithLayout);
    render(<StagePresentationSurface stage={stageWithLayout} onProjectQuestion={onProjectQuestion} />);
    fireEvent.click(screen.getByRole("button", { name: "投屏答题" }));
    expect(onProjectQuestion).toHaveBeenCalledWith("q1", "s1");
  });

  it("renders a stored layout block and shows a broken-media placeholder", () => {
    const stageWithLayout = stage();
    stageWithLayout.presentation = {
      blocks: [
        { id: "b1", type: "image", asset: { url: "/files/missing.png" }, z: 0, order: 0, x: 0.1, y: 0.1, w: 0.4, h: 0.3 }
      ]
    };
    const { container } = render(<StagePresentationSurface stage={stageWithLayout} />);
    expect(screen.getByTestId("stage-presentation-surface")).toBeInTheDocument();
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    fireEvent.error(img as Element);
    expect(screen.getByText(/素材不可用/)).toBeVisible();
  });
});
