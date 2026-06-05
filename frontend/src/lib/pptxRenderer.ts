/**
 * OOXML (.pptx) parser — unpacks with JSZip, renders each slide as
 * positioned HTML elements inside a relative container.
 */
import JSZip from "jszip";
import type { SlideContent, PptxParsedPresentation } from "../types";

const EMU_PER_PX = 914400 / 96; // 9525 EMU per CSS-px at 96 dpi

// ── public API ──────────────────────────────────────────────

export async function parsePptxFile(file: File): Promise<PptxParsedPresentation> {
  const zip = await JSZip.loadAsync(file.arrayBuffer());

  const presXml = await readZipEntry(zip, "ppt/presentation.xml");
  const { width, height } = parseSlideSize(presXml);

  const slideFiles = Object.keys(zip.files)
    .filter((k) => /^ppt\/slides\/slide\d+\.xml$/.test(k))
    .sort(naturalSort);

  const slides: SlideContent[] = [];
  for (const slidePath of slideFiles) {
    const xml = await readZipEntry(zip, slidePath);
    const relsPath = slidePath.replace(/slides\//, "slides/_rels/").replace(/\.xml$/, ".xml.rels");
    const relsXml = zip.file(relsPath) ? await readZipEntry(zip, relsPath) : "";
    const imageRels = parseImageRelationships(relsXml);

    const images: Record<string, string> = {};
    for (const [rId, target] of Object.entries(imageRels)) {
      const imgPath = "ppt/slides/" + target;
      const imgFile = zip.file(imgPath) || zip.file("ppt/" + target);
      if (imgFile) {
        const blob = await imgFile.async("blob");
        images[rId] = URL.createObjectURL(blob);
      }
    }

    const bgColor = extractSlideBgColor(xml);
    const html = renderSlideToHtml(xml, images, width, height);
    slides.push({ index: slides.length, html, bgColor, images, width, height });
  }

  return { fileName: file.name, slideWidth: width, slideHeight: height, slides };
}

export function releaseSlideObjectUrls(slides: SlideContent[]): void {
  for (const slide of slides) {
    for (const url of Object.values(slide.images)) {
      URL.revokeObjectURL(url);
    }
  }
}

// ── XML parsing helpers ─────────────────────────────────────

async function readZipEntry(zip: JSZip, path: string): Promise<string> {
  const entry = zip.file(path);
  if (!entry) throw new Error(`Missing ZIP entry: ${path}`);
  return entry.async("string");
}

function naturalSort(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

function parseSlideSize(xml: string): { width: number; height: number } {
  const m = xml.match(/<[^>]*sldSz[^>]*\bcx="(\d+)"[^>]*\bcy="(\d+)"/);
  if (m) return { width: parseInt(m[1], 10), height: parseInt(m[2], 10) };
  // default 10 x 7.5 inches
  return { width: 9144000, height: 6858000 };
}

function parseImageRelationships(relsXml: string): Record<string, string> {
  const result: Record<string, string> = {};
  if (!relsXml) return result;
  const re = /Id="([^"]+)"[^>]*Type="[^"]*image[^"]*"[^>]*Target="([^"]+)"/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(relsXml))) {
    result[m[1]] = m[2];
  }
  return result;
}

function extractSlideBgColor(xml: string): string | undefined {
  const bgMatch = xml.match(/<p:bg>([\s\S]*?)<\/p:bg>/);
  if (!bgMatch) return undefined;
  const clr = bgMatch[1].match(/<a:srgbClr val="([0-9A-Fa-f]{6})"/);
  if (clr) return `#${clr[1]}`;
  const schemeClr = bgMatch[1].match(/<a:schemeClr val="(\w+)"/);
  if (schemeClr) return schemeColorToHex(schemeClr[1]);
  return undefined;
}

// ── Slide → HTML renderer ───────────────────────────────────

function renderSlideToHtml(
  xml: string,
  images: Record<string, string>,
  slideW: number,
  slideH: number,
): string {
  const treeMatch = xml.match(/<p:spTree>([\s\S]*?)<\/p:spTree>/);
  if (!treeMatch) return "";
  const treeXml = treeMatch[1];

  const parts: string[] = [];
  walkTree(treeXml, images, parts, slideW, slideH, 0, 0);
  return parts.join("");
}

