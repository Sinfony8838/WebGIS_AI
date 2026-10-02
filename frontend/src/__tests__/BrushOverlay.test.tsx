import { createRef } from "react";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrushOverlay, type BrushOverlayHandle } from "../components/BrushOverlay";
import { BrushHistory } from "../lib/brushHistory";

type CanvasContextMock = CanvasRenderingContext2D & {
  beginPath: ReturnType<typeof vi.fn>;
  clearRect: ReturnType<typeof vi.fn>;
  ellipse: ReturnType<typeof vi.fn>;
  getImageData: ReturnType<typeof vi.fn>;
  lineTo: ReturnType<typeof vi.fn>;
  moveTo: ReturnType<typeof vi.fn>;
  putImageData: ReturnType<typeof vi.fn>;
  restore: ReturnType<typeof vi.fn>;
  save: ReturnType<typeof vi.fn>;
  setTransform: ReturnType<typeof vi.fn>;
  stroke: ReturnType<typeof vi.fn>;
  strokeRect: ReturnType<typeof vi.fn>;
  drawImage: ReturnType<typeof vi.fn>;
};

function makeContext(): CanvasContextMock {
  return {
    beginPath: vi.fn(),
    clearRect: vi.fn(),
    ellipse: vi.fn(),
    getImageData: vi.fn(() => ({ data: new Uint8ClampedArray(0) })),
    lineTo: vi.fn(),
    moveTo: vi.fn(),
    putImageData: vi.fn(),
    restore: vi.fn(),
    save: vi.fn(),
    setTransform: vi.fn(),
    stroke: vi.fn(),
    strokeRect: vi.fn(),
    drawImage: vi.fn()
  } as unknown as CanvasContextMock;
}

class ResizeObserverMock {
  observe = vi.fn();
  disconnect = vi.fn();
}

