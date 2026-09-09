export type LegendRow =
  | { kind: "text"; text: string; heading?: boolean; color?: string; dashed?: boolean }
  | { kind: "swatches"; items: { label: string; color: string }[] }
  | { kind: "image"; src: string; alt: string };

export type SnapshotDocument = {
  title: string;
  capturedAt: string;
  basemap: string;
  attribution: string;
  rows: LegendRow[];
};

const text = (element: Element) => (element.textContent || "").replace(/\s+/g, " ").trim();
const colorOf = (element: Element | null) => element ? getComputedStyle(element).backgroundColor : "#64748b";

/** Read the rendered legend once, including folded sources, without changing UI. */
export function collectLegendRows(root: Element | null): LegendRow[] {
  if (!root) return [];
  const rows: LegendRow[] = [];
  const visit = (element: Element) => {
    if (element.matches("button, input, label, summary")) return;
    if (element.matches(".map-density-key")) {
      rows.push({ kind: "swatches", items: Array.from(element.children).map(item => ({
        label: text(item), color: colorOf(item.querySelector("i"))
      })) });
    } else if (element.matches(".map-other-key")) {
      rows.push({ kind: "swatches", items: [{ label: text(element), color: colorOf(element.querySelector("i")) }] });
    } else if (element.matches("strong, p, a")) {
      let value = text(element);
      if (element instanceof HTMLAnchorElement && /^https?:/.test(element.href)) value += ` · ${element.href}`;
      if (value) {
        const line = element.querySelector(".map-line-key, .map-precipitation-key");
        rows.push({ kind: "text", text: value, heading: element.tagName === "STRONG",
          ...(line ? { color: line.matches(".map-precipitation-key") ? getComputedStyle(line).borderTopColor : colorOf(line),
            dashed: line.matches(".map-precipitation-key") } : {}) });
      }
    } else if (element instanceof HTMLImageElement) {
      rows.push({ kind: "image", src: element.currentSrc || element.src, alt: element.alt });
    } else {
      Array.from(element.children).forEach(visit);
    }
  };
  visit(root);
  return rows;
}

export function plainAttribution(html: string): string {
  return new DOMParser().parseFromString(html, "text/html").body.textContent?.replace(/\s+/g, " ").trim() || "";
}

export function loadSnapshotImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const timer = window.setTimeout(() => { image.onload = null; image.onerror = null; reject(new Error("图例图片加载超时")); }, 5000);
    image.crossOrigin = "anonymous";
    image.onload = () => { clearTimeout(timer); resolve(image); };
    image.onerror = () => { clearTimeout(timer); reject(new Error("图例图片无法读取")); };
    image.src = src;
  });
}

export function wrapSnapshotText(context: Pick<CanvasRenderingContext2D, "measureText">, value: string, width: number): string[] {
  const lines: string[] = [];
  for (const paragraph of value.split("\n")) {
    let line = "";
    for (const character of Array.from(paragraph)) {
      if (line && context.measureText(line + character).width > width) { lines.push(line); line = ""; }
      line += character;
    }
    lines.push(line);
  }
  return lines;
}

