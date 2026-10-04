import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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
    scene: {},
    ...overrides
  }) as LessonStage;

afterEach(cleanup);

describe("StagePresentationSurface", () => {

  it("renders a readable default presentation for stages without a layout", () => {
    const sample = stage();
    const { rerender } = render(<StagePresentationSurface stage={sample} />);
    const surface = screen.getByTestId("stage-presentation-surface");
    expect(surface).toHaveTextContent("情境导入");
    expect(screen.getAllByText("情境导入")).toHaveLength(1);
    expect(screen.getByRole("region", { name: "课堂展示内容" })).toHaveAttribute("tabindex", "0");
    expect(surface).toHaveTextContent("材料：人口密度图");
    expect(surface).not.toHaveTextContent("东多西少");
    expect(screen.queryByRole("button", { name: /结论/ })).toBeNull();
    rerender(<StagePresentationSurface stage={sample} revealConclusions />);
    expect(surface).toHaveTextContent("东多西少");
    rerender(<StagePresentationSurface stage={sample} revealConclusions={false} />);
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

  it("opens the whole long question and final option without mounting its answer", () => {
    const sample = stage();
    sample.questions[0].text = `${"读图比较人口空间分布特征。".repeat(80)}题干末尾标记`;
    sample.questions[0].options = ["选项一", `${"解释这一现象的地理原因。".repeat(35)}最后选项标记`];
    sample.presentation = { blocks: [{ id: "long-question", type: "question", asset: { question_id: "q1" }, x: 0.1, y: 0.1, w: 0.3, h: 0.1, z: 0, order: 0 }] };
    render(<StagePresentationSurface stage={sample} />);
    const opener = screen.getByRole("button", { name: "展开问题 1" });
    fireEvent.click(opener);
    const reader = screen.getByRole("dialog", { name: "问题展开阅读" });
    const content = within(reader).getByRole("region", { name: "完整内容" });
    expect(content).toHaveTextContent("题干末尾标记");
    expect(content).toHaveTextContent("最后选项标记");
    expect(content).not.toHaveTextContent("自然环境优越");
    expect(content).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(reader, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("closes the reader on stage changes and never reuses revealed content", () => {
    const first = stage({ presentation: { blocks: [{ id: "same-id", type: "text", text: "第一环节结论", teacher_reveal: true, x: 0, y: 0, w: 0.8, h: 0.4, z: 0, order: 0 }] } });
    const { rerender } = render(<StagePresentationSurface stage={first} revealConclusions />);
    fireEvent.click(screen.getByRole("button", { name: "展开文字 1" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("第一环节结论");
    rerender(<StagePresentationSurface stage={stage({ stage_id: "s2", title: "新环节" })} revealConclusions={false} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText(/第一环节结论|东多西少/)).toBeNull();
  });

  it("unmounts a revealed conclusion reader when the teacher hides conclusions", () => {
    const sample = stage({ presentation: { blocks: [{ id: "conclusion", type: "text", text: "教师控制的结论", teacher_reveal: true, x: 0, y: 0, w: 0.8, h: 0.4, z: 0, order: 0 }] } });
    const { rerender } = render(<StagePresentationSurface stage={sample} revealConclusions />);
    fireEvent.click(screen.getByRole("button", { name: "展开文字 1" }));
    rerender(<StagePresentationSurface stage={sample} revealConclusions={false} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText("教师控制的结论")).toBeNull();
    rerender(<StagePresentationSurface stage={sample} revealConclusions />);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("教师控制的结论")).toBeInTheDocument();
  });

  it("recovers a broken video after changing its source and never auto plays", () => {
    const videoStage = (url: string) => stage({ presentation: { blocks: [{ id: "video", type: "video", asset: { url, mime_type: "video/mp4" }, x: 0, y: 0, w: 0.8, h: 0.6, z: 0, order: 0 }] } });
    const { container, rerender } = render(<StagePresentationSurface stage={videoStage("/files/broken.mp4")} />);
    const video = container.querySelector("video")!;
    expect(video).toHaveAttribute("controls");
    expect(video).not.toHaveAttribute("autoplay");
    fireEvent.error(video);
    expect(screen.getByText(/素材不可用/)).toBeInTheDocument();
    rerender(<StagePresentationSurface stage={videoStage("/files/new.mp4")} />);
    expect(container.querySelector("video")).toHaveAttribute("src", "/files/new.mp4");
    fireEvent.click(screen.getByRole("button", { name: "展开视频 1" }));
    expect(container.querySelectorAll("video")).toHaveLength(1);
    expect(within(screen.getByRole("dialog")).getByRole("region")).toContainElement(container.querySelector("video"));
  });

  it("preserves question and map navigation from expanded reading", () => {
    const sample = stage({ presentation: { blocks: [{ id: "map", type: "map", x: 0, y: 0, w: 0.8, h: 0.6, z: 0, order: 0 }] } });
    const onPresentScene = vi.fn();
    const { rerender } = render(<StagePresentationSurface stage={sample} onPresentScene={onPresentScene} />);
    fireEvent.click(screen.getByRole("button", { name: "展开地图 1" }));
    fireEvent.click(screen.getByTestId("sps-map-button"));
    expect(onPresentScene).toHaveBeenCalledWith("stage");
    const onProjectQuestion = vi.fn();
    rerender(<StagePresentationSurface stage={stage({ stage_id: "s2" })} onProjectQuestion={onProjectQuestion} />);
    fireEvent.click(screen.getByRole("button", { name: /展开问题/ }));
    fireEvent.click(screen.getByRole("button", { name: "投屏答题" }));
    expect(onProjectQuestion).toHaveBeenCalledWith("q1", "s2");
  });
});

it("supports legacy empty layout objects and includes every classroom question without revealing answers", () => {
  const sample = stage();
  sample.presentation = {} as LessonStage["presentation"];
  sample.questions = [1, 2, 3, 4].map(index => ({ ...sample.questions[0], question_id: `q${index}`, text: `课堂问题${index}` }));
  render(<StagePresentationSurface stage={sample}/>);
  expect(screen.getAllByText("情境导入")).toHaveLength(1);
  for (const index of [1, 2, 3, 4]) expect(screen.getByTestId(`sps-question-q${index}`)).toHaveTextContent(`课堂问题${index}`);
  expect(screen.queryByText(/自然环境优越|东多西少/)).not.toBeInTheDocument();
});

it("removes repeated labels and activities only from the generated classroom display", () => {
  const sample = stage({ knowledge_point: "情境导入", material: "读图圈画", student_activities: ["读图圈画", "讨论比较", "讨论比较"] });
  render(<StagePresentationSurface stage={sample}/>);
  expect(screen.getByRole("region", { name: "课堂展示内容" })).toHaveTextContent("材料：读图圈画");
  expect(screen.getByRole("region", { name: "课堂展示内容" })).toHaveTextContent("活动：讨论比较");
  expect(screen.queryByText(/知识点：情境导入|活动：读图圈画|讨论比较；讨论比较/)).toBeNull();
  expect(sample.student_activities).toEqual(["读图圈画", "讨论比较", "讨论比较"]);
});
