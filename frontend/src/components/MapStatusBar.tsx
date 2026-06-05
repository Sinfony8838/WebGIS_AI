/**
 * Bottom status bar showing live coordinate / camera fields, matching the
 * reference geovisearth platform's footer style.
 *
 * Fields:
 *   - 经度 / 纬度    lon / lat
 *   - 海拔           ground elevation (set to "—" until terrain is wired)
 *   - 层级           OL zoom (plane) or estimated zoom from camera altitude (globe)
 *   - 视高           camera altitude (m / km)
 */
import { altitudeToZoom } from "../lib/altitudeZoom";
import type { ViewMode } from "../lib/viewMode";

type Props = {
  mode: ViewMode;
  lon: number | null;
  lat: number | null;
  /** Ground elevation in meters at the current cursor / focus. */
  elevationMeters?: number | null;
  /** OL zoom (used in plane mode). */
  zoom?: number | null;
  /** Camera altitude in meters (used in globe mode). */
  altitudeMeters?: number | null;
};

function formatLonLat(value: number | null | undefined, axis: "lon" | "lat"): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  const hemi = axis === "lon" ? (value >= 0 ? "E" : "W") : value >= 0 ? "N" : "S";
  return `${Math.abs(value).toFixed(2)}° ${hemi}`;
}

function formatMeters(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  const meters = Math.round(value);
  if (Math.abs(meters) >= 1000) {
    return `${(meters / 1000).toFixed(1)} km`;
  }
  return `${meters} m`;
}

function formatZoom(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return value.toFixed(1);
}

export function MapStatusBar({
  mode,
  lon,
  lat,
  elevationMeters,
  zoom,
  altitudeMeters
}: Props) {
  const effectiveZoom =
    mode === "globe" && altitudeMeters !== null && altitudeMeters !== undefined
      ? altitudeToZoom(altitudeMeters)
      : zoom ?? null;

  return (
    <div className="map-status-bar glass-panel" data-testid="map-status-bar" role="status" aria-live="polite">
      <Field label="经度" value={formatLonLat(lon, "lon")} />
      <Field label="纬度" value={formatLonLat(lat, "lat")} />
      <Field label="海拔" value={formatMeters(elevationMeters ?? null)} />
      <Field label="层级" value={formatZoom(effectiveZoom)} />
      {mode === "globe" ? (
        <Field label="视高" value={formatMeters(altitudeMeters ?? null)} />
      ) : null}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <span className="map-status-field">
      <span className="map-status-label">{label}</span>
      <strong className="map-status-value">{value}</strong>
    </span>
  );
}
