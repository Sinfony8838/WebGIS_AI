import type { JobRecord, ObservedUiAction, UiObservation } from "../types";

type Options = {
  isCurrent: () => boolean;
  recovered: boolean;
  sessionId: string;
  apply: (action: ObservedUiAction) => Promise<void>;
  acknowledge: (jobId: string, observation: UiObservation) => Promise<unknown>;
};

/** A reconnect retries only delivery of the receipt, never the UI mutation. */
export class UiActionReceiver {
  private actions = new Map<string, { applying: boolean; observation?: UiObservation; acknowledged: boolean }>();

  async receive(job: JobRecord, options: Options): Promise<void> {
    if (job.status !== "running" && job.status !== "queued") return;
    for (const action of job.ui_actions || []) {
      if (action.status !== "pending" || !options.isCurrent() || action.project_id !== job.project_id) continue;
      const key = `${job.job_id}:${action.action_id}`;
      let state = this.actions.get(key);
      if (state?.applying || state?.acknowledged) continue;
      if (!state) {
        state = { applying: true, acknowledged: false };
        this.actions.set(key, state);
        const observation: UiObservation = { action_id: action.action_id, project_id: job.project_id, session_id: action.session_id, status: "applied", detail: "界面状态已应用" };
        if (options.recovered || action.session_id !== options.sessionId || (action.expires_at !== undefined && action.expires_at * 1000 < Date.now())) {
          observation.status = "unconfirmed";
          observation.detail = options.recovered ? "恢复任务时不重放界面操作" : "课堂已变化或动作已过期，未应用旧动作";
        } else {
          try {
            await options.apply(action);
          } catch (error) {
            observation.status = "failed";
            observation.detail = error instanceof Error ? error.message : "界面应用失败";
          }
        }
        state.observation = observation;
        state.applying = false;
      }
      if (!options.isCurrent() || !state.observation) continue;
      try {
        await options.acknowledge(job.job_id, state.observation);
        state.acknowledged = true;
      } catch {
        // A later snapshot retries this exact receipt without replaying apply().
      }
    }
  }
}
