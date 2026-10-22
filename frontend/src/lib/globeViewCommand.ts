import { DEFAULT_GLOBE_ALTITUDE, zoomToAltitude } from "./altitudeZoom";

export type GlobeViewPreset = "overview" | "default" | "preserve";
export type GlobeViewTarget = { lon: number; lat: number; altitudeMeters: number; pitchDeg: number };
export type GlobeRenderEvidence = GlobeViewTarget & { frame: number; visible: boolean; scene3D: boolean };
export function globeViewTarget(preset: GlobeViewPreset, lon = 104, lat = 35, zoom = 4): GlobeViewTarget {
  return {
    lon: preset === "default" ? 104 : lon,
    lat: preset === "default" ? 35 : lat,
    altitudeMeters: preset === "preserve" ? Math.max(zoomToAltitude(zoom), 1_000_000) : preset === "default" ? DEFAULT_GLOBE_ALTITUDE : 20_000_000,
    pitchDeg: -90
  };
}
export function renderedGlobeMatches(actual: GlobeRenderEvidence | null, target: GlobeViewTarget, afterFrame: number): boolean {
  return Boolean(actual && actual.frame > afterFrame && actual.visible && actual.scene3D
    && Math.abs(((actual.lon - target.lon + 540) % 360) - 180) < 0.05
    && Math.abs(actual.lat - target.lat) < 0.05
    && Math.abs(actual.altitudeMeters - target.altitudeMeters) < Math.max(100, target.altitudeMeters * 0.005)
    && Math.abs(actual.pitchDeg - target.pitchDeg) < 1);
}
/** A mode flag alone is not evidence: wait for a fresh frame at the requested camera. */
export async function applyGlobeView(options: {
  target: GlobeViewTarget;
  read: () => GlobeRenderEvidence | null;
  fly: () => void;
  cancel: () => void;
  isCurrent: () => boolean;
  timeoutMs?: number;
}): Promise<void> {
  const deadline = Date.now() + (options.timeoutMs ?? 6000);
  let started = false;
  let afterFrame = -1;
  while (Date.now() < deadline) {
    if (!options.isCurrent()) {
      if (started) options.cancel();
      throw new Error("视图操作已取消或项目、课堂已变化");
    }
    const evidence = options.read();
    if (!started && evidence?.visible && evidence.scene3D) {
      afterFrame = evidence.frame;
      started = true;
      options.fly();
    } else if (started && renderedGlobeMatches(evidence, options.target, afterFrame)) {
      return;
    }
    await new Promise<void>(resolve => window.setTimeout(resolve, 25));
  }
  if (started) options.cancel();
  throw new Error("三维相机或画面未完成切换，未确认成功；请检查 WebGL 或重试");
}
