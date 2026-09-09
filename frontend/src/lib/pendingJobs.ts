import type { AssistantTab } from "../types";

export type PendingJob = { jobId: string; tab: AssistantTab };
const key = (userId: string, projectId: string) => `geobot.pending-jobs.v1:${encodeURIComponent(userId)}:${encodeURIComponent(projectId)}`;

export function readPendingJobs(userId: string, projectId: string): PendingJob[] {
  if (!userId || !projectId) return [];
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(key(userId, projectId)) || "[]");
    if (!Array.isArray(raw)) return [];
    const unique = new Map<string, PendingJob>();
    for (const item of raw) {
      if (item && typeof item.jobId === "string" && /^[a-zA-Z0-9_-]{1,128}$/.test(item.jobId)
          && ["teaching", "interaction"].includes(item.tab)) {
        unique.set(item.jobId, { jobId: item.jobId, tab: item.tab });
      }
    }
    return [...unique.values()];
  } catch { return []; }
}

export function rememberPendingJob(userId: string, projectId: string, job: PendingJob): void {
  if (!userId || !projectId) return;
  const jobs = readPendingJobs(userId, projectId).filter(item => item.jobId !== job.jobId);
  try { localStorage.setItem(key(userId, projectId), JSON.stringify([...jobs, job])); } catch { /* Live observation still works without storage. */ }
}

export function forgetPendingJob(userId: string, projectId: string, jobId: string): void {
  const jobs = readPendingJobs(userId, projectId).filter(item => item.jobId !== jobId);
  try {
    if (jobs.length) localStorage.setItem(key(userId, projectId), JSON.stringify(jobs));
    else localStorage.removeItem(key(userId, projectId));
  } catch { /* Storage may be disabled. */ }
}