/** Add the source sheet below the map; never cover or recolor map pixels. */
export async function composeSnapshotDocument(source: string, document: SnapshotDocument, cropWidth: number): Promise<string> {
  const mapImage = await loadSnapshotImage(source);
  const ratio = mapImage.naturalWidth / Math.max(cropWidth, 1);
  const width = Math.max(640, Math.round(cropWidth));
  const mapWidth = mapImage.naturalWidth / ratio;
  const mapHeight = mapImage.naturalHeight / ratio;
  const padding = 28, innerWidth = width - padding * 2;
  const canvas = window.document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) throw new Error("无法生成地图资料图片");
  const images = new Map<string, HTMLImageElement>();
  await Promise.all(document.rows.filter((row): row is Extract<LegendRow, {kind:"image"}> => row.kind === "image").map(async row => {
    // A missing official legend must be reported, never silently omitted.
    images.set(row.src, await loadSnapshotImage(row.src));
  }));
  const font = (heading = false) => `${heading ? "600 18" : "14"}px "Microsoft YaHei", "PingFang SC", sans-serif`;
  const draws: (() => void)[] = [];
  let y = mapHeight + padding;
  const addText = (value: string, heading = false, color?: string, dashed = false) => {
    context.font = font(heading);
    const indent = color ? 32 : 0;
    const lines = wrapSnapshotText(context, value, innerWidth - indent);
    const start = y;
    draws.push(() => {
      context.font = font(heading); context.fillStyle = heading ? "#17354a" : "#334d5e";
      if (color) {
        context.strokeStyle = color; context.lineWidth = 3; context.setLineDash(dashed ? [7, 5] : []);
        context.beginPath(); context.moveTo(padding, start + 11); context.lineTo(padding + 23, start + 11); context.stroke(); context.setLineDash([]);
      }
      lines.forEach((line, i) => context.fillText(line, padding + indent, start + i * 23));
    });
    y += lines.length * 23 + (heading ? 10 : 6);
  };
  addText(document.title || "课堂地图", true);
  addText(`截图时间：${document.capturedAt} · 底图：${document.basemap}`);
  if (document.attribution) addText(`底图署名：${document.attribution}`);
  addText("以下图例与资料对应截图时启用的专题；局部裁剪可能只包含其中一部分。截图时间不等于数据年份。");
  for (const row of document.rows) {
    if (row.kind === "text") addText(row.text, row.heading, row.color, row.dashed);
    else if (row.kind === "image") {
      const image = images.get(row.src)!;
      const imageWidth = Math.min(innerWidth, 620);
      const imageHeight = imageWidth * image.naturalHeight / Math.max(image.naturalWidth, 1);
      const top = y;
      draws.push(() => context.drawImage(image, padding, top, imageWidth, imageHeight));
      y += imageHeight + 12;
      if (row.alt) addText(row.alt);
    } else {
      const columns = Math.min(row.items.length, Math.max(1, Math.floor(innerWidth / 110)));
      const cellWidth = innerWidth / Math.max(columns, 1);
      for (let i = 0; i < row.items.length; i += columns) {
        const items = row.items.slice(i, i + columns);
        const top = y;
        context.font = font();
        const labels = items.map(item => wrapSnapshotText(context, item.label, cellWidth - 10));
        const height = 24 + Math.max(1, ...labels.map(lines => lines.length)) * 23;
        draws.push(() => items.forEach((item, column) => {
          const left = padding + column * cellWidth;
          context.fillStyle = item.color; context.fillRect(left, top, cellWidth - 6, 12);
          context.font = font(); context.fillStyle = "#334d5e";
          labels[column].forEach((label, line) => context.fillText(label, left, top + 20 + line * 23));
        }));
        y += height;
      }
      y += 6;
    }
  }
  if (!document.rows.length) addText("当前画面没有专题图例；请结合底图和已保存的课堂材料判读。");
  canvas.width = Math.ceil(width * ratio); canvas.height = Math.ceil((y + padding) * ratio);
  context.scale(ratio, ratio); context.textBaseline = "top";
  context.fillStyle = "#ffffff"; context.fillRect(0, 0, width, y + padding);
  context.drawImage(mapImage, (width - mapWidth) / 2, 0, mapWidth, mapHeight);
  context.strokeStyle = "#d8e3e9"; context.lineWidth = 1;
  context.beginPath(); context.moveTo(0, mapHeight); context.lineTo(width, mapHeight); context.stroke();
  draws.forEach(draw => draw());
  return canvas.toDataURL("image/png");
}

/** The ink canvas covers the viewport; crop it by the map's client rectangle. */
export function drawSnapshotInk(context: CanvasRenderingContext2D, ink: HTMLCanvasElement | null, bounds: DOMRect | {left:number;top:number;width:number;height:number}) {
  if (!ink?.width || !ink.height) return;
  const rect = ink.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const x = (bounds.left - rect.left) * ink.width / rect.width;
  const y = (bounds.top - rect.top) * ink.height / rect.height;
  context.drawImage(ink, x, y, bounds.width * ink.width / rect.width, bounds.height * ink.height / rect.height, 0, 0, bounds.width, bounds.height);
}


export async function mergeSnapshotInk(source: string, bounds: {left:number;top:number;width:number;height:number}, ink: HTMLCanvasElement | null): Promise<string> {
  // Freeze ink before awaiting image decoding, which may span a camera update.
  const frozen = window.document.createElement("canvas");
  const ratio = window.devicePixelRatio || 1;
  frozen.width = Math.round(bounds.width * ratio); frozen.height = Math.round(bounds.height * ratio);
  const frozenContext = frozen.getContext("2d");
  if (!frozenContext) throw new Error("无法读取课堂笔迹");
  frozenContext.scale(ratio, ratio); drawSnapshotInk(frozenContext, ink, bounds);
  const image = await loadSnapshotImage(source);
  const canvas = window.document.createElement("canvas");
  canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("无法合成课堂笔迹");
  context.drawImage(image, 0, 0); context.drawImage(frozen, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/png");
}
