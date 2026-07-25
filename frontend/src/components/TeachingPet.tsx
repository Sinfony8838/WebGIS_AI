import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { JobRecord } from "../types";
import { getPoseById, type PetPoseId } from "../assets/teaching-pet/manifest";
import { deriveTeachingPetState, type PetState } from "./teachingPetState";

type Props = {
  busy: boolean;
  currentJob: JobRecord | null;
  minimized: boolean;
  isListening: boolean;
  size: "header" | "orb";
  /** True only after the floating orb crosses the drag threshold. */
  dragging?: boolean;
  /** Optional: override the default welcome wave on first expansion. */
  hasWelcomed?: boolean;
};

const SUCCESS_HOLD_MS = 1600;
const CELEBRATE_HOLD_MS = 1600;
const ERROR_HOLD_MS = 3000;
const SLEEP_DELAY_MS = 75000;
const IDLE_POSE_INTERVAL_MS = 30000;
const MIN_STABLE_MS = 450;
const PET_SPRITE_URL = new URL("../assets/teaching-pet/cloud-teacher-sprite.png", import.meta.url).href;

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return false;
    }
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) {
      return;
    }
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = (event: MediaQueryListEvent) => setReduced(event.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return reduced;
}

function useStablePetState(target: PetState, reducedMotion: boolean, forceImmediate = false): PetState {
  const [displayed, setDisplayed] = useState<PetState>(target);
  const lastChangeRef = useRef<number>(Date.now());
  const pendingRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wasForcedRef = useRef(false);

  const isImmediatePose = (pose: PetPoseId) =>
    pose === "success" || pose === "error" || pose === "sleep";

  useEffect(() => {
    if (pendingRef.current) {
      clearTimeout(pendingRef.current);
      pendingRef.current = null;
    }

    if (displayed.pose === target.pose) {
      return;
    }

    // Feedback poses (success / error) and sleep/wake transitions should be
    // immediate; the 450ms stability window only applies to work poses so
    // rapid stage switches do not cause flicker.
    if (reducedMotion || forceImmediate || wasForcedRef.current || isImmediatePose(target.pose) || isImmediatePose(displayed.pose)) {
      setDisplayed(target);
      lastChangeRef.current = Date.now();
      wasForcedRef.current = forceImmediate;
      return;
    }

    wasForcedRef.current = forceImmediate;

    const now = Date.now();
    const elapsed = now - lastChangeRef.current;
    const remaining = Math.max(0, MIN_STABLE_MS - elapsed);

    const apply = () => {
      setDisplayed(target);
      lastChangeRef.current = Date.now();
      pendingRef.current = null;
    };

    if (remaining === 0) {
      apply();
      return;
    }

    pendingRef.current = setTimeout(apply, remaining);

    return () => {
      if (pendingRef.current) {
        clearTimeout(pendingRef.current);
        pendingRef.current = null;
      }
    };
  }, [target, reducedMotion, forceImmediate]);

  return displayed;
}

/**
 * Track transient success/error feedback triggered by job state transitions.
 *
 * Returns the current `lastOutcome` value and clears it automatically after
 * the configured hold duration.
 */
function useOutcomeFeedback(
  busy: boolean,
  currentJob: JobRecord | null
): "success" | "celebrate" | "error" | null {
  const [outcome, setOutcome] = useState<"success" | "celebrate" | "error" | null>(() =>
    currentJob?.error ? "error" : null
  );
  const prevBusyRef = useRef(busy);
  const prevErrorRef = useRef(currentJob?.error);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const errorAppeared = Boolean(currentJob?.error) && !prevErrorRef.current;
    const finished = prevBusyRef.current && !busy;

    if (errorAppeared) {
      setOutcome("error");
    } else if (finished && !currentJob?.error) {
      setOutcome("success");
    }

    prevBusyRef.current = busy;
    prevErrorRef.current = currentJob?.error;
  }, [busy, currentJob?.error]);

  // Hold success/error feedback for the configured duration, then clear it.
  useEffect(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    if (outcome === "success") {
      timerRef.current = setTimeout(() => {
        setOutcome((current) => (current === "success" ? "celebrate" : current));
      }, SUCCESS_HOLD_MS);
    } else if (outcome === "celebrate") {
      timerRef.current = setTimeout(() => {
        setOutcome((current) => (current === "celebrate" ? null : current));
      }, CELEBRATE_HOLD_MS);
    } else if (outcome === "error") {
      timerRef.current = setTimeout(() => {
        setOutcome((current) => (current === "error" ? null : current));
      }, ERROR_HOLD_MS);
    }

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [outcome]);

  return outcome;
}

