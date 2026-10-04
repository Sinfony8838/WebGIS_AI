import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PptViewer } from "../components/PptViewer";
import type { SlideContent } from "../types";

const slides = [1, 2, 3].map(index => ({ width: 9144000, height: 5143500, html: `<p>第${index}页</p>` })) as SlideContent[];
const base = { open: true, fileName: "课堂.pptx", slides, onExpand: vi.fn(), onCollapse: vi.fn(), onRemove: vi.fn() };

describe("PptViewer keyboard ownership", () => {
  beforeEach(() => vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} }));
  afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });

  it("uses the first Escape only to end drawing, ignores key-repeat and collapses on a second press", () => {
    const onExitBrush = vi.fn();
    function Harness() {
      const [brushActive, setBrushActive] = useState(true);
      return <PptViewer {...base} brushActive={brushActive} onExitBrush={() => { onExitBrush(); setBrushActive(false); }} />;
    }
    render(<Harness />);
    const first = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    fireEvent(window, first);
    expect(first.defaultPrevented).toBe(true);
    expect(onExitBrush).toHaveBeenCalledTimes(1);
    expect(base.onCollapse).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape", repeat: true });
    expect(base.onCollapse).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(base.onCollapse).toHaveBeenCalledTimes(1);
  });

  it("does not collapse a drawing deck when an older owner handles brush exit globally", () => {
    render(<PptViewer {...base} brushActive />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(base.onCollapse).not.toHaveBeenCalled();
  });

  it("leaves typing and contenteditable descendants in control of their keys", () => {
    render(<><input aria-label="标题" /><textarea aria-label="提示" /><select aria-label="字号"><option>大</option></select>
      <div contentEditable suppressContentEditableWarning><span data-testid="editor-text">编辑正文</span></div>
      <PptViewer {...base} /></>);
    for (const target of [screen.getByLabelText("标题"), screen.getByLabelText("提示"), screen.getByLabelText("字号"), screen.getByTestId("editor-text")]) {
      for (const key of ["ArrowRight", "ArrowLeft", "Home", "End", " ", "Escape"]) {
        fireEvent.keyDown(target, { key });
      }
    }
    expect(screen.getByText("第1页")).toBeInTheDocument();
    expect(base.onCollapse).not.toHaveBeenCalled();
  });

  it("does not hijack buttons, media controls, composition or modified shortcuts", () => {
    render(<><button type="button">画笔设置</button><video data-testid="video" controls /><PptViewer {...base} /></>);
    for (const target of [screen.getByRole("button", { name: "画笔设置" }), screen.getByTestId("video")]) {
      fireEvent.keyDown(target, { key: " " });
      fireEvent.keyDown(target, { key: "ArrowRight" });
      fireEvent.keyDown(target, { key: "End" });
    }
    fireEvent.keyDown(window, { key: "ArrowRight", isComposing: true });
    fireEvent.keyDown(window, { key: "ArrowRight", ctrlKey: true });
    fireEvent.keyDown(window, { key: "End", altKey: true });
    expect(screen.getByText("第1页")).toBeInTheDocument();
  });

  it("still navigates from the canvas and respects a previously handled event", () => {
    render(<PptViewer {...base} />);
    const handled = new KeyboardEvent("keydown", { key: "ArrowRight", cancelable: true });
    handled.preventDefault();
    fireEvent(window, handled);
    expect(screen.getByText("第1页")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByText("第2页")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "End" });
    expect(screen.getByText("第3页")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(screen.getByText("第2页")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Home" });
    expect(screen.getByText("第1页")).toBeInTheDocument();
  });

  it("returns keyboard focus to the drawing surface after a toolbar interaction", () => {
    const { container } = render(<><button type="button">画笔把手</button><PptViewer {...base} /></>);
    screen.getByRole("button", { name: "画笔把手" }).focus();
    fireEvent.pointerDown(screen.getByText("第1页"));
    const stage = container.querySelector(".ppt-viewer-stage")!;
    expect(document.activeElement).toBe(stage);
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(screen.getByText("第2页")).toBeInTheDocument();
  });

  it("does not take focus from an interactive control inside the slide", () => {
    render(<PptViewer {...base} slides={[{ ...slides[0], html: '<input aria-label="页内输入" />' }]} />);
    const input = screen.getByLabelText("页内输入");
    input.focus();
    fireEvent.pointerDown(input);
    expect(document.activeElement).toBe(input);
  });

  it("opens beside the map, resizes without paging, and restores the map on collapse", () => {
    const onSplitWidthChange = vi.fn();
    const view = render(<PptViewer {...base} onSplitWidthChange={onSplitWidthChange} />);
    expect(screen.getByRole("region", { name: "PPT 放映" })).toHaveClass("ppt-viewer-split");
    expect(onSplitWidthChange).toHaveBeenLastCalledWith(46);
    fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowLeft" });
    expect(onSplitWidthChange).toHaveBeenLastCalledWith(48);
    expect(screen.getByText("第1页")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全屏", exact: true }));
    expect(onSplitWidthChange).toHaveBeenLastCalledWith(null);
    fireEvent.click(screen.getByRole("button", { name: "地图同屏" }));
    expect(onSplitWidthChange).toHaveBeenLastCalledWith(48);
    view.rerender(<PptViewer {...base} open={false} onSplitWidthChange={onSplitWidthChange} />);
    expect(onSplitWidthChange).toHaveBeenLastCalledWith(null);
  });

  it("keeps the rendering source visible and reports image failures", () => {
    render(<PptViewer {...base} slides={[{ ...slides[0], imageUrl: "/slide.png", renderer: "powerpoint-pywin32" }]} />);
    expect(screen.getByRole("status")).toHaveTextContent("PowerPoint 原版渲染");
    fireEvent.error(screen.getByRole("img", { name: "幻灯片 1" }));
    expect(screen.getByRole("alert")).toHaveTextContent("图像加载失败");
  });
});
