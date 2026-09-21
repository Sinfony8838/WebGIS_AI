import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ScreenshotSelector } from "../components/ScreenshotSelector";

const bounds = { left: 100, top: 50, width: 800, height: 500 };

describe("ScreenshotSelector", () => {
  beforeEach(() => {
    if (!(globalThis as typeof globalThis & { PointerEvent?: typeof MouseEvent }).PointerEvent) {
      (globalThis as typeof globalThis & { PointerEvent?: typeof MouseEvent }).PointerEvent = MouseEvent;
    }
  });

  afterEach(() => cleanup());

  it("locks a page-relative crop selection before saving", () => {
    const onSaveLocal = vi.fn();
    render(<ScreenshotSelector bounds={bounds} onSaveLocal={onSaveLocal} onDestination={vi.fn()} onCancel={vi.fn()} />);
    const selector = screen.getByTestId("screenshot-selector");

    fireEvent.pointerDown(selector, { clientX: 180, clientY: 120, pointerId: 1 });
    fireEvent.pointerMove(selector, { clientX: 480, clientY: 320, pointerId: 1 });
    fireEvent.pointerUp(selector, { clientX: 480, clientY: 320, pointerId: 1 });

    expect(onSaveLocal).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "保存 PNG" }));
    expect(onSaveLocal).toHaveBeenCalledWith({
      left: 80,
      top: 70,
      width: 300,
      height: 200,
      viewportWidth: 800,
      viewportHeight: 500
    });
  });

  it("cancels with Escape and rejects a tiny crop", () => {
    const onCancel = vi.fn();
    render(<ScreenshotSelector bounds={bounds} onSaveLocal={vi.fn()} onDestination={vi.fn()} onCancel={onCancel} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);

    const selector = screen.getByTestId("screenshot-selector");
    fireEvent.pointerDown(selector, { clientX: 120, clientY: 80, pointerId: 2 });
    fireEvent.pointerUp(selector, { clientX: 130, clientY: 90, pointerId: 2 });
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toHaveTextContent("范围过小");
  });
  it("shows the frozen frame and ignores further input while saving", () => {
    const onSaveLocal = vi.fn(), onCancel = vi.fn();
    render(<ScreenshotSelector bounds={bounds} preview="data:image/png;base64,frozen" busy onSaveLocal={onSaveLocal} onDestination={vi.fn()} onCancel={onCancel} />);
    const selector = screen.getByTestId("screenshot-selector");
    expect(selector.style.backgroundImage).toContain("frozen");
    expect(selector).toHaveAttribute("aria-busy", "true");
    fireEvent.pointerDown(selector, {clientX:180,clientY:120,pointerId:1});
    fireEvent.pointerUp(selector, {clientX:480,clientY:320,pointerId:1});
    fireEvent.keyDown(window, {key:"Escape"});
    expect(onSaveLocal).not.toHaveBeenCalled(); expect(onCancel).not.toHaveBeenCalled();
  });

  it("can select and save the whole page without a pointer drag", () => {
    const onSaveLocal = vi.fn();
    render(<ScreenshotSelector bounds={bounds} onSaveLocal={onSaveLocal} onDestination={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", {name:"选择整个页面"}));
    fireEvent.click(screen.getByRole("button", { name: "保存 PNG" }));
    expect(onSaveLocal).toHaveBeenCalledWith({left:0,top:0,width:800,height:500,viewportWidth:800,viewportHeight:500});
  });

  it("supports dragging the locked selection to the assistant", () => {
    const onDestination = vi.fn();
    render(<ScreenshotSelector bounds={bounds} onSaveLocal={vi.fn()} onDestination={onDestination} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", {name:"选择整个页面"}));
    const dataTransfer = {
      setData: vi.fn(),
      getData: vi.fn(() => "selected"),
      effectAllowed: "none"
    };
    fireEvent.dragStart(screen.getByRole("button", {name:"拖动选区到右侧"}), { dataTransfer });
    fireEvent.drop(screen.getByTestId("screenshot-drop-assistant"), { dataTransfer });
    expect(onDestination).toHaveBeenCalledWith("assistant", expect.objectContaining({width:800,height:500}));
  });

});
