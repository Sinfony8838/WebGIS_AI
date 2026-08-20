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

  it("returns a map-relative crop selection", () => {
    const onComplete = vi.fn();
    render(<ScreenshotSelector bounds={bounds} onComplete={onComplete} onCancel={vi.fn()} />);
    const selector = screen.getByTestId("screenshot-selector");

    fireEvent.pointerDown(selector, { clientX: 180, clientY: 120, pointerId: 1 });
    fireEvent.pointerMove(selector, { clientX: 480, clientY: 320, pointerId: 1 });
    fireEvent.pointerUp(selector, { clientX: 480, clientY: 320, pointerId: 1 });

    expect(onComplete).toHaveBeenCalledWith({
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
    render(<ScreenshotSelector bounds={bounds} onComplete={vi.fn()} onCancel={onCancel} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);

    const selector = screen.getByTestId("screenshot-selector");
    fireEvent.pointerDown(selector, { clientX: 120, clientY: 80, pointerId: 2 });
    fireEvent.pointerUp(selector, { clientX: 130, clientY: 90, pointerId: 2 });
    expect(onCancel).toHaveBeenCalledTimes(2);
  });
});