function walkTree(
  xml: string,
  images: Record<string, string>,
  out: string[],
  _slideW: number,
  _slideH: number,
  _offX: number,
  _offY: number,
): void {
  // Process <p:sp>, <p:pic>, <p:grpSp> in document order
  const tagRe = /<(p:sp|p:pic|p:grpSp)\b/g;
  let m: RegExpExecArray | null;
  while ((m = tagRe.exec(xml))) {
    const tag = m[1];
    const start = m.index;
    const end = findMatchingClose(xml, start, tag);
    if (end < 0) continue;
    const chunk = xml.slice(start, end + tag.length + 3); // +3 for "</>"

    if (tag === "p:sp") {
      const html = renderShape(chunk, images);
      if (html) out.push(html);
    } else if (tag === "p:pic") {
      const html = renderPicture(chunk, images);
      if (html) out.push(html);
    } else if (tag === "p:grpSp") {
      // Recurse into group children (skip grpSpPr)
      const innerMatch = chunk.match(/<p:grpSp>([\s\S]*?)<\/p:grpSp>/);
      if (innerMatch) walkTree(innerMatch[1], images, out, _slideW, _slideH, _offX, _offY);
    }
  }
}

function renderShape(xml: string, _images: Record<string, string>): string {
  const xfrm = parseXfrm(xml);
  if (!xfrm) return "";

  const style = buildPositionStyle(xfrm);

  // Extract fill color
  const fillColor = extractFillColor(xml);

  // Extract border
  const border = extractBorder(xml);

  // Extract text
  const textHtml = extractTextHtml(xml);

  const bgStyle = fillColor ? `background:${fillColor};` : "";
  const borderStyle = border ? `border:${border};` : "";

  return `<div style="position:absolute;${style}${bgStyle}${borderStyle}">${textHtml}</div>`;
}

function renderPicture(xml: string, images: Record<string, string>): string {
  const xfrm = parseXfrm(xml);
  if (!xfrm) return "";

  const style = buildPositionStyle(xfrm);
  const blipMatch = xml.match(/r:embed="([^"]+)"/);
  if (!blipMatch) return "";

  const url = images[blipMatch[1]];
  if (!url) return "";

  return `<div style="position:absolute;${style}"><img src="${url}" style="width:100%;height:100%;object-fit:contain;" /></div>`;
}

// ── Transform parsing ───────────────────────────────────────

type Xfrm = { x: number; y: number; cx: number; cy: number; rot?: number };

function parseXfrm(xml: string): Xfrm | null {
  const xfrmMatch = xml.match(/<a:xfrm[^>]*>([\s\S]*?)<\/a:xfrm>/);
  if (!xfrmMatch) return null;
  const xfrmXml = xfrmMatch[1];

  const offMatch = xfrmXml.match(/<a:off[^>]*x="(-?\d+)"[^>]*y="(-?\d+)"/);
  const extMatch = xfrmXml.match(/<a:ext[^>]*cx="(\d+)"[^>]*cy="(\d+)"/);
  if (!offMatch || !extMatch) return null;

  const rotMatch = xfrmXml.match(/rot="(-?\d+)"/);

  return {
    x: parseInt(offMatch[1], 10),
    y: parseInt(offMatch[2], 10),
    cx: parseInt(extMatch[1], 10),
    cy: parseInt(extMatch[2], 10),
    rot: rotMatch ? parseInt(rotMatch[1], 10) : undefined,
  };
}

function buildPositionStyle(x: Xfrm): string {
  const left = x.x / EMU_PER_PX;
  const top = x.y / EMU_PER_PX;
  const w = x.cx / EMU_PER_PX;
  const h = x.cy / EMU_PER_PX;
  let s = `left:${left}px;top:${top}px;width:${w}px;height:${h}px;`;
  if (x.rot) {
    s += `transform:rotate(${x.rot / 60000}deg);transform-origin:center;`;
  }
  return s;
}

// ── Fill & border extraction ────────────────────────────────

function extractFillColor(xml: string): string | undefined {
  // Look in spPr for solidFill
  const spPrMatch = xml.match(/<p:spPr[^>]*>([\s\S]*?)<\/p:spPr>/);
  if (!spPrMatch) return undefined;
  const spPr = spPrMatch[1];

  const solidMatch = spPr.match(/<a:solidFill>([\s\S]*?)<\/a:solidFill>/);
  if (!solidMatch) return undefined;
  const fill = solidMatch[1];

  const srgb = fill.match(/<a:srgbClr val="([0-9A-Fa-f]{6})"/);
  if (srgb) return `#${srgb[1]}`;

  const scheme = fill.match(/<a:schemeClr val="(\w+)"/);
  if (scheme) return schemeColorToHex(scheme[1]);

  return undefined;
}

function extractBorder(xml: string): string | undefined {
  const lnMatch = xml.match(/<a:ln[^>]*w="(\d+)"[^>]*>([\s\S]*?)<\/a:ln>/);
  if (!lnMatch) return undefined;

  const widthEmu = parseInt(lnMatch[1], 10);
  const widthPx = Math.max(1, widthEmu / EMU_PER_PX);

  const fillXml = lnMatch[2];
  const srgb = fillXml.match(/<a:srgbClr val="([0-9A-Fa-f]{6})"/);
  const color = srgb ? `#${srgb[1]}` : "#000000";

  return `${widthPx}px solid ${color}`;
}

// ── Text extraction ─────────────────────────────────────────

