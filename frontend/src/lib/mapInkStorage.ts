import type { MapInkStroke } from "./mapInk";

const key = (scope: string) => `webgis-map-ink:v1:${scope}`;
export function readMapInk(scope: string): MapInkStroke[] {
  if (!scope) return [];
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key(scope)) || "[]");
    if (!Array.isArray(value)) return [];
    return value.filter((s): s is MapInkStroke => s && typeof s.color === "string" && Number.isFinite(s.lineWidth)
      && s.lineWidth > 0 && Array.isArray(s.paths) && s.paths.every((p: unknown) => Array.isArray(p)
        && p.every(v => Array.isArray(v) && v.length === 2 && v.every(Number.isFinite))));
  } catch { return []; }
}
export function writeMapInk(scope: string, strokes: MapInkStroke[]): boolean {
  if (!scope) return true;
  try { localStorage.setItem(key(scope), JSON.stringify(strokes)); return true; }
  catch { return false; }
}
