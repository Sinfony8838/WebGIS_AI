import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PresentationLayoutEditor } from "../components/PresentationLayoutEditor";
import { defaultLayoutFromStage } from "../lib/presentationLayout";
import type { LessonStage } from "../types";
import { uploadImageLibraryAsset, uploadVideoAsset } from "../api";

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
  uploadVideoAsset: vi.fn().mockResolvedValue({ status: "success", artifact: { metadata: { public_url: "/files/uploads/p1/video_library/intro.mp4", mime_type: "video/mp4" } } }),
  uploadImageLibraryAsset: vi.fn().mockResolvedValue({ job_id: "j1", artifact: { metadata: { public_url: "/files/uploads/p1/image_library/local.png", mime_type: "image/png" } } })
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
    scene: {},
    ...overrides
  }) as LessonStage;

describe("PresentationLayoutEditor", () => {
  it("raises the selected block above its neighbour and persists the stacking order", () => {
    const onSave = vi.fn();
    const presentation = { blocks: [
      { id: "a", type: "text" as const, text: "A", x: 0, y: 0, w: 0.4, h: 0.2, z: 0, order: 0 },
      { id: "b", type: "text" as const, text: "B", x: 0, y: 0, w: 0.4, h: 0.2, z: 1, order: 1 }
    ] };
    render(<PresentationLayoutEditor stage={stage({ presentation })} projectId="p1" busy={false} libraryAssets={[]} onSave={onSave} />);
    fireEvent.pointerDown(screen.getByTestId("ple-block-a"), { pointerId: 1, clientX: 0, clientY: 0 });
    fireEvent.pointerUp(screen.getByTestId("ple-canvas"));
    fireEvent.click(screen.getByRole("button", { name: "上移层级" }));
    fireEvent.click(screen.getByTestId("ple-save"));
    expect(onSave.mock.calls[0][0].blocks.map((block: { id: string; z: number }) => [block.id, block.z])).toEqual([["b", 0], ["a", 1]]);
  });

  it("inserts video links as videos and charts as charts", async () => {
    const onSave = vi.fn();
    const assets = [{ artifact_id: "a1", title: "图表图", url: "/files/chart.png", mime_type: "image/png" }];
    render(<PresentationLayoutEditor stage={stage()} projectId="p1" busy={false} libraryAssets={assets} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "插入视频区块" }));
    fireEvent.change(screen.getByLabelText("视频 https 链接"), { target: { value: "https://example.com/video.mp4" } });
    fireEvent.click(screen.getByRole("button", { name: "使用链接" }));
    fireEvent.click(screen.getByRole("button", { name: "插入图表区块" }));
    fireEvent.click(screen.getByRole("button", { name: /图表图/ }));
    fireEvent.click(screen.getByTestId("ple-save"));
    const blocks = onSave.mock.calls[0][0].blocks;
    expect(blocks.find((block: { type: string }) => block.type === "video")?.asset.url).toBe("https://example.com/video.mp4");
    expect(blocks.find((block: { type: string }) => block.type === "chart")?.asset.url).toBe("/files/chart.png");
  });

  it("reports a failed video upload and keeps unsaved blocks unchanged", async () => {
    vi.mocked(uploadVideoAsset).mockRejectedValueOnce(new Error("文件超过限制"));
    render(<PresentationLayoutEditor stage={stage()} projectId="p1" busy={false} libraryAssets={[]} onSave={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "插入视频区块" }));
    fireEvent.change(screen.getByLabelText("选择视频文件"), { target: { files: [new File(["bad"], "bad.mp4")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("文件超过限制");
    expect(screen.getByTestId("ple-save")).toBeDisabled();
  });

  it("uploads a local image into the project library and attaches it as a block", async () => {
    const { uploadImageLibraryAsset } = await import("../api");
    const onSave = vi.fn();
    render(<PresentationLayoutEditor stage={stage()} projectId="p1" busy={false} libraryAssets={[]} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "插入图片区块" }));
    fireEvent.click(screen.getByTestId("ple-upload-image"));
    fireEvent.change(screen.getByLabelText("选择本地图片"), { target: { files: [new File(["img"], "local.png", { type: "image/png" })] } });
    await waitFor(() => expect(screen.getByTestId("ple-save")).toBeEnabled());
    fireEvent.click(screen.getByTestId("ple-save"));
    const blocks = onSave.mock.calls[0][0].blocks;
    expect(blocks.some((block: { type: string; asset?: { url?: string } }) => block.type === "image" && block.asset?.url === "/files/uploads/p1/image_library/local.png")).toBe(true);
  });

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
    expect(layout.blocks[0].x).toBeCloseTo(1 - before.w, 5);
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

  it("uploads a local image into the project library and attaches it as a block", async () => {
    const onSave = vi.fn();
    render(<PresentationLayoutEditor stage={stage()} projectId="p1" busy={false} libraryAssets={[]} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "插入图片区块" }));
    fireEvent.click(screen.getByTestId("ple-upload-image"));
    fireEvent.change(screen.getByLabelText("选择本地图片"), { target: { files: [new File(["img"], "local.png", { type: "image/png" })] } });
    await waitFor(() => expect(screen.getByTestId("ple-save")).toBeEnabled());
    fireEvent.click(screen.getByTestId("ple-save"));
    const blocks = onSave.mock.calls[0][0].blocks;
    expect(blocks.some((block: { type: string; asset?: { url?: string } }) => block.type === "image" && block.asset?.url === "/files/uploads/p1/image_library/local.png")).toBe(true);
  });

  it("adopts an external presentation update while the teacher has no unsaved edits", async () => {
    const onSave = vi.fn();
    const initial = stage();
    const { rerender } = render(<PresentationLayoutEditor stage={initial} projectId="p1" busy={false} libraryAssets={[]} onSave={onSave} />);
    const external = stage({
      presentation: { blocks: [{ id: "blk_ext", type: "image", text: "", asset: { url: "/files/ext.png", mime_type: "image/png", name: "ext.png" }, x: 0.3, y: 0.34, w: 0.4, h: 0.3, z: 0, order: 0 }] }
    });
    rerender(<PresentationLayoutEditor stage={external} projectId="p1" busy={false} libraryAssets={[]} onSave={onSave} />);
    await waitFor(() => expect(screen.getByTestId("ple-canvas")).toHaveTextContent("图片"));
    fireEvent.click(screen.getByRole("button", { name: "插入文字区块" }));
    expect(screen.getByTestId("ple-save")).toBeEnabled();
    fireEvent.click(screen.getByTestId("ple-save"));
    const blocks = onSave.mock.calls[0][0].blocks;
    expect(blocks.some((block: { id: string }) => block.id === "blk_ext")).toBe(true);
    expect(blocks.some((block: { type: string }) => block.type === "text")).toBe(true);
  });

  it("keeps unsaved local edits when an external presentation update arrives", async () => {
    const onSave = vi.fn();
    const initial = stage();
    const { rerender } = render(<PresentationLayoutEditor stage={initial} projectId="p1" busy={false} libraryAssets={[]} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "插入文字区块" }));
    const external = stage({
      presentation: { blocks: [{ id: "blk_ext", type: "image", text: "", asset: { url: "/files/ext.png", mime_type: "image/png", name: "ext.png" }, x: 0.3, y: 0.34, w: 0.4, h: 0.3, z: 0, order: 0 }] }
    });
    rerender(<PresentationLayoutEditor stage={external} projectId="p1" busy={false} libraryAssets={[]} onSave={onSave} />);
    expect(screen.getByTestId("ple-save")).toBeEnabled();
    fireEvent.click(screen.getByTestId("ple-save"));
    const blocks = onSave.mock.calls[0][0].blocks;
    expect(blocks.some((block: { id: string }) => block.id === "blk_ext")).toBe(false);
    expect(blocks.some((block: { type: string }) => block.type === "text")).toBe(true);
  });
  it("preserves native video pointer events instead of starting a drag", () => {
    const videoStage = stage({ presentation: { blocks: [{ id: "video-control", type: "video", asset: { url: "https://example.test/clip.webm" }, x: .2, y: .2, w: .5, h: .4, z: 0, order: 0 }] } });
    render(<PresentationLayoutEditor stage={videoStage} projectId="p1" busy={false} libraryAssets={[]} onSave={vi.fn()} />);
    const video = screen.getByTestId("ple-canvas").querySelector("video")!;
    const event = new PointerEvent("pointerdown", { bubbles: true, cancelable: true, clientX: 30, clientY: 30 });
    fireEvent(video, event);
    expect(event.defaultPrevented).toBe(false);
    expect(screen.getByTestId("ple-save")).toBeDisabled();
  });

});
