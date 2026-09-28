import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PresentationLayoutEditor } from "../components/PresentationLayoutEditor";
import { defaultLayoutFromStage } from "../lib/presentationLayout";
import type { LessonStage } from "../types";

// jsdom 没有 PointerEvent：退化为普通 Event 会丢 clientX，用 MouseEvent 派生最小实现。
class JsdomPointerEvent extends MouseEvent {
  pointerId: number;
  constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}
if (typeof window.PointerEvent === "undefined") {
  (window as unknown as { PointerEvent: typeof JsdomPointerEvent }).PointerEvent = JsdomPointerEvent;
}

vi.mock("../api", () => ({
  buildAuthenticatedUrl: (path: string) => path,
  uploadVideoAsset: vi.fn().mockResolvedValue({ status: "success", artifact: { metadata: { public_url: "/files/uploads/p1/video_library/intro.mp4", mime_type: "video/mp4" } } })
}));

const stage = (overrides: Partial<LessonStage> = {}): LessonStage =>
  ({
    stage_id: "s1",
    title: "情境导入",
    minutes: 10,
    knowledge_point: "人口分布",
    material: "人口密度图",
    student_activities: ["读图圈画"],
    knowledge_conclusion: "东多西少",
    questions: [{ question_id: "q1", text: "人口集中在哪里？" }],
    script: [],
    assistant_prompts: [],
    scene: {}
  }) as LessonStage;

describe("PresentationLayoutEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(cleanup);

  it("starts from the stored layout or a generated default", () => {
    render(<PresentationLayoutEditor stage={stage()} projectId="p1" busy={false} libraryAssets={[]} onSave={vi.fn()} />);
    expect(screen.getByTestId("ple-canvas")).toHaveTextContent("情境导入");
    expect(screen.getByTestId("ple-canvas")).toHaveTextContent("东多西少");
  });

  it("inserts a text block, edits its text and saves the layout", async () => {
    const onSave = vi.fn();
    render(<PresentationLayoutEditor stage={stage()} projectId="p1" busy={false} libraryAssets={[]} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "插入文字区块" }));
    const inputs = screen.getAllByLabelText(/区块文字（/);
    fireEvent.change(inputs[inputs.length - 1], { target: { value: "新文字块" } });
    fireEvent.click(screen.getByTestId("ple-save"));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const layout = onSave.mock.calls[0][0];
    expect(layout.blocks.some((block: { text?: string }) => block.text === "新文字块")).toBe(true);
  });

  it("drags a block and persists the new normalized position", async () => {
    const onSave = vi.fn();
    render(<PresentationLayoutEditor stage={stage()} projectId="p1" busy={false} libraryAssets={[]} onSave={onSave} />);
    const canvas = screen.getByTestId("ple-canvas");
    const block = canvas.firstElementChild as HTMLElement;
    const before = defaultLayoutFromStage(stage()).blocks[0];
    Object.defineProperty(canvas, "getBoundingClientRect", { value: () => ({ width: 1000, height: 500, left: 0, top: 0, right: 1000, bottom: 500, x: 0, y: 0 }) });
    fireEvent.pointerDown(block, { pointerId: 1, clientX: before.x * 1000, clientY: before.y * 500 });
    fireEvent.pointerMove(canvas, { pointerId: 1, clientX: before.x * 1000 + 200, clientY: before.y * 500 + 50 });
    fireEvent.pointerUp(canvas, { pointerId: 1 });
    fireEvent.click(screen.getByTestId("ple-save"));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const layout = onSave.mock.calls[0][0];
    expect(layout.blocks[0].x).toBeCloseTo(before.x + 0.2, 5);
    expect(layout.blocks[0].y).toBeCloseTo(before.y + 0.1, 5);
  });

  it("attaches a library image and replaces an existing block asset", async () => {
    const onSave = vi.fn();
    const assets = [{ artifact_id: "a1", title: "人口密度图", url: "/files/uploads/p1/image_library/map.png", mime_type: "image/png" }];
    render(<PresentationLayoutEditor stage={stage()} projectId="p1" busy={false} libraryAssets={assets} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "插入图片区块" }));
    fireEvent.click(screen.getByRole("button", { name: /人口密度图/ }));
    fireEvent.click(screen.getByTestId("ple-save"));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const layout = onSave.mock.calls[0][0];
    const imageBlock = layout.blocks.find((block: { type: string; asset?: { url?: string } }) => block.type === "image");
    expect(imageBlock?.asset?.url).toBe("/files/uploads/p1/image_library/map.png");
  });

  it("shows the question picker restricted to stage questions", () => {
    render(<PresentationLayoutEditor stage={stage()} projectId="p1" busy={false} libraryAssets={[]} onSave={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "插入问题区块" }));
    expect(screen.getByRole("button", { name: "人口集中在哪里？" })).toBeVisible();
  });
});
