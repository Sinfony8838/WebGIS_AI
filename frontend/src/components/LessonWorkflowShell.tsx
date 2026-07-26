import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  addSessionObservation,
  applyLessonScene,
  captureLessonScene,
  closeSessionQuestion,
  createClassSession,
  endClassSession,
  enterSessionStage,
  fetchJob,
  fetchLesson,
  fetchLessons,
  importLesson,
  launchSessionQuestion,
  updateLesson
} from "../api";
import type {
  ClassSessionRecord,
  LayersResponse,
  LessonRecord,
  LessonStage,
  ObservationVerdict,
  ProjectRecord,
  SceneSnapshot,
  TeachingContext
} from "../types";
import { ClassRunPanel } from "./ClassRunPanel";
import { LessonPanel } from "./LessonPanel";
import { QuizOverlay } from "./QuizOverlay";
import { ReportPanel } from "./ReportPanel";
import { VisualQueryPopup, type VisualizationItem } from "./VisualQueryPopup";

type LessonMode = "off" | "prep" | "teach" | "review";

type Props = {
  project: (ProjectRecord & { status?: string }) | null;
  layerState: LayersResponse | null;
  busy?: boolean;
  onRefresh: () => void | Promise<void>;
  /** 底部状态栏（经纬度/层级），与课前/课中/课后按钮同坞排布，避免相互压盖。 */
  statusBar?: ReactNode;
  /** 每次递增时打开课堂工作流：有进行中课堂则展开课中面板，否则打开课前备课。 */
  openSignal?: number;
  /** 课堂工作流状态（lesson/session/stage/phase）变化时上报给 App，随助教请求发往后端。 */
  onTeachingContextChange?: (ctx: TeachingContext | null) => void;
  /** 课中一键把预设追问派发给教学智能体。 */
  onAssistantPrompt?: (prompt: string) => void;
};

function currentLayerSnapshot(layerState: LayersResponse | null): SceneSnapshot {
  const visibility: Record<string, boolean> = {};
  layerState?.items.forEach((layer) => {
    visibility[layer.layer_id] = layer.visible;
  });
  return {
    basemap_id: layerState?.base_map?.id || "",
    view: layerState?.view?.center
      ? { center: layerState.view.center, zoom: layerState.view.zoom }
      : undefined,
    layer_visibility: visibility,
    templates: layerState?.enabled_templates || []
  };
}

async function waitForLessonImport(jobId: string): Promise<LessonRecord | null> {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const job = await fetchJob(jobId);
    if (job.status === "completed") {
      return (job.result?.lesson as LessonRecord | undefined) || null;
    }
    if (job.status === "failed") {
      throw new Error(job.error || "Lesson import failed");
    }
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
  throw new Error("Lesson import timed out");
}

