import { useEffect, useRef, useState } from "react";

import { buildWorkflowStreamUrl, fetchCurrentUser, fetchWorkflow } from "../api";
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
  "workflow_error"
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
export function useWorkflowStream(workflowId: string, projectId = ""): WorkflowStreamState {
  const [state, setState] = useState<WorkflowStreamState>(INITIAL_STATE);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!workflowId) {
      setState(INITIAL_STATE);
      return;
    }

    let cancelled = false;
    let stopped = false;
    let disconnected = false;
    let source: EventSource | null = null;
    let pollTimer: number | undefined;
    let request: { controller: AbortController; events: WorkflowEvent[]; deadline: number } | null = null;
    setState({ ...INITIAL_STATE, workflowId, status: "pending" });

    function closeSource() {
      source?.close();
      source = null;
      sourceRef.current = null;
    }

    function stopObservation() {
      stopped = true;
      window.clearTimeout(pollTimer);
      pollTimer = undefined;
      closeSource();
    }

    function schedulePoll() {
      if (cancelled || stopped || pollTimer !== undefined) return;
      pollTimer = window.setTimeout(() => {
        pollTimer = undefined;
        querySnapshot();
      }, 3000);
    }

    function querySnapshot() {
      if (cancelled || stopped || request) return;
      window.clearTimeout(pollTimer);
      pollTimer = undefined;
      const pending = { controller: new AbortController(), events: [] as WorkflowEvent[], deadline: 0 };
      request = pending;
      pending.deadline = window.setTimeout(() => {
        if (request !== pending) return;
        request = null;
        pending.controller.abort();
        disconnected = true;
        schedulePoll();
      }, 15000);
      // Every retry is a GET of this original ID; no submission/replay path.
      void fetchWorkflow(workflowId, pending.controller.signal)
        .then((record) => {
          if (cancelled || request !== pending) return;
          if (record.workflow_id !== workflowId || (projectId && record.project_id !== projectId)) {
            stopObservation();
            return;
          }
          const hydrate = (previous: WorkflowStreamState): WorkflowStreamState => {
            const snapshot: WorkflowStreamState = {
              ...previous, workflowId, intent: record.intent || previous.intent,
              status: record.status as WorkflowStatus, steps: record.steps || [],
              artifacts: record.artifacts || [], error: record.error || null
            };
            return pending.events.reduce((next, event) => applyEvent(next, event, workflowId), snapshot);
          };
          setState(hydrate);
          const status = hydrate(INITIAL_STATE).status;
          if (["success", "error", "cancelled"].includes(status)) {
            stopObservation();
          } else if (!stopped) {
            disconnected = false;
            openSource();
          }
        })
        .catch(() => {
          if (cancelled || request !== pending) return;
          // A live SSE may still supply results after an initial GET failure.
          disconnected = true;
        })
        .finally(() => {
          window.clearTimeout(pending.deadline);
          if (request !== pending) return;
          request = null;
          if (disconnected) schedulePoll();
        });
    }

    function handleEvent(eventType: WorkflowEventType, raw: MessageEvent<string>, sender: EventSource) {
      if (cancelled || stopped || source !== sender) return;
      try {
        const payload = raw.data ? (JSON.parse(raw.data) as Record<string, unknown>) : {};
        const workflow = payload.workflow as Partial<WorkflowRecord> | undefined;
        if ((payload.workflow_id && payload.workflow_id !== workflowId)
          || (workflow?.workflow_id && workflow.workflow_id !== workflowId)
          || (projectId && workflow?.project_id && workflow.project_id !== projectId)) return;
        const event: WorkflowEvent = { type: eventType, payload };
        request?.events.push(event);
        setState((prev) => applyEvent(prev, event, workflowId));
        if (TERMINAL_EVENTS.has(eventType)) {
          stopObservation();
        } else if (eventType === "stream_idle_timeout") {
          disconnected = true;
          closeSource();
          querySnapshot();
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
    function openSource() {
      if (cancelled || stopped || source) return;
      const sender = new EventSource(buildWorkflowStreamUrl(workflowId), { withCredentials: true });
      source = sender;
      sourceRef.current = sender;
      eventTypes.forEach((type) => sender.addEventListener(type, (event) => handleEvent(type, event as MessageEvent<string>, sender)));
      sender.onerror = () => {
        if (cancelled || stopped || source !== sender) return;
        disconnected = true;
        closeSource();
        void fetchCurrentUser().catch(() => undefined);
        querySnapshot();
      };
    }

    querySnapshot();
    openSource();

    return () => {
      cancelled = true;
      window.clearTimeout(pollTimer);
      if (request) {
        window.clearTimeout(request.deadline);
        request.controller.abort();
        request = null;
      }
      closeSource();
    };
  }, [workflowId, projectId]);

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
  if (["success", "error", "cancelled"].includes(state.status)
    && !TERMINAL_EVENTS.has(event.type)) return next;

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
      // The executor attaches the full record so a teacher-initiated cancel
      // (record.status "cancelled") is distinguishable from a real failure.
      const wf = event.payload?.workflow as Partial<WorkflowRecord> | undefined;
      next = {
        ...next,
        status: (wf?.status as WorkflowStatus) || "error",
        steps: wf?.steps || next.steps,
        artifacts: wf?.artifacts || next.artifacts,
        error: err
      };
      break;
    }
    case "stream_idle_timeout": {
      // Transport inactivity is not a workflow terminal; GET reconciliation
      // determines whether the original run is still active or completed.
      break;
    }
    case "ping":
    default:
      break;
  }
  return next;
}
