import type { JobRecord } from "../types";

export type JobSubscription = { close: () => void };
type JobSource = Pick<EventSource, "addEventListener" | "close">;
type Options = {
  createSource: () => JobSource;
  fetchJob: (jobId: string, signal: AbortSignal) => Promise<JobRecord>;
  onJob: (job: JobRecord) => void;
  onRecovering: () => void;
};

/** Recover observation of the same job; never resubmit an operation after a lost stream. */
export function subscribeJob(jobId: string, options: Options): JobSubscription {
  const source = options.createSource();
  let closed = false;
  let polling = false;
  let revision = 0;
  let failures = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let requestTimeout: ReturnType<typeof setTimeout> | undefined;

  function close() {
    closed = true;
    source.close();
    clearTimeout(timer);
    clearTimeout(requestTimeout);
    controller?.abort();
  }
  function recover() {
    if (closed || polling) return;
    polling = true;
    source.close();
    options.onRecovering();
  }
  function accept(value: unknown): boolean {
    const job = value as JobRecord | null;
    if (!job || job.job_id !== jobId || typeof job.status !== "string" ||
        typeof job.project_id !== "string" || !job.stages || !Array.isArray(job.steps)) return false;
    revision += 1;
    if (job.status === "completed" || job.status === "failed") close();
    options.onJob(job);
    return true;
  }
  function schedule(delay: number) {
    clearTimeout(timer);
    if (!closed) timer = setTimeout(() => { void reconcile(); }, delay);
  }
  async function reconcile() {
    if (closed || controller) return;
    const observedRevision = revision;
    const request = new AbortController();
    controller = request;
    requestTimeout = setTimeout(() => request.abort(), 10000);
    try {
      const job = await options.fetchJob(jobId, request.signal);
      if (closed) return;
      // A stream update received during the GET is newer than its snapshot.
      if (observedRevision === revision && !accept(job)) throw new Error("Invalid job snapshot");
      failures = 0;
    } catch {
      if (!closed) { failures += 1; recover(); }
    } finally {
      clearTimeout(requestTimeout);
      controller = undefined;
      schedule(polling ? Math.min(3000 * 2 ** Math.min(failures, 3), 15000) : 15000);
    }
  }
  source.addEventListener("job", (event) => {
    if (closed || polling) return;
    try {
      if (!accept(JSON.parse((event as MessageEvent).data))) throw new Error("Invalid job event");
      if (!controller) schedule(15000);
    } catch {
      recover();
      schedule(0);
    }
  });
  source.addEventListener("error", () => {
    if (closed) return;
    recover();
    schedule(0);
  });
  // A silent stream can miss its terminal event without dispatching onerror.
  schedule(15000);
  return { close };
}
