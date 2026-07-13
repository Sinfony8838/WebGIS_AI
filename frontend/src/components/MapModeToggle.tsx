/**
 * Toggle button placed in the top header that switches between the 3D
 * globe and 2D plane views.
 *
 * The button always shows the *destination* mode (i.e. "切到 2D" when
 * currently in globe, "切到 3D" when currently in plane) — this matches
 * the verb-oriented style most digital-earth platforms use.
 */
import type { ViewMode } from "../lib/viewMode";

type Props = {
  mode: ViewMode;
  busy?: boolean;
  onChange: (next: ViewMode) => void;
};

function GlobeIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <ellipse cx="12" cy="12" rx="4" ry="9" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path d="M3 12 H21 M5 7 H19 M5 17 H19" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function PlaneIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
      <rect x="3.5" y="4.5" width="17" height="13" rx="1.6" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M3.5 9 H20.5 M9 4.5 V17.5" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

export function MapModeToggle({ mode, busy, onChange }: Props) {
  const isGlobe = mode === "globe";
  const nextMode: ViewMode = isGlobe ? "plane" : "globe";
  const label = isGlobe ? "切到 2D" : "切到 3D";
  const ariaLabel = isGlobe ? "切换到 2D 平面地图" : "切换到 3D 数字地球";

  return (
    <button
      type="button"
      className={`map-mode-toggle ${isGlobe ? "is-globe" : "is-plane"}`}
      aria-label={ariaLabel}
      aria-pressed={isGlobe}
      title={ariaLabel}
      disabled={busy}
      onClick={() => onChange(nextMode)}
      data-testid="map-mode-toggle"
    >
      <span className="map-mode-toggle-icon" aria-hidden="true">
        {isGlobe ? <PlaneIcon /> : <GlobeIcon />}
      </span>
      <span className="map-mode-toggle-label">{label}</span>
    </button>
  );
}