const IDLE_POSES: Array<{ pose: PetPoseId; label: string }> = [
  { pose: "idle", label: "在线" },
  { pose: "think", label: "静候思考" },
  { pose: "idea", label: "有了教学灵感" },
  { pose: "turn", label: "观察课堂" }
];

/** Rotate calm, source-sheet-only poses while the expanded pet is genuinely idle. */
function useIdlePoseCycle(active: boolean): PetState {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!active) {
      setIndex(0);
      return;
    }

    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % IDLE_POSES.length);
    }, IDLE_POSE_INTERVAL_MS);

    return () => window.clearInterval(timer);
  }, [active]);

  return IDLE_POSES[index];
}

/**
 * Track whether the pet has been minimized and idle long enough to nap.
 */
function useSleepReady(minimized: boolean, busy: boolean, isListening: boolean): boolean {
  const [ready, setReady] = useState(false);
  const minimizedAtRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const clear = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    if (!minimized || busy || isListening) {
      clear();
      minimizedAtRef.current = null;
      setReady(false);
      return;
    }

    const now = Date.now();
    const started = minimizedAtRef.current ?? now;
    minimizedAtRef.current = started;
    const elapsed = now - started;

    if (elapsed >= SLEEP_DELAY_MS) {
      setReady(true);
      return;
    }

    setReady(false);
    timerRef.current = setTimeout(() => {
      setReady(true);
      timerRef.current = null;
    }, SLEEP_DELAY_MS - elapsed);

    return clear;
  }, [minimized, busy, isListening]);

  return ready;
}

export function TeachingPet({
  busy,
  currentJob,
  minimized,
  isListening,
  size,
  dragging = false,
  hasWelcomed = true
}: Props) {
  const reducedMotion = useReducedMotion();
  const outcome = useOutcomeFeedback(busy, currentJob);
  const canSleep = useSleepReady(minimized, busy, isListening);
  const idlePose = useIdlePoseCycle(!busy && !minimized && !isListening && !dragging && !outcome && hasWelcomed);

  const targetState = useMemo(() => {
    // The source sheet has no separate walking frame. Keep its original idle
    // sticker and apply the walking motion class while the teacher drags it.
    if (dragging && minimized) {
      return { pose: "idle" as PetPoseId, label: "移动中" };
    }

    // First expansion shows a welcome wave before falling back to normal logic.
    if (!hasWelcomed && !minimized && !busy) {
      return { pose: "wave" as PetPoseId, label: "你好" };
    }

    const derived = deriveTeachingPetState({
      busy,
      currentJob,
      minimized,
      isListening,
      lastOutcome: outcome,
      canSleep
    });

    return derived.pose === "idle" && !minimized ? idlePose : derived;
  }, [busy, currentJob, minimized, isListening, outcome, canSleep, hasWelcomed, dragging, idlePose]);

  const displayedState = useStablePetState(targetState, reducedMotion, dragging);
  const pose = getPoseById(displayedState.pose);

  const sizeClass = size === "orb" ? "teaching-pet-orb" : "teaching-pet-header";
  const motionClass = reducedMotion ? "reduced" : "animated";

  const style = {
    backgroundImage: `url("${PET_SPRITE_URL}")`,
    "--pet-column": pose.column,
    "--pet-row": pose.row
  } as CSSProperties;

  return (
    <span
      className={`teaching-pet ${sizeClass} ${motionClass}${dragging ? " walking" : ""}`}
      aria-hidden="true"
      draggable={false}
      data-pose={displayedState.pose}
      data-testid={`teaching-pet-${size}`}
      style={style}
      title={pose.alt}
    />
  );
}

export { deriveTeachingPetState };
export type { PetState };
