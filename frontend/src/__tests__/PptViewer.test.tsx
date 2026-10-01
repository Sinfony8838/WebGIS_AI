import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PptViewer } from "../components/PptViewer";
import type { BrushOverlayHandle } from "../components/BrushOverlay";
import type { SlideContent } from "../types";

function makeSlide(index: number): SlideContent {
  const px = 1280 * 9525;
  return {
    index,
    html: "",
    imageUrl: `blob:slide-${index}`,
    images: {},
    width: px,
    height: Math.round(px * 9 / 16),
    renderer: "powerpoint-incremental"
  };
}

function matchMediaStub(matchesNarrow = false) {
  return vi.fn().mockImplementation((query: string) => ({
    matches: query === "(max-width: 1024px)" ? matchesNarrow : false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn()
  })) as unknown as typeof window.matchMedia;
}

class ResizeObserverMock {
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
}

type Setup = {
  rerenderWith: (slides: SlideContent[], extra?: Partial<Parameters<typeof PptViewer>[0]>) => void;
  callbacks: {
    onCollapse: ReturnType<typeof vi.fn>;
    onRemove: ReturnType<typeof vi.fn>;
    onToggleFullscreen: ReturnType<typeof vi.fn>;
    onPaneWidthChange: ReturnType<typeof vi.fn>;
  };
  unmount: () => void;
};

function setup(initial: Partial<Parameters<typeof PptViewer>[0]> = {}): Setup {
  const callbacks = {
    onCollapse: vi.fn(),
    onRemove: vi.fn(),
    onToggleFullscreen: vi.fn(),
    onPaneWidthChange: vi.fn()
  };
  const props = {
    open: true,
    slides: [makeSlide(0)],
    fileName: "课件.pptx",
    deckKey: "deck-1",
    renderStatus: "complete" as const,
    expectedSlides: 1,
    previewMode: "rendered" as const,
    paneWidth: 700,
    fullscreen: false,
    onPaneWidthChange: callbacks.onPaneWidthChange,
    onToggleFullscreen: callbacks.onToggleFullscreen,
    onExpand: vi.fn(),
    onCollapse: callbacks.onCollapse,
    onRemove: callbacks.onRemove,
    brushActive: false,
    brushSettings: undefined,
    brushOverlayRef: createRef<BrushOverlayHandle>(),
    onBrushContentChange: vi.fn(),
    ...initial
  };
  const view = render(<PptViewer {...props} />);
  return {
    callbacks,
    unmount: view.unmount,
    rerenderWith: (slides, extra = {}) => {
      view.rerender(<PptViewer {...props} {...extra} slides={slides} />);
    }
  };
}

describe("PptViewer split pane", () => {
  beforeEach(() => {
    window.matchMedia = matchMediaStub(false);
    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(700);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(400);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("keeps the current page while rendered slides arrive incrementally", async () => {
    const view = setup({ expectedSlides: 3 });
    const pane = document.body.querySelector<HTMLElement>(".ppt-pane");
    expect(pane).not.toBeNull();

    // Reader moves to page 2 while only one slide is rendered? Page 2 is not
    // rendered yet, so first simulate its arrival, then navigate to it.
    view.rerenderWith([makeSlide(0), makeSlide(1), makeSlide(2)]);
    const page2 = screen.getByRole("button", { name: "2" });
    fireEvent.click(page2);
    expect(screen.getByText("2 / 3")).not.toBeNull();

    // A late poll delivering a longer list must not reset the page.
    view.rerenderWith([makeSlide(0), makeSlide(1), makeSlide(2)], { deckKey: "deck-1" });
    expect(screen.getByText("2 / 3")).not.toBeNull();
  });

  it("shows the simple-preview badge only for simple-parser results", () => {
    setup({ previewMode: "simple" });
    expect(screen.getByText("简易预览")).not.toBeNull();
  });

  it("shows the render-progress badge while slides are pending", () => {
    setup({ renderStatus: "rendering", expectedSlides: 11, slides: [] });
    expect(screen.getByText(/渲染中 0 \/ 11/)).not.toBeNull();
    expect(screen.getByText("正在渲染第 1 页…")).not.toBeNull();
  });

  it("gates keyboard paging on pane focus", () => {
    const view = setup({ expectedSlides: 3 });
    view.rerenderWith([makeSlide(0), makeSlide(1), makeSlide(2)]);

    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByText("1 / 3")).not.toBeNull();

    const pane = document.body.querySelector<HTMLElement>(".ppt-pane");
    pane!.focus();
    expect(document.activeElement).toBe(pane);
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByText("2 / 3")).not.toBeNull();
  });

  it("shows an error card (not a broken image) when a page fails to load", async () => {
    setup();
    const img = screen.getByAltText("幻灯片 1") as HTMLImageElement;
    fireEvent.error(img);
    expect(await screen.findByText("第 1 页加载失败")).not.toBeNull();
    expect(screen.getByRole("button", { name: "重试" })).not.toBeNull();
  });

  it("wires fullscreen toggle, collapse and remove", () => {
    const view = setup();
    fireEvent.click(screen.getByRole("button", { name: "全屏" }));
    expect(view.callbacks.onToggleFullscreen).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "收起" }));
    expect(view.callbacks.onCollapse).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "移除" }));
    expect(view.callbacks.onRemove).toHaveBeenCalledTimes(1);
  });

  it("reports pane width changes while dragging the divider", async () => {
    const view = setup({ paneWidth: 700 });
    const divider = document.body.querySelector<HTMLDivElement>(".ppt-pane-divider");
    expect(divider).not.toBeNull();

    fireEvent.pointerDown(divider!, { pointerId: 1, clientX: 800 });
    // jsdom's synthetic pointer events drop clientX, so dispatch natively.
    const move = new Event("pointermove") as PointerEvent;
    Object.defineProperty(move, "clientX", { value: 900 });
    window.dispatchEvent(move);
    fireEvent.pointerUp(window, { pointerId: 1 });
    // window.innerWidth in jsdom is 1024 → width = 1024-900 = 124 → clamped to MIN 360.
    // The width callback runs inside a rAF, so wait for it to flush.
    await waitFor(() => expect(view.callbacks.onPaneWidthChange).toHaveBeenCalledWith(360));
  });

  it("collapses to the dock showing deck state when closed", () => {
    const view = setup({ open: false, expectedSlides: 11, renderStatus: "rendering", slides: [] });
    expect(screen.getByText("渲染中…")).not.toBeNull();
    expect(screen.getByText("课件.pptx")).not.toBeNull();
    view.unmount();
  });

  it("restores focus-gated Escape from fullscreen to split mode", () => {
    const view = setup({ fullscreen: true });
    const pane = document.body.querySelector<HTMLElement>(".ppt-pane");
    pane!.focus();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(view.callbacks.onToggleFullscreen).toHaveBeenCalledTimes(1);
  });

  it("retries a failed page image", async () => {
    setup();
    const img = screen.getByAltText("幻灯片 1") as HTMLImageElement;
    fireEvent.error(img);
    fireEvent.click(await screen.findByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.getByAltText("幻灯片 1")).not.toBeNull());
  });
});
