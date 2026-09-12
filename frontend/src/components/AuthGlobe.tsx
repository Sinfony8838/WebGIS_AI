import { geoGraticule, geoOrthographic, geoPath } from "d3-geo";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import land from "../assets/earth/ne_110m_land.json";

type Rotation = [number, number, number];

const INITIAL_ROTATION: Rotation = [-105, -30, 0];
const AUTO_ROTATION_DEGREES_PER_SECOND = 2.4;
const GRATICULE = geoGraticule().step([30, 30])();

function clampLatitude(value: number): number {
  return Math.max(-75, Math.min(75, value));
}

export function AuthGlobe({ reducedMotion }: { reducedMotion: boolean }) {
  const [rotation, setRotationState] = useState<Rotation>(INITIAL_ROTATION);
  const [dragging, setDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const rotationRef = useRef<Rotation>(INITIAL_ROTATION);
  const dragRef = useRef<{
    pointerId: number;
    x: number;
    y: number;
    rotation: Rotation;
  } | null>(null);
  const resumeAtRef = useRef(0);

  const setRotation = useCallback((next: Rotation) => {
    rotationRef.current = next;
    setRotationState(next);
  }, []);

  useEffect(() => {
    if (reducedMotion) return undefined;
    let frame = 0;
    let previous = performance.now();
    let accumulated = 0;

    const tick = (now: number) => {
      const elapsed = Math.min(64, Math.max(0, now - previous));
      previous = now;
      if (
        !document.hidden
        && containerRef.current?.offsetParent !== null
        && !dragRef.current
        && now >= resumeAtRef.current
      ) {
        accumulated += elapsed;
        // Thirty redraws per second are smooth enough for this decorative
        // globe and substantially cheaper than rebuilding paths at 60 fps.
        if (accumulated >= 32) {
          const current = rotationRef.current;
          setRotation([
            current[0] + AUTO_ROTATION_DEGREES_PER_SECOND * accumulated / 1000,
            current[1],
            current[2]
          ]);
          accumulated = 0;
        }
      }
      frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [reducedMotion, setRotation]);

  const paths = useMemo(() => {
    const projection = geoOrthographic()
      .translate([260, 260])
      .scale(202)
      .clipAngle(90)
      .precision(0.5)
      .rotate(rotation);
    const path = geoPath(projection);
    return {
      sphere: path({ type: "Sphere" }) || "",
      graticule: path(GRATICULE) || "",
      land: path(land) || ""
    };
  }, [rotation]);

  const finishDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    dragRef.current = null;
    resumeAtRef.current = performance.now() + 1400;
    setDragging(false);
  };

  return (
    <div
      ref={containerRef}
      className={`auth-globe-wrap anim-rise${dragging ? " is-dragging" : ""}`}
      aria-hidden="true"
      data-testid="auth-globe"
      onDoubleClick={() => {
        setRotation(INITIAL_ROTATION);
        resumeAtRef.current = performance.now() + 1400;
      }}
      onPointerDown={(event) => {
        // Some browsers/test environments omit `button` for touch/pen
        // pointers; only an explicit secondary button should be rejected.
        if (typeof event.button === "number" && event.button > 0) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture?.(event.pointerId);
        dragRef.current = {
          pointerId: event.pointerId,
          x: event.clientX,
          y: event.clientY,
          rotation: [...rotationRef.current] as Rotation
        };
        setDragging(true);
      }}
      onPointerMove={(event) => {
        const start = dragRef.current;
        if (!start || start.pointerId !== event.pointerId) return;
        event.preventDefault();
        setRotation([
          start.rotation[0] + (event.clientX - start.x) * 0.24,
          clampLatitude(start.rotation[1] - (event.clientY - start.y) * 0.2),
          0
        ]);
      }}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
    >
      <svg
        className="auth-globe-svg"
        viewBox="0 0 520 520"
        focusable="false"
        data-rotation-lon={rotation[0].toFixed(2)}
        data-rotation-lat={rotation[1].toFixed(2)}
      >
        <defs>
          <radialGradient id="auth-ocean" cx="36%" cy="30%" r="82%">
            <stop offset="0%" className="auth-ocean-inner" />
            <stop offset="100%" className="auth-ocean-outer" />
          </radialGradient>
          <filter id="auth-globe-shadow" x="-25%" y="-25%" width="150%" height="150%">
            <feDropShadow dx="0" dy="12" stdDeviation="14" floodOpacity=".12" />
          </filter>
        </defs>
        <g className="auth-globe-halo" fill="none">
          <circle cx="260" cy="260" r="218" />
          <circle cx="260" cy="260" r="232" />
        </g>
        <g className="auth-globe-orbit" fill="none" transform="rotate(-18 260 260)">
          <ellipse cx="260" cy="260" rx="246" ry="66" />
        </g>
        <g filter="url(#auth-globe-shadow)">
          <path className="auth-globe-ocean" d={paths.sphere} />
          <path className="auth-globe-grid" d={paths.graticule} />
          <path className="auth-globe-land" d={paths.land} />
          <path className="auth-globe-rim" d={paths.sphere} />
        </g>
      </svg>
      <span className="auth-globe-drag-hint">拖动地球探索</span>
    </div>
  );
}