export function LessonWorkflowShell({
  project,
  layerState,
  busy = false,
  onRefresh,
  statusBar,
  openSignal = 0,
  onTeachingContextChange,
  onAssistantPrompt
}: Props) {
  const [lessonMode, setLessonMode] = useState<LessonMode>("off");
  const [lessons, setLessons] = useState<LessonRecord[]>([]);
  const [activeLesson, setActiveLesson] = useState<LessonRecord | null>(null);
  const [activeSession, setActiveSession] = useState<ClassSessionRecord | null>(null);
  const [studentJoinUrl, setStudentJoinUrl] = useState("");
  const [stageEnteredAt, setStageEnteredAt] = useState<number | null>(null);
  const [quizVisible, setQuizVisible] = useState(false);
  const [panelCollapsed, setPanelCollapsed] = useState(true);
  const [localBusy, setLocalBusy] = useState(false);
  const [error, setError] = useState("");
  const [visualQueryDismissed, setVisualQueryDismissed] = useState(false);
  const visualQuerySignatureRef = useRef("");

  // 侧栏“上课模式”入口：有进行中课堂直接展开课中面板，否则进入课前备课。
  useEffect(() => {
    if (!openSignal) {
      return;
    }
    setPanelCollapsed(false);
    setLessonMode((previous) => {
      if (activeSession && activeSession.status === "running") {
        return "teach";
      }
      return previous === "prep" ? previous : "prep";
    });
    // openSignal 是单调递增的触发器，activeSession 仅作为打开瞬间的判据。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openSignal]);

  // 把课堂工作流状态上报给 App：备课=course_prep、上课中=in_class、复盘=post_class。
  // session_id 在课堂结束后仍保留（课后复盘需要用它读取真实课堂记录）。
  useEffect(() => {
    if (!onTeachingContextChange) {
      return;
    }
    if (!activeLesson && !activeSession) {
      onTeachingContextChange(null);
      return;
    }
    const running = activeSession?.status === "running";
    // phase 以课堂事实为准：只要班课在进行就是 in_class（即使教师收起了课中面板）；
    // 班课已结束则进入 post_class；否则跟随面板模式。
    const phase: TeachingContext["phase"] = running
      ? "in_class"
      : lessonMode === "prep"
        ? "course_prep"
        : activeSession || lessonMode === "review"
          ? "post_class"
          : "";
    onTeachingContextChange({
      lesson_id: activeLesson?.lesson_id || undefined,
      session_id: activeSession?.session_id || undefined,
      stage_id: running ? activeSession?.current_stage_id || undefined : undefined,
      phase
    });
  }, [lessonMode, activeLesson, activeSession, onTeachingContextChange]);

  const visualQueryLayer = useMemo(() => {
    return (
      layerState?.items
        .filter((layer) => layer.visible)
        .find((layer) => Boolean((layer.metadata || {}).visualization)) || null
    );
  }, [layerState]);

  useEffect(() => {
    const signature = visualQueryLayer
      ? `${visualQueryLayer.layer_id}:${Array.isArray((visualQueryLayer.data as { features?: unknown[] }).features) ? (visualQueryLayer.data as { features: unknown[] }).features.length : 0}`
      : "";
    if (signature && signature !== visualQuerySignatureRef.current) {
      visualQuerySignatureRef.current = signature;
      setVisualQueryDismissed(false);
    }
  }, [visualQueryLayer]);

  const loadLessons = useCallback(async () => {
    try {
      const payload = await fetchLessons();
      setLessons(payload.items);
      setActiveLesson((previous) => {
        if (previous && payload.items.some((item) => item.lesson_id === previous.lesson_id)) {
          return previous;
        }
        return payload.items[0] || null;
      });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  useEffect(() => {
    void loadLessons();
  }, [loadLessons]);

  const runWithBusy = useCallback(async (operation: () => Promise<void>) => {
    setLocalBusy(true);
    setError("");
    try {
      await operation();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLocalBusy(false);
    }
  }, []);

  const selectLesson = useCallback(
    async (lessonId: string) => {
      await runWithBusy(async () => {
        const lesson = await fetchLesson(lessonId);
        setActiveLesson(lesson);
      });
    },
    [runWithBusy]
  );

  const applyScene = useCallback(
    async (stageId: string, viaSession = false) => {
      if (!project || !activeLesson) return;
      await runWithBusy(async () => {
        if (viaSession && activeSession) {
          await enterSessionStage(activeSession.session_id, stageId);
          setActiveSession((previous) => (previous ? { ...previous, current_stage_id: stageId } : previous));
          setStageEnteredAt(Date.now());
        } else {
          await applyLessonScene(activeLesson.lesson_id, stageId, project.project_id);
        }
        await onRefresh();
      });
    },
    [activeLesson, activeSession, onRefresh, project, runWithBusy]
  );

  const captureScene = useCallback(
    async (stageId: string): Promise<SceneSnapshot | null> => {
      if (!activeLesson) return null;
      let snapshot: SceneSnapshot | null = null;
      await runWithBusy(async () => {
        snapshot = currentLayerSnapshot(layerState);
        await captureLessonScene(activeLesson.lesson_id, stageId, snapshot);
        const lesson = await fetchLesson(activeLesson.lesson_id);
        setActiveLesson(lesson);
        setLessons((previous) => previous.map((item) => (item.lesson_id === lesson.lesson_id ? lesson : item)));
      });
      return snapshot;
    },
    [activeLesson, layerState, runWithBusy]
  );

  const saveStages = useCallback(
    async (stages: LessonStage[]) => {
      if (!activeLesson) return;
      await runWithBusy(async () => {
        const updated = await updateLesson(activeLesson.lesson_id, { stages });
        setActiveLesson(updated);
        setLessons((previous) => previous.map((item) => (item.lesson_id === updated.lesson_id ? updated : item)));
      });
    },
    [activeLesson, runWithBusy]
  );

  const importLessonText = useCallback(
    async (text: string) => {
      if (!project) return;
      await runWithBusy(async () => {
        const { job_id } = await importLesson(project.project_id, text);
        const lesson = await waitForLessonImport(job_id);
        await loadLessons();
        if (lesson?.lesson_id) {
          const fetched = await fetchLesson(lesson.lesson_id);
          setActiveLesson(fetched);
        }
      });
    },
    [loadLessons, project, runWithBusy]
  );

  const startClass = useCallback(async () => {
    if (!project || !activeLesson) return;
    await runWithBusy(async () => {
      const response = await createClassSession(activeLesson.lesson_id, project.project_id);
      setActiveSession(response.session);
      setStudentJoinUrl(response.student_join_url || "");
      setLessonMode("teach");
      const firstStage = activeLesson.stages[0];
      if (firstStage) {
        await applyScene(firstStage.stage_id, true);
      }
    });
  }, [activeLesson, applyScene, project, runWithBusy]);

  const endSession = useCallback(async () => {
    if (!activeSession) return;
    await runWithBusy(async () => {
      const response = await endClassSession(activeSession.session_id);
      setActiveSession(response.session);
      setQuizVisible(false);
      setLessonMode("review");
      await onRefresh();
    });
  }, [activeSession, onRefresh, runWithBusy]);

  const launchQuestion = useCallback(
    async (questionId: string, stageId: string) => {
      if (!activeSession) return;
      await runWithBusy(async () => {
        await launchSessionQuestion(activeSession.session_id, { question_id: questionId, stage_id: stageId });
        setQuizVisible(true);
      });
    },
    [activeSession, runWithBusy]
  );

  const launchAdhocQuestion = useCallback(
    async (text: string, options: string[]) => {
      if (!activeSession) return;
      await runWithBusy(async () => {
        await launchSessionQuestion(activeSession.session_id, {
          stage_id: activeSession.current_stage_id,
          adhoc: { text, options }
        });
        setQuizVisible(true);
      });
    },
    [activeSession, runWithBusy]
  );

  const closeQuestion = useCallback(async () => {
    if (!activeSession) return;
    await runWithBusy(async () => {
      await closeSessionQuestion(activeSession.session_id);
      setQuizVisible(false);
    });
  }, [activeSession, runWithBusy]);

  const recordObservation = useCallback(
    (verdict: ObservationVerdict, tag: string, note: string, questionId: string) => {
      if (!activeSession) return;
      void runWithBusy(async () => {
        await addSessionObservation(activeSession.session_id, {
          stage_id: activeSession.current_stage_id,
          question_id: questionId,
          verdict,
          tag,
          note
        });
      });
    },
    [activeSession, runWithBusy]
  );

  const workflowBusy = busy || localBusy;
  const teachPanelVisible = lessonMode === "teach" && Boolean(activeSession) && Boolean(activeLesson);

  return (
    <>
      {teachPanelVisible && activeSession && activeLesson ? (
        <ClassRunPanel
          lesson={activeLesson}
          session={activeSession}
          currentStageId={activeSession.current_stage_id}
          stageEnteredAt={stageEnteredAt}
          busy={workflowBusy}
          quizActive={quizVisible}
          collapsed={panelCollapsed}
          onToggleCollapsed={() => setPanelCollapsed((value) => !value)}
          onEnterStage={(stageId) => void applyScene(stageId, true)}
          onLaunchQuestion={(questionId, stageId) => void launchQuestion(questionId, stageId)}
          onLaunchAdhocQuestion={(text, options) => void launchAdhocQuestion(text, options)}
          onObservation={recordObservation}
          onSnapshot={() => void onRefresh()}
          onEndSession={() => void endSession()}
          onAssistantPrompt={onAssistantPrompt}
        />
      ) : null}
      <div className="bottom-stack">
        <div className="bottom-dock">
          {statusBar}
          <div className="lesson-workflow-launcher" data-testid="lesson-workflow-launcher">
            <button
              type="button"
              className={`toolbar-button compact ${lessonMode === "prep" ? "active" : ""}`}
              onClick={() => setLessonMode((value) => (value === "prep" ? "off" : "prep"))}
            >
              课前
            </button>
            <button
              type="button"
              className={`toolbar-button compact ${lessonMode === "teach" ? "active" : ""}`}
              disabled={!activeLesson}
              onClick={() => setLessonMode((value) => (value === "teach" ? "off" : "teach"))}
            >
              课中
            </button>
            <button
              type="button"
              className={`toolbar-button compact ${lessonMode === "review" ? "active" : ""}`}
              onClick={() => setLessonMode((value) => (value === "review" ? "off" : "review"))}
            >
              课后
            </button>
          </div>
        </div>
      </div>

      {error ? <div className="lesson-workflow-error glass-panel">{error}</div> : null}

      {project && lessonMode === "prep" ? (
        <LessonPanel
          lessons={lessons}
          activeLesson={activeLesson}
          busy={workflowBusy}
          onSelectLesson={(lessonId) => void selectLesson(lessonId)}
          onApplyScene={(stageId) => void applyScene(stageId)}
          onCaptureScene={captureScene}
          onSaveStages={(stages) => void saveStages(stages)}
          onImportText={(text) => void importLessonText(text)}
          onStartClass={() => void startClass()}
          onClose={() => setLessonMode("off")}
        />
      ) : null}

      {project && lessonMode === "review" ? <ReportPanel projectId={project.project_id} onClose={() => setLessonMode("off")} /> : null}

      {quizVisible && activeSession ? (
        <QuizOverlay
          sessionId={activeSession.session_id}
          joinUrl={studentJoinUrl}
          onCloseQuestion={() => void closeQuestion()}
          onDismiss={() => setQuizVisible(false)}
        />
      ) : null}

      {visualQueryDismissed || !visualQueryLayer ? null : (
        <VisualQueryPopup
          layer={visualQueryLayer}
          shifted={teachPanelVisible && !panelCollapsed}
          onClose={() => setVisualQueryDismissed(true)}
          onFocusItem={(_item: VisualizationItem) => {
            void onRefresh();
          }}
        />
      )}
    </>
  );
}
