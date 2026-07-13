import { useEffect, useRef, useState } from "react";

import { buildWorkflowStreamUrl, fetchWorkflow } from "../api";
import type {
  WorkflowArtifactRecord,
  WorkflowError,
  WorkflowEvent,
  WorkflowEventType,
  WorkflowRecord,
  WorkflowStepRecord,
  WorkflowStatus
} from "../types";

export type WorkflowStreamState = {
  workflowId: string;
  status: WorkflowStatus | "idle";
  intent: string;
  steps: WorkflowStepRecord[];
  artifacts: WorkflowArtifactRecord[];
  error: WorkflowError | null;
  lastEvent: WorkflowEvent | null;
};

const INITIAL_STATE: WorkflowStreamState = {
  workflowId: "",
  status: "idle",
  intent: "",
  steps: [],
  artifacts: [],
  error: null,
  lastEvent: null
};

const TERMINAL_EVENTS: ReadonlySet<WorkflowEventType> = new Set([
  "workflow_success",
  "workflow_error",
  "stream_idle_timeout"
]);

function mergeStep(existing: WorkflowStepRecord[], next: WorkflowStepRecord): WorkflowStepRecord[] {
  const found = existing.findIndex((step) => step.id === next.id);
  if (found < 0) {
    return [...existing, next];
  }
  const copy = existing.slice();
  copy[found] = { ...copy[found], ...next };
  return copy;
}

function mergeArtifact(
  existing: WorkflowArtifactRecord[],
  next: WorkflowArtifactRecord
): WorkflowArtifactRecord[] {
  if (existing.find((item) => item.artifact_id === next.artifact_id)) {
    return existing;
  }
  return [...existing, next];
}

/**
 * Subscribe to /workflow/{id}/stream and surface a normalized state slice.
 * Pass an empty workflow id to disconnect / reset.
 */
export function useWorkflowStream(workflowId: string): WorkflowStreamState {
  const [state, setState] = useState<WorkflowStreamState>(INITIAL_STATE);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!workflowId) {
      setState(INITIAL_STATE);
      return;
    }

    let cancelled = false;
    setState({ ...INITIAL_STATE, workflowId, status: "pending" });

    // Hydrate initial state with whatever is already persisted on the server.
    fetchWorkflow(workflowId)
      .then((record) => {
        if (cancelled) {
          return;
        }
        setState((prev) => ({
          ...prev,
          workflowId,
          intent: record.intent || prev.intent,
          status: (record.status as WorkflowStatus) || prev.status,
          steps: record.steps || [],
          artifacts: record.artifacts || [],
          error: record.error || null
        }));
      })
      .catch(() => {
        // ignore — events will populate the state
      });

    const url = buildWorkflowStreamUrl(workflowId);
    const source = new EventSource(url);
    sourceRef.current = source;

    function handleEvent(eventType: WorkflowEventType, raw: MessageEvent<string>) {
      try {
        const payload = raw.data ? (JSON.parse(raw.data) as Record<string, unknown>) : {};
        const event: WorkflowEvent = { type: eventType, payload };
        setState((prev) => applyEvent(prev, event, workflowId));
        if (TERMINAL_EVENTS.has(eventType)) {
          source.close();
          sourceRef.current = null;
        }
      } catch {
        // ignore malformed payloads — keep the stream open
      }
    }

    const eventTypes: WorkflowEventType[] = [
      "workflow_created",
      "workflow_started",
      "step_started",
      "step_progress",
      "step_success",
      "step_error",
      "artifact_ready",
      "workflow_success",
      "workflow_error",
      "stream_idle_timeout",
      "ping"
    ];
    eventTypes.forEach((type) => source.addEventListener(type, (event) => handleEvent(type, event as MessageEvent<string>)));

    source.onerror = () => {
      // Browser will retry automatically; we just note we lost connectivity.
      setState((prev) => ({ ...prev }));
    };

    return () => {
      cancelled = true;
      source.close();
      sourceRef.current = null;
    };
  }, [workflowId]);

  return state;
}

function applyEvent(
  state: WorkflowStreamState,
  event: WorkflowEvent,
  expectedId: string
): WorkflowStreamState {
  const incomingId = (event.payload?.workflow_id as string | undefined) || state.workflowId;
  if (incomingId && incomingId !== expectedId) {
    return state;
  }
  let next: WorkflowStreamState = { ...state, lastEvent: event };

  switch (event.type) {
    case "workflow_created":
    case "workflow_started": {
      const wf = (event.payload?.workflow as Partial<WorkflowRecord>) || null;
      if (wf) {
        next = {
          ...next,
          intent: wf.intent || next.intent,
          status: (wf.status as WorkflowStatus) || "running"
        };
      } else {
        next = { ...next, status: "running" };
      }
      break;
    }
    case "step_started":
    case "step_progress":
    case "step_success":
    case "step_error": {
      const step = event.payload?.step as WorkflowStepRecord | undefined;
      if (step) {
        next = { ...next, steps: mergeStep(next.steps, step) };
      }
      if (event.type === "step_error") {
        const err = event.payload?.error as WorkflowError | undefined;
        if (err) {
          next = { ...next, error: err };
        }
      }
      break;
    }
    case "artifact_ready": {
      const artifact = event.payload?.artifact as WorkflowArtifactRecord | undefined;
      if (artifact) {
        next = { ...next, artifacts: mergeArtifact(next.artifacts, artifact) };
      }
      break;
    }
    case "workflow_success": {
      const wf = event.payload?.workflow as Partial<WorkflowRecord> | undefined;
      const arts = (event.payload?.artifacts as WorkflowArtifactRecord[] | undefined) || [];
      next = {
        ...next,
        status: "success",
        intent: wf?.intent || next.intent,
        steps: wf?.steps || next.steps,
        artifacts: arts.length ? arts : next.artifacts,
        error: null
      };
      break;
    }
    case "workflow_error": {
      const err = (event.payload?.error as WorkflowError | undefined) || null;
      next = { ...next, status: "error", error: err };
      break;
    }
    case "stream_idle_timeout": {
      next = { ...next, status: state.status === "idle" ? "error" : state.status };
      break;
    }
    case "ping":
    default:
      break;
  }
  return next;
}
