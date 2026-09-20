import { afterEach, describe, expect, it, vi } from "vitest";

const { html2canvasMock } = vi.hoisted(() => ({ html2canvasMock: vi.fn() }));
vi.mock("html2canvas", () => ({ default: html2canvasMock }));

import { captureWorkspaceSnapshot } from "../workspaceScreenshot";

describe("captureWorkspaceSnapshot", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
    Object.defineProperty(window, "devicePixelRatio", { configurable: true, value: 1 });
  });

  it("captures the visible workspace and replaces the cloned map with the frozen map image", async () => {
    const root = document.createElement("div");
    root.style.backgroundColor = "rgb(7, 17, 31)";
    root.innerHTML = `
      <div data-testid="map-canvas"><canvas></canvas></div>
      <button data-testid="toolbar-screenshot" disabled>截取中…</button>
    `;
    document.body.append(root);
    vi.spyOn(root, "getBoundingClientRect").mockReturnValue({
      left: 0, top: 0, right: 1200, bottom: 800, width: 1200, height: 800, x: 0, y: 0,
      toJSON: () => ({})
    });
    Object.defineProperty(window, "devicePixelRatio", { configurable: true, value: 3 });

    html2canvasMock.mockImplementation(async (_root: HTMLElement, options: { onclone?: (document: Document) => void }) => {
      options.onclone?.(document);
      expect(document.querySelector('[data-testid="map-canvas"] img')).toHaveAttribute("src", "data:image/png;base64,iVBORw0KGgo=");
      expect(document.querySelector('[data-testid="toolbar-screenshot"]')).toHaveTextContent("截图");
      expect(document.querySelector<HTMLButtonElement>('[data-testid="toolbar-screenshot"]')).not.toBeDisabled();
      return { toDataURL: () => "data:image/png;base64,workspace" } as HTMLCanvasElement;
    });

    await expect(captureWorkspaceSnapshot({ root, mapImageDataUrl: "data:image/png;base64,iVBORw0KGgo=", target: "plane" }))
      .resolves.toBe("data:image/png;base64,workspace");
    expect(html2canvasMock).toHaveBeenCalledWith(root, expect.objectContaining({ scale: 2, width: 1200, height: 800, useCORS: true }));
  });

  it("rejects a missing frozen map image", async () => {
    const root = document.createElement("div");
    await expect(captureWorkspaceSnapshot({ root, mapImageDataUrl: "", target: "globe" }))
      .rejects.toThrow("地图画面尚未准备好");
    expect(html2canvasMock).not.toHaveBeenCalled();
  });
});
