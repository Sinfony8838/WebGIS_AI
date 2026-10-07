import { useCallback, useLayoutEffect, useRef } from "react";
import { fetchActiveTeachingMaps, fetchLayers, fetchLessonResources, fetchOutputs, fetchProject } from "../api";

export type ProjectSnapshot = {
  project: Awaited<ReturnType<typeof fetchProject>>;
  layers: Awaited<ReturnType<typeof fetchLayers>>;
  outputs: Awaited<ReturnType<typeof fetchOutputs>>;
  lessons: Awaited<ReturnType<typeof fetchLessonResources>>;
  teachingMaps: Awaited<ReturnType<typeof fetchActiveTeachingMaps>>;
};

/** Commit one read cohort only while its actor, project and batch still own it. */
export function useProjectSnapshotRefresh(
  userId: string,
  projectId: string,
  commit: (snapshot: ProjectSnapshot) => void,
  reset: (actorChanged: boolean) => void
) {
  const callbacks = useRef({ commit, reset });
  const scope = useRef({ userId, projectId, epoch: 0, mounted: false });
  const batch = useRef(0);
  const request = useRef<AbortController | null>(null);

  const invalidate = useCallback(() => {
    batch.current += 1;
    request.current?.abort();
    request.current = null;
  }, []);

  useLayoutEffect(() => { callbacks.current = { commit, reset }; }, [commit, reset]);
  useLayoutEffect(() => {
    scope.current.mounted = true;
    return () => {
      scope.current.mounted = false;
      scope.current.epoch += 1;
      invalidate();
    };
  }, [invalidate]);
  useLayoutEffect(() => {
    const actorChanged = scope.current.userId !== userId;
    if (actorChanged || scope.current.projectId !== projectId) {
      invalidate();
      scope.current.epoch += 1;
      scope.current.userId = userId;
      // The previous actor's selected project is never adopted by a new actor.
      scope.current.projectId = actorChanged ? "" : projectId;
      callbacks.current.reset(actorChanged);
    }
  }, [userId, projectId, invalidate]);

  const captureScope = useCallback((requestedProjectId: string) => {
    const epoch = scope.current.epoch;
    return () => scope.current.mounted && scope.current.userId === userId &&
      !!requestedProjectId && scope.current.projectId === requestedProjectId &&
      scope.current.epoch === epoch;
  }, [userId]);

  // Only the authenticated bootstrap/explicit project-selection path calls
  // this, before setProject renders. An ordinary refresh cannot select a project.
  const selectProject = useCallback((selectedProjectId: string) => {
    if (!scope.current.mounted || scope.current.userId !== userId || !selectedProjectId) return false;
    if (scope.current.projectId !== selectedProjectId) {
      invalidate();
      scope.current.epoch += 1;
      scope.current.projectId = selectedProjectId;
      callbacks.current.reset(false);
    }
    return true;
  }, [userId, invalidate]);

  const refresh = useCallback(async (requestedProjectId: string): Promise<ProjectSnapshot | null> => {
    const isScopeCurrent = captureScope(requestedProjectId);
    if (!isScopeCurrent()) return null;
    invalidate();
    const batchId = batch.current;
    const controller = new AbortController();
    request.current = controller;
    const isCurrent = () => isScopeCurrent() && batch.current === batchId &&
      request.current === controller && !controller.signal.aborted;
    try {
      const [project, layers, outputs, lessons, teachingMaps] = await Promise.all([
        fetchProject(requestedProjectId, controller.signal),
        fetchLayers(requestedProjectId, controller.signal),
        fetchOutputs(requestedProjectId, controller.signal),
        fetchLessonResources(requestedProjectId, controller.signal),
        fetchActiveTeachingMaps(requestedProjectId, controller.signal)
      ]);
      if (!isCurrent()) return null;
      if (project.project_id !== requestedProjectId) throw new Error("项目快照与当前项目不一致");
      const snapshot = { project, layers, outputs, lessons, teachingMaps };
      callbacks.current.commit(snapshot);
      return snapshot;
    } catch (error) {
      if (!isCurrent()) return null;
      throw error;
    } finally {
      if (request.current === controller) {
        // Cancel other members after a cohort failure; late 401s from that
        // cancelled cohort must not revoke a newer authenticated session.
        controller.abort();
        request.current = null;
      }
    }
  }, [userId, captureScope, invalidate]);

  return { refresh, selectProject, captureScope, invalidate };
}
