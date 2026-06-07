/**
 * Cesium-based 3D digital globe view.
 *
 * The widget lifecycle:
 *   - Viewer is created lazily on first mount and destroyed on unmount.
 *   - When `visible=false` the underlying canvas is hidden via CSS but the
 *     Cesium scene is kept warm so re-showing it is instant.
 *   - Imagery is sourced from the backend basemap catalog (XYZ URL template
 *     compatible with Cesium's UrlTemplateImageryProvider).
 *   - Camera state is reported to the parent via `onCameraChange` (throttled
 *     to one rAF per dispatch) so that other UI surfaces (status bar,
 *     pitch slider, compass) stay in sync.
 *   - When the camera altitude drops below
 *     `GLOBE_TO_PLANE_ALTITUDE_THRESHOLD`, we fire `onAltitudeThreshold`
 *     exactly once so the parent can transition to 2D.
 *   - Double-click on the globe surface fires `onDoubleClickGlobe(lon, lat)`
 *     for the "dive into 2D" gesture.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import {
  DEFAULT_GLOBE_ALTITUDE,
  GLOBE_TO_PLANE_ALTITUDE_THRESHOLD
} from "../lib/altitudeZoom";

export type CameraState = {
  lon: number;
  lat: number;
  altitudeMeters: number;
  headingDeg: number;
  pitchDeg: number;
};

export type Map3DGlobeHandle = {
  flyTo: (lon: number, lat: number, altitudeMeters?: number, durationSeconds?: number) => void;
  resetView: () => void;
  getCameraState: () => CameraState | null;
};

type Props = {
  /** Visible state — hides the canvas without destroying the scene. */
  visible: boolean;
  /** XYZ template URL used as the globe imagery. Use {x}/{y}/{z} placeholders. */
  imageryUrl: string;
  /** Optional subdomains array for the imagery URL. */
  imagerySubdomains?: string[];
  /** Whether to show the lat/lon graticule overlay. */
  showGraticule?: boolean;
  /** Initial camera position (defaults to China at 12000km). */
  initialView?: { lon: number; lat: number; altitudeMeters: number };
  /** Throttled camera change callback. */
  onCameraChange?: (state: CameraState) => void;
  /**
   * Fires once when altitude drops below GLOBE_TO_PLANE_ALTITUDE_THRESHOLD.
   * Re-arms when altitude climbs above 2x the threshold.
   */
  onAltitudeThreshold?: (state: CameraState) => void;
  /** Double-click on a point of the globe surface. */
  onDoubleClickGlobe?: (lon: number, lat: number) => void;
  /** WebGL init failure handler — caller should fall back to 2D. */
  onWebGLError?: (message: string) => void;
};

const DEFAULT_INITIAL_VIEW = {
  lon: 104,
  lat: 35,
  altitudeMeters: DEFAULT_GLOBE_ALTITUDE
};

function extractTokenPattern(template: string): { url: string; subdomains?: string[] } {
  // Cesium's UrlTemplateImageryProvider uses {x}/{y}/{z}/{s} placeholders,
  // matching OpenLayers' XYZ convention. We pass through unchanged.
  const subdomainMatch = template.match(/\{([a-z0-9_,;-]+)\}/i);
  if (subdomainMatch && subdomainMatch[1].includes(",")) {
    const subdomains = subdomainMatch[1].split(",").map((s) => s.trim()).filter(Boolean);
    return { url: template.replace(subdomainMatch[0], "{s}"), subdomains };
  }
  return { url: template };
}

