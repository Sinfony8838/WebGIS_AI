import type { BrushSettings } from "../components/BrushOverlay";

export type InkPoint = [number, number];
export type MapInkStroke = { paths: InkPoint[][]; color: string; lineWidth: number };
export type MapInkProjection = {
  toWorld: (client: InkPoint) => InkPoint | null;
  toClient: (world: InkPoint) => InkPoint | null;
  subscribe: (render: () => void) => (() => void) | undefined;
};

// Sample shapes before inverse projection: their geographic positions survive
// panning, zooming, rotation and transitions between the plane and globe.
export function shapePaths(start: InkPoint, end: InkPoint, settings: BrushSettings): InkPoint[][] {
  const [x, y] = start, [ex, ey] = end;
  if (settings.tool === "rectangle") return [[[x,y],[ex,y],[ex,ey],[x,ey],[x,y]]];
  if (settings.tool === "ellipse") return [Array.from({ length: 73 }, (_, i) => {
    const angle = i * Math.PI / 36;
    return [(x+ex)/2 + Math.abs(ex-x)/2*Math.cos(angle), (y+ey)/2 + Math.abs(ey-y)/2*Math.sin(angle)] as InkPoint;
  })];
  if (settings.tool === "arrow") {
    const a = Math.atan2(ey-y, ex-x), n = Math.max(10, settings.lineWidth*3);
    return [[start,end], [[ex-n*Math.cos(a-Math.PI/6),ey-n*Math.sin(a-Math.PI/6)],end,[ex-n*Math.cos(a+Math.PI/6),ey-n*Math.sin(a+Math.PI/6)]]];
  }
  return [[start,end]];
}

export function anchorPaths(paths: InkPoint[][], toWorld: MapInkProjection["toWorld"]): InkPoint[][] {
  const anchored: InkPoint[][] = [];
  for (const path of paths) {
    let section: InkPoint[] = [];
    const append = (pixel: InkPoint) => {
      const point = toWorld(pixel);
      if (point && point.every(Number.isFinite)) section.push(point);
      else if (section.length) { anchored.push(section); section = []; }
    };
    if (path.length) append(path[0]);
    for (let i = 1; i < path.length; i++) {
      const a = path[i-1], b = path[i];
      const steps = Math.max(1, Math.ceil(Math.hypot(b[0]-a[0], b[1]-a[1])/4));
      for (let j = 1; j <= steps; j++) append([a[0]+(b[0]-a[0])*j/steps, a[1]+(b[1]-a[1])*j/steps]);
    }
    if (section.length) anchored.push(section);
  }
  return anchored;
}

function distanceToSegment(point: InkPoint, a: InkPoint, b: InkPoint): number {
  const dx=b[0]-a[0], dy=b[1]-a[1], length=dx*dx+dy*dy;
  const t=length ? Math.max(0,Math.min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/length)) : 0;
  return Math.hypot(point[0]-a[0]-t*dx, point[1]-a[1]-t*dy);
}

// Erase geographic segments, not display pixels, so erased parts cannot
// reappear when the map is zoomed. Sampling limits edge error to 4 draw pixels.
export function eraseInk(strokes: MapInkStroke[], point: InkPoint, radius: number, project: MapInkProjection["toClient"]): MapInkStroke[] {
  return strokes.flatMap(stroke => {
    const paths: InkPoint[][] = [];
    for (const path of stroke.paths) {
      let section: InkPoint[] = [];
      if (path.length === 1) {
        const p=project(path[0]);
        if (!p || Math.hypot(p[0]-point[0],p[1]-point[1]) > radius+stroke.lineWidth/2) paths.push(path);
        continue;
      }
      for (let i=1; i<path.length; i++) {
        const a=project(path[i-1]), b=project(path[i]);
        const hit=a && b && distanceToSegment(point,a,b) <= radius+stroke.lineWidth/2;
        if (hit) { if (section.length) paths.push(section); section=[]; }
        else { if (!section.length) section.push(path[i-1]); section.push(path[i]); }
      }
      if (section.length) paths.push(section);
    }
    return paths.length ? [{...stroke,paths}] : [];
  });
}
