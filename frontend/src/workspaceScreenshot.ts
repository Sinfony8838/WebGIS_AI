import html2canvas from "html2canvas";

export type WorkspaceCaptureTarget = "plane" | "globe";

type CaptureOptions = {
  root: HTMLElement;
  mapImageDataUrl: string;
  target: WorkspaceCaptureTarget;
};

function prepareClonedWorkspace(clonedDocument: Document, target: WorkspaceCaptureTarget, imageDataUrl: string): void {
  const selector = target === "globe" ? '[data-testid="map-3d-globe"]' : '[data-testid="map-canvas"]';
  const container = clonedDocument.querySelector<HTMLElement>(selector);
  if (container) {
    const image = clonedDocument.createElement("img");
    image.src = imageDataUrl;
    image.alt = "";
    image.setAttribute("aria-hidden", "true");
    image.style.position = "absolute";
    image.style.inset = "0";
    image.style.width = "100%";
    image.style.height = "100%";
    image.style.objectFit = "fill";
    image.style.pointerEvents = "none";
    container.replaceChildren(image);
  }
  const screenshotButton = clonedDocument.querySelector<HTMLButtonElement>('[data-testid="toolbar-screenshot"]');
  if (screenshotButton) {
    screenshotButton.textContent = "截图";
    screenshotButton.disabled = false;
  }
}

export async function captureWorkspaceSnapshot({ root, mapImageDataUrl, target }: CaptureOptions): Promise<string> {
  if (!mapImageDataUrl.startsWith("data:image/")) throw new Error("地图画面尚未准备好，请稍后重试。");
  const rootRect = root.getBoundingClientRect();
  if (rootRect.width < 24 || rootRect.height < 24) throw new Error("当前页面尺寸无效，无法截图。");
  const canvas = await html2canvas(root, {
    scale: Math.min(window.devicePixelRatio || 1, 2),
    useCORS: true,
    allowTaint: false,
    backgroundColor: window.getComputedStyle(root).backgroundColor || "#07111f",
    width: Math.round(rootRect.width),
    height: Math.round(rootRect.height),
    scrollX: -window.scrollX,
    scrollY: -window.scrollY,
    logging: false,
    onclone: (clonedDocument) => prepareClonedWorkspace(clonedDocument, target, mapImageDataUrl)
  });
  return canvas.toDataURL("image/png");
}
