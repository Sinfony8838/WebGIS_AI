/**
 * Bidirectional mapping between Cesium camera altitude (meters above
 * the ellipsoid) and an OpenLayers Web-Mercator zoom level.
 *
 * Web-Mercator resolution (m/pixel at the equator) at zoom z is
 *   ground_resolution = 156543.034 / 2^z
 * For a typical viewport ~900 px tall, the camera "altitude" that
 * roughly fills the screen is altitude ≈ ground_resolution * 900.
 *
 * This is an approximation, but it's the standard one used in
 * digital-globe applications (Cesium docs, ol-cesium) and is good
 * enough to make 2D ↔ 3D transitions feel continuous.
 *
 * Thresholds used by App.tsx:
 *   - globe → plane: altitude < 500 km   (≈ zoom 8.5)
 *   - plane → globe: zoom < 3            (≈ altitude 14,000 km)
 */

const EQUATOR_RESOLUTION = 156543.03392804097;
const VIEWPORT_REFERENCE_PX = 900;

/** Web-Mercator zoom that fills a 900-pixel viewport at the given altitude. */
export function altitudeToZoom(altitudeMeters: number): number {
  if (!Number.isFinite(altitudeMeters) || altitudeMeters <= 0) {
    return 0;
  }
  const groundResolution = altitudeMeters / VIEWPORT_REFERENCE_PX;
  const zoom = Math.log2(EQUATOR_RESOLUTION / groundResolution);
  // Clamp to OL's usable range
  return Math.max(0, Math.min(22, zoom));
}

/** Inverse of altitudeToZoom — camera altitude in meters for a given zoom. */
export function zoomToAltitude(zoom: number): number {
  if (!Number.isFinite(zoom)) {
    return 12_000_000;
  }
  const clamped = Math.max(0, Math.min(22, zoom));
  const groundResolution = EQUATOR_RESOLUTION / Math.pow(2, clamped);
  return groundResolution * VIEWPORT_REFERENCE_PX;
}

/** Altitude (m) below which the 3D globe should auto-transition to 2D. */
export const GLOBE_TO_PLANE_ALTITUDE_THRESHOLD = 500_000; // 500 km

/** Zoom level below which the 2D plane should auto-transition to 3D. */
export const PLANE_TO_GLOBE_ZOOM_THRESHOLD = 3;

/** Default initial altitude for the globe view — high enough to see all of Asia. */
export const DEFAULT_GLOBE_ALTITUDE = 12_000_000; // 12,000 km

/** Default landing altitude when transitioning from globe to plane via double-click. */
export const DOUBLE_CLICK_LANDING_ALTITUDE = 1_000_000; // 1,000 km