export const Map3DGlobe = forwardRef<Map3DGlobeHandle, Props>(function Map3DGlobe(
  {
    visible,
    imageryUrl,
    imagerySubdomains,
    showGraticule,
    initialView = DEFAULT_INITIAL_VIEW,
    onCameraChange,
    onAltitudeThreshold,
    onDoubleClickGlobe,
    onWebGLError
  },
  ref
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const screenHandlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);
  const gridLayerRef = useRef<Cesium.ImageryLayer | null>(null);
  const gridLabelsRef = useRef<Cesium.LabelCollection | null>(null);
  const baseImageryLayerRef = useRef<Cesium.ImageryLayer | null>(null);
  const altitudeArmedRef = useRef(true);
  const lastCameraStateRef = useRef<CameraState | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const callbacksRef = useRef({ onCameraChange, onAltitudeThreshold, onDoubleClickGlobe, onWebGLError });

  // Keep callback refs current so the Viewer's persistent listeners always
  // dispatch to the latest props without needing to recreate the scene.
  callbacksRef.current = { onCameraChange, onAltitudeThreshold, onDoubleClickGlobe, onWebGLError };

  // One-time Viewer initialization
  useEffect(() => {
    if (!containerRef.current || viewerRef.current) {
      return undefined;
    }

    const { url, subdomains: extractedSubdomains } = extractTokenPattern(imageryUrl);
    const subdomains = imagerySubdomains && imagerySubdomains.length ? imagerySubdomains : extractedSubdomains;

    let viewer: Cesium.Viewer;
    try {
      viewer = new Cesium.Viewer(containerRef.current, {
        // Hide every default widget — we render our own UI.
        animation: false,
        baseLayerPicker: false,
        fullscreenButton: false,
        geocoder: false,
        homeButton: false,
        infoBox: false,
        sceneModePicker: false,
        selectionIndicator: false,
        timeline: false,
        navigationHelpButton: false,
        navigationInstructionsInitiallyVisible: false,
        vrButton: false,
        baseLayer: Cesium.ImageryLayer.fromProviderAsync(
          Promise.resolve(
            new Cesium.UrlTemplateImageryProvider({
              url,
              subdomains,
              maximumLevel: 18,
              credit: new Cesium.Credit("© 高德地图", false)
            })
          ),
          {}
        ),
        terrain: new Cesium.Terrain(Promise.resolve(new Cesium.EllipsoidTerrainProvider())),
        skyBox: undefined,
        skyAtmosphere: undefined,
        // Keep contextOptions explicit so a WebGL failure surfaces as a
        // thrown error we can catch and recover from.
        contextOptions: {
          webgl: {
            failIfMajorPerformanceCaveat: false
          }
        }
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Cesium Viewer 初始化失败";
      callbacksRef.current.onWebGLError?.(message);
      return undefined;
    }

    viewerRef.current = viewer;
    baseImageryLayerRef.current = viewer.imageryLayers.get(0);

    // Visual polish: enable lighting for a subtle terminator, dim the
    // background stars enough that they don't compete with the UI chrome,
    // and tint the atmosphere a cool blue to match the rest of the app.
    viewer.scene.globe.enableLighting = false;
    viewer.scene.globe.showGroundAtmosphere = true;
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#06182c");
    if (viewer.scene.skyAtmosphere) {
      viewer.scene.skyAtmosphere.hueShift = -0.06;
      viewer.scene.skyAtmosphere.saturationShift = 0.04;
      viewer.scene.skyAtmosphere.brightnessShift = 0.04;
    }
    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#000610");

    // Disable text selection inside the Cesium canvas — it interferes with
    // pan / orbit drag gestures on some touch devices.
    viewer.canvas.style.outline = "none";

    // Fly to the initial Chinese-centric view.
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(
        initialView.lon,
        initialView.lat,
        initialView.altitudeMeters
      ),
      orientation: {
        heading: 0,
        pitch: Cesium.Math.toRadians(-90),
        roll: 0
      }
    });

    // Camera change subscription (throttled via rAF).
    const dispatchCameraState = () => {
      rafIdRef.current = null;
      const cam = viewer.camera;
      const cartographic = Cesium.Cartographic.fromCartesian(cam.positionWC);
      const lon = Cesium.Math.toDegrees(cartographic.longitude);
      const lat = Cesium.Math.toDegrees(cartographic.latitude);
      const altitudeMeters = cartographic.height;
      const headingDeg = Cesium.Math.toDegrees(cam.heading);
      const pitchDeg = Cesium.Math.toDegrees(cam.pitch);
      const state: CameraState = { lon, lat, altitudeMeters, headingDeg, pitchDeg };
      lastCameraStateRef.current = state;
      callbacksRef.current.onCameraChange?.(state);

      // Altitude threshold edge-triggered dispatch.
      if (altitudeArmedRef.current && altitudeMeters < GLOBE_TO_PLANE_ALTITUDE_THRESHOLD) {
        altitudeArmedRef.current = false;
        callbacksRef.current.onAltitudeThreshold?.(state);
      } else if (!altitudeArmedRef.current && altitudeMeters > GLOBE_TO_PLANE_ALTITUDE_THRESHOLD * 2) {
        altitudeArmedRef.current = true;
      }
    };

    const onCameraMoved = () => {
      if (rafIdRef.current !== null) {
        return;
      }
      rafIdRef.current = window.requestAnimationFrame(dispatchCameraState);
    };
    viewer.camera.changed.addEventListener(onCameraMoved);
    viewer.camera.percentageChanged = 0.0001;
    // Push initial state once so UI has something to display.
    dispatchCameraState();

    // Double-click handler for "dive into 2D" gesture.
    const screenHandler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
    screenHandler.setInputAction((event: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
      let lon: number | null = null;
      let lat: number | null = null;
      // Prefer a real surface pick (works at low altitude); fall back to
      // ellipsoid intersection when above the globe.
      const picked = viewer.scene.pickPosition(event.position);
      if (picked && Number.isFinite(picked.x)) {
        const c = Cesium.Cartographic.fromCartesian(picked);
        lon = Cesium.Math.toDegrees(c.longitude);
        lat = Cesium.Math.toDegrees(c.latitude);
      } else {
        const ray = viewer.camera.getPickRay(event.position);
        if (ray) {
          const intersection = viewer.scene.globe.pick(ray, viewer.scene);
          if (intersection) {
            const c = Cesium.Cartographic.fromCartesian(intersection);
            lon = Cesium.Math.toDegrees(c.longitude);
            lat = Cesium.Math.toDegrees(c.latitude);
          }
        }
      }
      if (lon !== null && lat !== null) {
        callbacksRef.current.onDoubleClickGlobe?.(lon, lat);
      }
    }, Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
    screenHandlerRef.current = screenHandler;

    return () => {
      if (rafIdRef.current !== null) {
        window.cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      try {
        viewer.camera.changed.removeEventListener(onCameraMoved);
      } catch {
        /* viewer already torn down */
      }
      screenHandler.destroy();
      screenHandlerRef.current = null;
      try {
        viewer.destroy();
      } catch {
        /* ignore */
      }
      viewerRef.current = null;
      baseImageryLayerRef.current = null;
      gridLayerRef.current = null;
      gridLabelsRef.current = null;
    };
    // We intentionally exclude the imagery and initialView from the dep
    // array so the Viewer is created exactly once. Live updates flow
    // through the dedicated effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Live-swap the base imagery layer when the URL prop changes.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) {
      return;
    }
    const { url, subdomains: extractedSubdomains } = extractTokenPattern(imageryUrl);
    const subdomains = imagerySubdomains && imagerySubdomains.length ? imagerySubdomains : extractedSubdomains;
    const provider = new Cesium.UrlTemplateImageryProvider({
      url,
      subdomains,
      maximumLevel: 18,
      credit: new Cesium.Credit("© 高德地图", false)
    });
    const nextLayer = new Cesium.ImageryLayer(provider, {});
    // Insert below the grid layer (if any) but above other layers.
    viewer.imageryLayers.add(nextLayer, 0);
    if (baseImageryLayerRef.current) {
      viewer.imageryLayers.remove(baseImageryLayerRef.current, true);
    }
    baseImageryLayerRef.current = nextLayer;
  }, [imageryUrl, imagerySubdomains]);

  // Add or remove the lat/lon graticule overlay (lines + numeric labels).
  // The grid is two coordinated pieces: a tile-based GridImageryProvider
  // for the lines, plus a Cesium LabelCollection placed at major degree
  // intersections to surface readable lat/lon numbers — the imagery
  // provider alone doesn't draw text.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) {
      return;
    }
    if (showGraticule) {
      if (!gridLayerRef.current) {
        const gridProvider = new Cesium.GridImageryProvider({
          cells: 8,
          color: Cesium.Color.fromCssColorString("rgba(140, 222, 255, 0.42)"),
          glowColor: Cesium.Color.fromCssColorString("rgba(140, 222, 255, 0.14)"),
          glowWidth: 1,
          backgroundColor: Cesium.Color.TRANSPARENT
        });
        gridLayerRef.current = viewer.imageryLayers.addImageryProvider(gridProvider);
      }
      if (!gridLabelsRef.current) {
        const labels = new Cesium.LabelCollection();
        viewer.scene.primitives.add(labels);
        // Major intersections every 30° — dense enough to anchor the
        // user's reading, sparse enough not to clutter the view.
        const fontSpec = "11px 'Inter', 'Noto Sans SC', sans-serif";
        const fill = Cesium.Color.fromCssColorString("rgba(224, 240, 254, 0.94)");
        const outline = Cesium.Color.fromCssColorString("rgba(8, 24, 44, 0.92)");
        const farFade = new Cesium.NearFarScalar(2_000_000, 1.0, 30_000_000, 0.45);
        for (let lon = -180; lon <= 180; lon += 30) {
          for (let lat = -60; lat <= 60; lat += 30) {
            const lonLabel = lon === 0 ? "0°" : `${Math.abs(lon)}°${lon > 0 ? "E" : "W"}`;
            const latLabel = lat === 0 ? "0°" : `${Math.abs(lat)}°${lat > 0 ? "N" : "S"}`;
            labels.add({
              position: Cesium.Cartesian3.fromDegrees(lon, lat),
              text: `${lonLabel}\n${latLabel}`,
              font: fontSpec,
              fillColor: fill,
              outlineColor: outline,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
              verticalOrigin: Cesium.VerticalOrigin.CENTER,
              scaleByDistance: farFade,
              disableDepthTestDistance: 0
            });
          }
        }
        gridLabelsRef.current = labels;
      }
      viewer.scene.requestRender();
    } else {
      if (gridLayerRef.current) {
        viewer.imageryLayers.remove(gridLayerRef.current, true);
        gridLayerRef.current = null;
      }
      if (gridLabelsRef.current) {
        viewer.scene.primitives.remove(gridLabelsRef.current);
        gridLabelsRef.current = null;
      }
      viewer.scene.requestRender();
    }
  }, [showGraticule]);

  // Pause Cesium rendering when invisible to save GPU cycles.
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) {
      return;
    }
    viewer.useDefaultRenderLoop = visible;
    if (visible) {
      // Force one frame so the canvas isn't stale.
      viewer.scene.requestRender();
    }
  }, [visible]);

  useImperativeHandle(
    ref,
    (): Map3DGlobeHandle => ({
      flyTo: (lon, lat, altitudeMeters, durationSeconds = 1.2) => {
        const viewer = viewerRef.current;
        if (!viewer) {
          return;
        }
        const altitude = altitudeMeters ?? DEFAULT_GLOBE_ALTITUDE;
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(lon, lat, altitude),
          orientation: {
            heading: 0,
            pitch: Cesium.Math.toRadians(-90),
            roll: 0
          },
          duration: durationSeconds
        });
      },
      resetView: () => {
        const viewer = viewerRef.current;
        if (!viewer) {
          return;
        }
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(
            DEFAULT_INITIAL_VIEW.lon,
            DEFAULT_INITIAL_VIEW.lat,
            DEFAULT_INITIAL_VIEW.altitudeMeters
          ),
          orientation: {
            heading: 0,
            pitch: Cesium.Math.toRadians(-90),
            roll: 0
          },
          duration: 1.4
        });
      },
      getCameraState: () => lastCameraStateRef.current
    })
  );

  return (
    <div
      ref={containerRef}
      className={`map-3d-globe ${visible ? "is-visible" : "is-hidden"}`}
      data-testid="map-3d-globe"
      aria-hidden={!visible}
    />
  );
});
