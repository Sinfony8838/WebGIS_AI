import type { JobRecord } from "../types";
import type { PetPoseId } from "../assets/teaching-pet/manifest";

export type PetState = {
  pose: PetPoseId;
  label: string;
};

export type TeachingPetInput = {
  busy: boolean;
  currentJob: JobRecord | null;
  minimized: boolean;
  isListening: boolean;
  /** Force a feedback pose; cleared by the caller after its timer expires. */
  lastOutcome: "success" | "celebrate" | "error" | null;
  /** True when the pet has been minimized and idle long enough to nap. */
  canSleep: boolean;
};

const DEFAULT_STATE: PetState = { pose: "idle", label: "在线" };

/**
 * Determine whether the current job is waiting for explicit teacher approval.
 */
export function requiresConfirmation(job: JobRecord | null): boolean {
  if (!job?.result) {
    return false;
  }
  return Boolean(job.result.requires_confirmation && job.result.confirmation_id);
}

/**
 * Determine whether the current execution stage involves map manipulation.
 */
export function isMapExecution(job: JobRecord | null): boolean {
  if (!job?.result?.actions_planned?.length) {
    return false;
  }
  return job.result.actions_planned.some((action) => action.requires_map_context);
}

/**
 * Find the currently running stage key, if any.
 */
export function getRunningStage(job: JobRecord | null): string | null {
  if (!job?.stages) {
    return null;
  }
  const running = Object.entries(job.stages).find(([, stage]) => stage.status === "running");
  return running?.[0] ?? null;
}

/**
 * Map the live teaching-agent state to a single pet pose.
 *
 * Priority (fixed):
 *   错误 > 等待确认 > 执行 > 规划/检索 > 完成/庆祝反馈 > 睡眠 > 空闲
 */
export function deriveTeachingPetState(input: TeachingPetInput): PetState {
  const { busy, currentJob, minimized, isListening, lastOutcome, canSleep } = input;

  // 1. Error feedback (highest priority).
  if (lastOutcome === "error") {
    return { pose: "error", label: "出错了" };
  }

  if (lastOutcome === "celebrate") {
    return { pose: "celebrate", label: "完成，继续加油" };
  }

  // 2. Waiting for teacher confirmation.
  if (requiresConfirmation(currentJob)) {
    return { pose: "confirm", label: "高风险操作待确认" };
  }

  // 3. Execution stage.
  if (busy) {
    const runningStage = getRunningStage(currentJob);

    if (runningStage === "execution") {
      return isMapExecution(currentJob)
        ? { pose: "map", label: "正在执行地图操作" }
        : { pose: "laptop", label: "正在执行操作" };
    }

    if (runningStage === "routing" || runningStage === "retrieval") {
      return { pose: "search", label: "正在检索" };
    }

    if (runningStage === "planning") {
      return { pose: "tablet", label: "正在规划" };
    }

    if (runningStage === "grounding" || runningStage === "artifacts") {
      return { pose: "explain", label: "正在整理答复" };
    }

    if (runningStage === "confirmation") {
      return { pose: "confirm", label: "等待确认" };
    }

    // Any other busy state that has not been mapped falls back to thinking.
    return { pose: "think", label: "正在思考" };
  }

  // 4. Completion feedback.
  if (lastOutcome === "success") {
    return { pose: "success", label: "完成" };
  }

  // 5. Sleep only when minimized and truly idle.
  if (minimized && canSleep && !isListening) {
    return { pose: "sleep", label: "休息中" };
  }

  // 6. Idle / ready.
  return DEFAULT_STATE;
}