describe("BrushOverlay", () => {
  let context: CanvasContextMock;

  beforeEach(() => {
    context = makeContext();
    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
    Object.defineProperty(window, "devicePixelRatio", {
      configurable: true,
      value: 2
    });
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      get: () => 400
    });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", {
      configurable: true,
      get: () => 300
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context);
    vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockReturnValue({
      bottom: 320,
      height: 300,
      left: 10,
      right: 410,
      top: 20,
      width: 400,
      x: 10,
      y: 20,
      toJSON: () => ({})
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("draws with CSS-pixel pointer coordinates on high-DPI screens", () => {
    const { container } = render(
      <div>
        <BrushOverlay
          active
          settings={{ tool: "freehand", color: "#ff4444", lineWidth: 4 }}
        />
      </div>
    );

    const canvas = container.querySelector("canvas");
    expect(canvas).toBeTruthy();

    fireEvent.mouseDown(canvas!, { clientX: 110, clientY: 120 });
    fireEvent.mouseMove(canvas!, { clientX: 160, clientY: 170 });

    expect(context.setTransform).toHaveBeenCalledWith(2, 0, 0, 2, 0, 0);
    expect(context.moveTo).toHaveBeenLastCalledWith(100, 100);
    expect(context.lineTo).toHaveBeenLastCalledWith(150, 150);
  });

  it("normalizes pointer coordinates inside a transformed canvas", () => {
    vi.mocked(HTMLCanvasElement.prototype.getBoundingClientRect).mockReturnValue({
      bottom: 170,
      height: 150,
      left: 10,
      right: 210,
      top: 20,
      width: 200,
      x: 10,
      y: 20,
      toJSON: () => ({})
    });

    const { container } = render(
      <div>
        <BrushOverlay
          active
          settings={{ tool: "freehand", color: "#ff4444", lineWidth: 4 }}
        />
      </div>
    );

    const canvas = container.querySelector("canvas");
    expect(canvas).toBeTruthy();

    fireEvent.mouseDown(canvas!, { clientX: 110, clientY: 120 });
    fireEvent.mouseMove(canvas!, { clientX: 160, clientY: 170 });

    expect(context.moveTo).toHaveBeenLastCalledWith(200, 200);
    expect(context.lineTo).toHaveBeenLastCalledWith(300, 300);
  });

  it("forwards wheel gestures while brush mode is active", () => {
    const onWheelZoom = vi.fn();
    const { container, rerender } = render(
      <div>
        <BrushOverlay
          active
          settings={{ tool: "freehand", color: "#ff4444", lineWidth: 4 }}
          onWheelZoom={onWheelZoom}
        />
      </div>
    );

    const canvas = container.querySelector("canvas");
    expect(canvas).toBeTruthy();

    fireEvent.wheel(canvas!, { clientX: 120, clientY: 130, deltaY: -120 });
    expect(onWheelZoom).toHaveBeenCalledTimes(1);
    expect(onWheelZoom.mock.calls[0][0].deltaY).toBe(-120);

    rerender(
      <div>
        <BrushOverlay
          active={false}
          settings={{ tool: "freehand", color: "#ff4444", lineWidth: 4 }}
          onWheelZoom={onWheelZoom}
        />
      </div>
    );
    fireEvent.wheel(canvas!, { clientX: 120, clientY: 130, deltaY: -120 });
    expect(onWheelZoom).toHaveBeenCalledTimes(1);
  });

  it("keeps per-page undo through remount, supports undoing clear and ignores obsolete image loads", () => {
    const images: Array<{ src: string; onload?: () => void }> = [];
    vi.stubGlobal("Image", class {
      src = "";
      onload?: () => void;
      constructor() { images.push(this); }
    });
    const history = new BrushHistory();
    history.commit("page", "A"); history.commit("page", "A+B");
    const ref = createRef<BrushOverlayHandle>();
    const onUndoChange = vi.fn(), onContentChange = vi.fn();
    const props = { active: true, history, pageKey: "page", settings: { tool: "freehand" as const, color: "red", lineWidth: 4 }, onUndoChange, onContentChange };
    const first = render(<BrushOverlay {...props} ref={ref} />);
    expect(ref.current?.exportImage()).toBe("A+B"); // Decoding has not finished.
    act(() => ref.current?.undo());
    expect(history.image("page")).toBe("A");
    const oldPage = images[0], undonePage = images[1];
    context.drawImage.mockClear();
    act(() => oldPage.onload?.());
    expect(context.drawImage).not.toHaveBeenCalled();
    act(() => undonePage.onload?.());
    expect(context.drawImage).toHaveBeenLastCalledWith(undonePage, 0, 0, 400, 300);
    act(() => ref.current?.clear());
    expect(history.image("page")).toBeNull();
    expect(onContentChange).toHaveBeenLastCalledWith(false);
    expect(onUndoChange).toHaveBeenLastCalledWith(true);
    act(() => ref.current?.undo());
    expect(history.image("page")).toBe("A");
    const pending = images.at(-1)!;
    first.unmount();
    context.drawImage.mockClear(); onContentChange.mockClear();
    act(() => pending.onload?.());
    expect(context.drawImage).not.toHaveBeenCalled();
    expect(onContentChange).not.toHaveBeenCalled();
    render(<BrushOverlay {...props} ref={ref} />);
    expect(ref.current?.exportImage()).toBe("A");
    act(() => ref.current?.undo());
    expect(history.image("page")).toBeNull();
  });

  it("does not erase an image with no history and clearing cancels pending restoration", () => {
    const images: Array<{ onload?: () => void }> = [];
    vi.stubGlobal("Image", class { constructor() { images.push(this); } onload?: () => void; });
    const ref = createRef<BrushOverlayHandle>();
    render(<BrushOverlay ref={ref} active settings={{ tool: "freehand", color: "red", lineWidth: 4 }} />);
    act(() => ref.current?.loadImage("imported"));
    context.clearRect.mockClear();
    act(() => ref.current?.undo());
    expect(context.clearRect).not.toHaveBeenCalled();
    expect(ref.current?.exportImage()).toBe("imported");
    act(() => ref.current?.clear());
    context.drawImage.mockClear();
    act(() => images[0].onload?.());
    expect(context.drawImage).not.toHaveBeenCalled();
    expect(ref.current?.exportImage()).toBeNull();
  });
});