function extractTextHtml(xml: string): string {
  const txBodyMatch = xml.match(/<p:txBody>([\s\S]*?)<\/p:txBody>/);
  if (!txBodyMatch) return "";
  const txBody = txBodyMatch[1];

  const paragraphs = txBody.split(/<\/a:p>/);
  const htmlParts: string[] = [];

  for (const para of paragraphs) {
    if (!para.includes("<a:p")) continue;
    const paraHtml = extractParagraphHtml(para);
    if (paraHtml) htmlParts.push(`<div style="margin:0;line-height:1.3;">${paraHtml}</div>`);
  }

  return htmlParts.join("");
}

function extractParagraphHtml(paraXml: string): string {
  const parts: string[] = [];

  // Extract run properties from the first run as paragraph default
  const defRpr = paraXml.match(/<a:defRPr[^>]*\/>/);

  // Process runs
  const runRe = /<a:r>([\s\S]*?)<\/a:r>/g;
  let m: RegExpExecArray | null;
  while ((m = runRe.exec(paraXml))) {
    const runXml = m[1];
    const rPr = runXml.match(/<a:rPr([^>]*)>/);
    const textMatch = runXml.match(/<a:t>([\s\S]*?)<\/a:t>/);
    if (!textMatch) continue;

    const text = xmlUnescape(textMatch[1]);
    const style = rPr ? parseRunStyle(rPr[1] + (rPr[0].endsWith("/>") ? "" : "")) : "";
    parts.push(`<span style="${style}">${text}</span>`);
  }

  // Process line break
  if (paraXml.includes("<a:br/>")) {
    parts.push("<br/>");
  }

  return parts.join("");
}

function parseRunStyle(rPrAttr: string): string {
  const parts: string[] = [];

  const szMatch = rPrAttr.match(/sz="(\d+)"/);
  if (szMatch) {
    // sz is in hundredths of a point; convert to px (1pt ≈ 1.333px at 96dpi)
    const pt = parseInt(szMatch[1], 10) / 100;
    parts.push(`font-size:${(pt * 1.333).toFixed(1)}px`);
  }

  const boldMatch = rPrAttr.match(/b="1"/);
  if (boldMatch) parts.push("font-weight:bold");

  const italicMatch = rPrAttr.match(/i="1"/);
  if (italicMatch) parts.push("font-style:italic");

  const underlineMatch = rPrAttr.match(/u="(\w+)"/);
  if (underlineMatch) parts.push("text-decoration:underline");

  const colorMatch = rPrAttr.match(/<a:solidFill>[\s\S]*?<a:srgbClr val="([0-9A-Fa-f]{6})"/);
  if (colorMatch) parts.push(`color:#${colorMatch[1]}`);

  const schemeColorMatch = rPrAttr.match(/<a:solidFill>[\s\S]*?<a:schemeClr val="(\w+)"/);
  if (schemeColorMatch && !colorMatch) {
    parts.push(`color:${schemeColorToHex(schemeColorMatch[1])}`);
  }

  const fontMatch = rPrAttr.match(/latin typeface="([^"]+)"/);
  if (fontMatch) parts.push(`font-family:'${fontMatch[1]}',sans-serif`);

  return parts.join(";");
}

// ── Utility ─────────────────────────────────────────────────

function xmlUnescape(s: string): string {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'");
}

function findMatchingClose(xml: string, openStart: number, tag: string): number {
  const openTag = `<${tag}`;
  const closeTag = `</${tag}>`;
  let depth = 0;
  let i = openStart;
  while (i < xml.length) {
    if (xml.startsWith(openTag, i) && (xml[i + openTag.length] === " " || xml[i + openTag.length] === ">" || xml[i + openTag.length] === "/")) {
      // Check self-closing
      const selfClose = xml.indexOf("/>", i);
      const tagEnd = xml.indexOf(">", i);
      if (selfClose >= 0 && selfClose === tagEnd - 1 && depth === 0) {
        return selfClose; // self-closing open tag
      }
      depth++;
      i = tagEnd + 1;
    } else if (xml.startsWith(closeTag, i)) {
      depth--;
      if (depth === 0) return i + closeTag.length;
      i += closeTag.length;
    } else {
      i++;
    }
  }
  return -1;
}

function schemeColorToHex(name: string): string {
  const map: Record<string, string> = {
    tx1: "#000000",
    tx2: "#44546a",
    bg1: "#ffffff",
    bg2: "#e7e6e6",
    accent1: "#4472c4",
    accent2: "#ed7d31",
    accent3: "#a5a5a5",
    accent4: "#ffc000",
    accent5: "#5b9bd5",
    accent6: "#70ad47",
    hlink: "#0563c1",
    folHlink: "#954f72",
    dk1: "#000000",
    dk2: "#44546a",
    lt1: "#ffffff",
    lt2: "#e7e6e6",
  };
  return map[name] || "#000000";
}
