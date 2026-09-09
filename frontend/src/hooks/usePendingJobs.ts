import { useEffect, useRef } from "react";
import { readPendingJobs, type PendingJob } from "../lib/pendingJobs";

/** Restore observation only after the authenticated user's project has loaded. */
export function usePendingJobs(userId: string, projectId: string, resume: (job: PendingJob) => void) {
  const resumeRef = useRef(resume);
  resumeRef.current = resume;
  useEffect(() => {
    for (const job of readPendingJobs(userId, projectId)) resumeRef.current(job);
  }, [userId, projectId]);
}
