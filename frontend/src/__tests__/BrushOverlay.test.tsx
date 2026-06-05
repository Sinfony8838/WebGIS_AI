import { fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrushOverlay } from "../components/BrushOverlay";

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
    strokeRect: vi.fn()
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
});
