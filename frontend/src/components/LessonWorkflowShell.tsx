import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  addSessionObservation,
  activatePopulationSourceVersion,
  applyLessonScene,
  captureLessonScene,
  closeSessionQuestion,
  createClassSession,
  createLessonDesign,
  endClassSession,
  enterSessionStage,
  fetchClassSessions,
  fetchJob,
  fetchLesson,
  fetchLessons,
  fetchPopulationSources,
  fetchPopulationSourceVersions,
  importLesson,
  launchSessionQuestion,
  populationLessonPrepResult,
  preparePopulationLesson,
  revealSessionQuestion,
  fetchQuestionExplanation,
  resolvePopulationLessonPrep,
  updateLesson,
  updateSessionQuestionTimer
} from "../api";
import type {
  ClassSessionRecord,
  JobRecord,
  LayersResponse,
  LessonRecord,
  LessonQuestion,
  LessonGlobeScene,
  LessonStage,
  ObservationVerdict,
  PopulationLessonPrepInput,
  PopulationLessonPrepResult,
  PopulationSourceCard,
  PopulationSourceVersion,
  ProjectRecord,
  SceneSnapshot,
  TeachingContext
} from "../types";
import { ClassRunPanel } from "./ClassRunPanel";
import { LessonPanel } from "./LessonPanel";
import { QuestionPracticeModal } from "./QuestionPracticeModal";
import { RehearsalPanel } from "./RehearsalPanel";
import { ReportPanel } from "./ReportPanel";
import { VisualQueryPopup, type VisualizationItem } from "./VisualQueryPopup";

type LessonMode = "off" | "prep" | "rehearsal" | "teach" | "review";

type Props = {
  project: (ProjectRecord & { status?: string }) | null;
  assistantJob?: JobRecord | null;
  layerState: LayersResponse | null;
  busy?: boolean;
  onRefresh: () => void | Promise<void>;
  /** 底部状态栏（经纬度/层级），与课前/课中/课后按钮同坞排布，避免相互压盖。 */
  statusBar?: ReactNode;
  /** 每次递增时打开课堂工作流：有进行中课堂则展开课中面板，否则打开课前备课。 */
  openSignal?: number;
  /** 助教识别到整节课设计请求时自动打开共创面板。 */
  designOpenSignal?: number;
  /** 打开全屏教案设计工作台（教案设计入口；未提供时退回右侧共创面板）。 */
  onOpenDesignWorkspace?: (designId?: string) => void;
  /** 打开指定课时的模拟测试（教案设计工作台「进入模拟测试」入口）。 */
  rehearsalSignal?: number;
  rehearsalLessonId?: string;
  /** 课堂工作流状态（lesson/session/stage/phase）变化时上报给 App，随助教请求发往后端。 */
  onTeachingContextChange?: (ctx: TeachingContext | null) => void;
  /** 课中一键把预设追问派发给教学智能体。 */
  onAssistantPrompt?: (prompt: string, displayMessage?: string) => void;
  /** 应用课时场景返回的 3D 意图；空对象表示离开课时固定场景并恢复进入前状态。 */
  onApplyGlobeScene?: (globe: LessonGlobeScene) => void;
  /** 捕获当前课堂场景时同时读取 3D 模式、主题和相机。 */
  getGlobeSceneSnapshot?: () => LessonGlobeScene;
  /** 课中按教学顺序聚焦一张证据图层，避免多图层同时堆叠。 */
  onFocusEvidenceLayer?: (datasetId: string, stageDatasetIds: string[]) => void;
  /** 三维宏观导入结束后，教师一键回到二维规范专题图判读。 */
  onRequestPlaneView?: () => void;
  /** 框选真实地图截图并将 Artifact 记入当前课堂事件。 */
  onCaptureEvidence?: (sessionId: string, stageId: string) => void;
};

function currentLayerSnapshot(
  layerState: LayersResponse | null,
  globe?: LessonGlobeScene
): SceneSnapshot {
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
    templates: layerState?.enabled_templates || [],
    globe
  };
}

function lessonSnapshotFromSession(session: ClassSessionRecord): LessonRecord | null {
  const snapshot = session.metadata?.lesson_snapshot;
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return null;
  const candidate = snapshot as Partial<LessonRecord>;
  if (candidate.lesson_id !== session.lesson_id || !Array.isArray(candidate.stages)) return null;
  return candidate as LessonRecord;
}

function sessionStageEnteredAt(session: ClassSessionRecord): number | null {
  const event = [...session.events].reverse().find(
    (item) => item.type === "stage_enter" && item.stage_id === session.current_stage_id
  );
  const value = event ? Date.parse(event.timestamp) : NaN;
  return Number.isFinite(value) ? value : null;
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

async function waitForPopulationPrep(
  jobId: string,
  onProgress: (label: string) => void,
  signal: AbortSignal
): Promise<PopulationLessonPrepResult> {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    if (signal.aborted) {
      const error = new Error("人口专题智能备课已取消");
      error.name = "AbortError";
      throw error;
    }
    const job = await fetchJob(jobId);
    const activeStage = Object.values(job.stages || {}).find((stage) => stage.status === "running");
    if (activeStage?.summary) {
      onProgress(activeStage.summary);
    }
    if (job.status === "completed") {
      const result = populationLessonPrepResult(job);
      if (!result?.change_set) {
        throw new Error("智能备课未返回可确认的教案变更草稿");
      }
      return result;
    }
    if (job.status === "failed") {
      throw new Error(job.error || "人口专题智能备课失败");
    }
    await new Promise<void>((resolve, reject) => {
      const onAbort = () => {
        window.clearTimeout(timer);
        const error = new Error("人口专题智能备课已取消");
        error.name = "AbortError";
        reject(error);
      };
      const timer = window.setTimeout(() => {
        signal.removeEventListener("abort", onAbort);
        resolve();
      }, 500);
      signal.addEventListener("abort", onAbort, { once: true });
    });
  }
  throw new Error("人口专题智能备课超时");
}

export function LessonWorkflowShell({
  project,
  assistantJob,
  layerState,
  busy = false,
  onRefresh,
  statusBar,
  openSignal = 0,
  designOpenSignal = 0,
  onOpenDesignWorkspace,
  rehearsalSignal = 0,
  rehearsalLessonId = "",
  onTeachingContextChange,
  onAssistantPrompt,
  onApplyGlobeScene,
  getGlobeSceneSnapshot,
  onFocusEvidenceLayer,
  onRequestPlaneView,
  onCaptureEvidence
}: Props) {
  const [lessonMode, setLessonMode] = useState<LessonMode>("off");
  const [lessons, setLessons] = useState<LessonRecord[]>([]);
  const [activeLesson, setActiveLesson] = useState<LessonRecord | null>(null);
  const [activeSession, setActiveSession] = useState<ClassSessionRecord | null>(null);
  const appliedAssistantJob = useRef("");
  const [stageEnteredAt, setStageEnteredAt] = useState<number | null>(null);
  const [panelCollapsed, setPanelCollapsed] = useState(true);
  const [localBusy, setLocalBusy] = useState(false);
  const [error, setError] = useState("");
  const [visualQueryDismissed, setVisualQueryDismissed] = useState(false);
  const [prepResult, setPrepResult] = useState<PopulationLessonPrepResult | null>(null);
  const [prepProgress, setPrepProgress] = useState("");
  const [populationSources, setPopulationSources] = useState<PopulationSourceCard[]>([]);
  const [populationSourceVersions, setPopulationSourceVersions] = useState<PopulationSourceVersion[]>([]);
  const [populationSourceVersion, setPopulationSourceVersion] = useState("");
  const visualQuerySignatureRef = useRef("");
  const prepAbortRef = useRef<AbortController | null>(null);

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

  useEffect(() => {
    if (!designOpenSignal) return;
    setPanelCollapsed(false);
    onOpenDesignWorkspace?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [designOpenSignal]);

  const openDesign = () => {
    onOpenDesignWorkspace?.();
  };

  // 教案设计工作台「进入模拟测试」入口：打开指定课时的模拟测试面板。
  useEffect(() => {
    if (!rehearsalSignal || !rehearsalLessonId) return;
    let cancelled = false;
    void fetchLesson(rehearsalLessonId)
      .then((lesson) => {
        if (cancelled) return;
        setActiveLesson(lesson);
        setLessons((previous) => previous.some((item) => item.lesson_id === lesson.lesson_id)
          ? previous.map((item) => (item.lesson_id === lesson.lesson_id ? lesson : item))
          : [lesson, ...previous]);
        setLessonMode("rehearsal");
      })
      .catch((exc) => {
        if (!cancelled) setError(exc instanceof Error ? exc.message : String(exc));
      });
    return () => {
      cancelled = true;
    };
    // rehearsalSignal 单调递增触发，rehearsalLessonId 仅作为打开瞬间的目标。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rehearsalSignal]);

  const startRehearsal = useCallback((lesson: LessonRecord) => {
    setActiveLesson(lesson);
    setLessonMode("rehearsal");
  }, []);

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
      : lessonMode === "prep" || lessonMode === "rehearsal"
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

  useEffect(() => {
    if (!project) {
      setActiveSession(null);
      return;
    }
    setActiveSession(null);
    let cancelled = false;
    void fetchClassSessions({ projectId: project.project_id })
      .then(async ({ items }) => {
        const running = [...items]
          .filter((item) => item.status === "running")
          .sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)))[0];
        if (!running) return;
        const lesson = lessonSnapshotFromSession(running) || await fetchLesson(running.lesson_id);
        if (cancelled) return;
        setActiveSession(running);
        setActiveLesson(lesson);
        setLessons((previous) => previous.some((item) => item.lesson_id === lesson.lesson_id)
          ? previous.map((item) => (item.lesson_id === lesson.lesson_id ? lesson : item))
          : [lesson, ...previous]);
        setStageEnteredAt(sessionStageEnteredAt(running));
        setLessonMode("teach");
        setPanelCollapsed(false);
      })
      .catch((exc) => {
        if (!cancelled) setError(exc instanceof Error ? exc.message : String(exc));
      });
    return () => {
      cancelled = true;
    };
  }, [project?.project_id]);

  // Assistant actions mutate the same classroom on the server. Adopt their
  // returned state so the next instruction carries the actual session/stage.
  useEffect(() => {
    if (assistantJob?.status !== "completed" || assistantJob.project_id !== project?.project_id
      || appliedAssistantJob.current === assistantJob.job_id) return;
    appliedAssistantJob.current = assistantJob.job_id;
    for (const entry of assistantJob.result?.actions_executed || []) {
      if (["start_class_session", "end_class_session"].includes(entry.action.tool_name)) {
        const session = entry.result?.class_session as ClassSessionRecord | undefined;
        if (!session?.session_id) continue;
        setActiveSession(session);
        const lesson = lessonSnapshotFromSession(session);
        if (lesson) setActiveLesson(lesson);
        setStageEnteredAt(sessionStageEnteredAt(session));
        setLessonMode(session.status === "running" ? "teach" : "review");
        setPanelCollapsed(false);
      }
      if (entry.action.tool_name === "enter_lesson_stage") {
        const stage = entry.result?.stage as LessonStage | undefined;
        if (!stage?.stage_id) continue;
        const session = entry.result?.session as ClassSessionRecord | undefined;
        setActiveSession((previous) => session || (previous ? { ...previous, current_stage_id: stage.stage_id } : previous));
        setStageEnteredAt(session ? sessionStageEnteredAt(session) : Date.now());
        onApplyGlobeScene?.(stage.scene?.globe || {});
        setLessonMode("teach");
      }
    }
  }, [assistantJob, project?.project_id, onApplyGlobeScene]);

  useEffect(() => () => {
    prepAbortRef.current?.abort();
  }, []);

  const loadPopulationSources = useCallback(async () => {
    if (!project) return;
    const [sourcePayload, versionPayload] = await Promise.all([
      fetchPopulationSources(project.project_id),
      fetchPopulationSourceVersions(project.project_id)
    ]);
    setPopulationSources(sourcePayload.items);
    setPopulationSourceVersion(sourcePayload.version || versionPayload.active_version);
    setPopulationSourceVersions(versionPayload.versions);
  }, [project]);

  useEffect(() => {
    if (lessonMode !== "prep" || !project) return;
    void loadPopulationSources().catch((exc) => {
      setError(exc instanceof Error ? exc.message : String(exc));
    });
  }, [lessonMode, loadPopulationSources, project]);

  const runWithBusy = useCallback(async (operation: () => Promise<void>) => {
    setLocalBusy(true);
    setError("");
    try {
      await operation();
    } catch (exc) {
      if (exc instanceof Error && exc.name === "AbortError") return;
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLocalBusy(false);
    }
  }, []);

  const designRequest = useRef(0);
  useEffect(() => () => { designRequest.current += 1; }, [project?.project_id]);
  const designFromLesson = useCallback(async (lesson: LessonRecord) => {
    if (!project || !onOpenDesignWorkspace) return;
    const requestId = ++designRequest.current;
    await runWithBusy(async () => {
      const design = await createLessonDesign(project.project_id, lesson.lesson_id);
      if (requestId !== designRequest.current) return;
      setLessonMode("off");
      onOpenDesignWorkspace(design.design_id);
    });
  }, [project, onOpenDesignWorkspace, runWithBusy]);

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
        let globe: LessonGlobeScene = {};
        if (viaSession && activeSession) {
          const response = await enterSessionStage(activeSession.session_id, stageId);
          globe = response.scene?.globe || {};
          setActiveSession((previous) => response.session || (previous ? { ...previous, current_stage_id: stageId } : previous));
          setStageEnteredAt(response.session ? sessionStageEnteredAt(response.session) : Date.now());
        } else {
          const response = await applyLessonScene(activeLesson.lesson_id, stageId, project.project_id);
          globe = response.globe || {};
        }
        onApplyGlobeScene?.(globe);
        await onRefresh();
      });
    },
    [activeLesson, activeSession, onApplyGlobeScene, onRefresh, project, runWithBusy]
  );

  const captureScene = useCallback(
    async (stageId: string): Promise<SceneSnapshot | null> => {
      if (!activeLesson) return null;
      let snapshot: SceneSnapshot | null = null;
      await runWithBusy(async () => {
        snapshot = currentLayerSnapshot(layerState, getGlobeSceneSnapshot?.());
        await captureLessonScene(activeLesson.lesson_id, stageId, snapshot);
        const lesson = await fetchLesson(activeLesson.lesson_id);
        setActiveLesson(lesson);
        setLessons((previous) => previous.map((item) => (item.lesson_id === lesson.lesson_id ? lesson : item)));
      });
      return snapshot;
    },
    [activeLesson, getGlobeSceneSnapshot, layerState, runWithBusy]
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

  const prepareLesson = useCallback(
    async (input: PopulationLessonPrepInput) => {
      if (!project || !activeLesson) return;
      await runWithBusy(async () => {
        prepAbortRef.current?.abort();
        const controller = new AbortController();
        prepAbortRef.current = controller;
        setPrepResult(null);
        setPrepProgress("正在建立人口专题备课任务…");
        const accepted = await preparePopulationLesson(project.project_id, activeLesson.lesson_id, input);
        const result = await waitForPopulationPrep(accepted.job_id, setPrepProgress, controller.signal);
        if (controller.signal.aborted) return;
        setPrepResult(result);
        setPrepProgress("预演通过，等待教师确认。");
        prepAbortRef.current = null;
      });
    },
    [activeLesson, project, runWithBusy]
  );

  const changePopulationSourceVersion = useCallback(
    async (version: string) => {
      if (!project) return;
      await runWithBusy(async () => {
        await activatePopulationSourceVersion(project.project_id, version);
        await loadPopulationSources();
        setPrepResult(null);
        setPrepProgress(`已切换人口来源包 ${version}，后续草稿将使用该版本。`);
      });
    },
    [loadPopulationSources, project, runWithBusy]
  );

  const resolvePrepChangeSet = useCallback(
    async (decision: "apply" | "reject", acceptedStageIds: string[]) => {
      if (!prepResult?.change_set) return;
      await runWithBusy(async () => {
        const response = await resolvePopulationLessonPrep(
          prepResult.change_set.change_set_id,
          decision,
          acceptedStageIds
        );
        if (decision === "apply") {
          const updated = response.lesson || (activeLesson ? await fetchLesson(activeLesson.lesson_id) : null);
          if (updated) {
            setActiveLesson(updated);
            setLessons((previous) =>
              previous.map((item) => (item.lesson_id === updated.lesson_id ? updated : item))
            );
          }
          await onRefresh();
        }
        setPrepResult(null);
        setPrepProgress(decision === "apply" ? "已应用教师选中的环节。" : "已放弃本次备课草稿。");
      });
    },
    [activeLesson, onRefresh, prepResult, runWithBusy]
  );

  const startClass = useCallback(async () => {
    if (!project || !activeLesson) return;
    await runWithBusy(async () => {
      const response = await createClassSession(activeLesson.lesson_id, project.project_id);
      setActiveSession(response.session);
      setLessonMode("teach");
      setPanelCollapsed(false);
      const firstStage = (lessonSnapshotFromSession(response.session) || activeLesson).stages[0];
      if (firstStage) {
        // Use the newly created ID; React state still holds the previous session here.
        const entered = await enterSessionStage(response.session.session_id, firstStage.stage_id);
        const session = entered.session || { ...response.session, current_stage_id: firstStage.stage_id };
        setActiveSession(session);
        setStageEnteredAt(entered.session ? sessionStageEnteredAt(session) : Date.now());
        onApplyGlobeScene?.(entered.scene?.globe || {});
      }
      await onRefresh();
    });
  }, [activeLesson, onApplyGlobeScene, onRefresh, project, runWithBusy]);

  const endSession = useCallback(async () => {
    if (!activeSession) return;
    await runWithBusy(async () => {
      const response = await endClassSession(activeSession.session_id);
      setActiveSession(response.session);
      setLessonMode("review");
      await onRefresh();
    });
  }, [activeSession, onRefresh, runWithBusy]);

  const launchQuestion = useCallback(
    async (questionId: string, stageId: string) => {
      if (!activeSession) return;
      await runWithBusy(async () => {
        await launchSessionQuestion(activeSession.session_id, {
          question_id: questionId,
          stage_id: stageId,
          delivery: "teacher_oral"
        });
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
          adhoc: { text, options },
          delivery: "teacher_oral"
        });
      });
    },
    [activeSession, runWithBusy]
  );

  // ------------------------------------------------------------------
  // 正式课堂题目投屏与计时（服务端计时状态，刷新/断线自动恢复）
  // ------------------------------------------------------------------

  const projectQuestion = useCallback(
    async (questionId: string, stageId: string) => {
      if (!activeSession) return;
      await runWithBusy(async () => {
        const response = await launchSessionQuestion(activeSession.session_id, {
          question_id: questionId,
          stage_id: stageId,
          delivery: "student"
        });
        setActiveSession((previous) =>
          previous ? { ...previous, active_question: response.active_question } : previous
        );
      });
    },
    [activeSession, runWithBusy]
  );

  const projectionTimerAction = useCallback(
    async (action: "start" | "pause" | "resume" | "reset") => {
      if (!activeSession) return;
      await runWithBusy(async () => {
        const response = await updateSessionQuestionTimer(activeSession.session_id, action);
        setActiveSession((previous) =>
          previous
            ? { ...previous, active_question: { ...previous.active_question, timer: response.timer } }
            : previous
        );
      });
    },
    [activeSession, runWithBusy]
  );

  const projectionReveal = useCallback(async () => {
    if (!activeSession) return;
    await runWithBusy(async () => {
      const response = await revealSessionQuestion(activeSession.session_id);
      setActiveSession((previous) =>
        previous?.session_id === activeSession.session_id && previous.active_question?.question_id === activeSession.active_question?.question_id
          ? { ...previous, active_question: { ...previous.active_question, timer: response.timer } }
          : previous
      );
    });
  }, [activeSession, runWithBusy]);

  const explanationTimer = (activeSession?.active_question as Partial<LessonQuestion> | undefined)?.timer;
  const explanationRequestId = explanationTimer?.ai_request_id;
  const explanationStatus = explanationTimer?.ai_explanation_status;
  useEffect(() => {
    if (!activeSession || activeSession.status !== "running" || explanationStatus !== "pending") return;
    let cancelled = false, timeout = 0;
    const sessionId = activeSession.session_id;
    const questionId = activeSession.active_question.question_id;
    const poll = async () => {
      try {
        const response = await fetchQuestionExplanation(sessionId);
        if (cancelled) return;
        if (!response.timer || response.question_id !== questionId || response.timer.ai_request_id !== explanationRequestId) return;
        setActiveSession(previous => previous?.session_id === sessionId && previous.active_question?.question_id === questionId && (previous.active_question as Partial<LessonQuestion>).timer?.ai_request_id === explanationRequestId
          ? { ...previous, active_question: { ...previous.active_question, timer: response.timer! } } : previous);
        if (response.timer.ai_explanation_status !== "pending") return;
      } catch { /* A temporary disconnect must not close the question or lose its answer. */ }
      if (!cancelled) timeout = window.setTimeout(poll, 1500);
    };
    timeout = window.setTimeout(poll, 700);
    return () => { cancelled = true; window.clearTimeout(timeout); };
  }, [activeSession?.session_id, activeSession?.active_question?.question_id, activeSession?.status, explanationRequestId, explanationStatus]);

  const closeProjection = useCallback(async () => {
    if (!activeSession) return;
    await runWithBusy(async () => {
      await closeSessionQuestion(activeSession.session_id);
      setActiveSession((previous) =>
        previous ? { ...previous, active_question: {} } : previous
      );
    });
  }, [activeSession, runWithBusy]);

  // 投屏题直接取自班课 active_question：它是开课时刻的完整题目快照（含答案与计时状态），
  // 服务端保证计时字段为实时计算值；无计时的活跃题（历史学生作答题）不进入投屏弹窗。
  const projectionQuestion = useMemo(() => {
    const active = activeSession?.active_question as Partial<LessonQuestion> | undefined;
    if (activeSession?.status !== "running" || !active?.question_id || !active?.timer) {
      return null;
    }
    return active as unknown as LessonQuestion;
  }, [activeSession]);

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
  const teachPanelVisible = lessonMode === "teach" && activeSession?.status === "running" && Boolean(activeLesson);

  return (
    <>
      {teachPanelVisible && activeSession && activeLesson ? (
        <ClassRunPanel
          lesson={activeLesson}
          session={activeSession}
          currentStageId={activeSession.current_stage_id}
          stageEnteredAt={stageEnteredAt}
          busy={workflowBusy}
          quizActive={Boolean(activeSession.active_question?.question_id)}
          collapsed={panelCollapsed}
          onToggleCollapsed={() => setPanelCollapsed((value) => !value)}
          onEnterStage={(stageId) => void applyScene(stageId, true)}
          onLaunchQuestion={(questionId, stageId) => void launchQuestion(questionId, stageId)}
          onProjectQuestion={(questionId, stageId) => void projectQuestion(questionId, stageId)}
          onLaunchAdhocQuestion={(text, options) => void launchAdhocQuestion(text, options)}
          onObservation={recordObservation}
          onSnapshot={() => onCaptureEvidence?.(activeSession.session_id, activeSession.current_stage_id)}
          onEndSession={() => void endSession()}
          visibleCatalogLayerIds={(layerState?.items || [])
            .filter((layer) => layer.visible && layer.source === "one_map_catalog")
            .map((layer) => String(layer.metadata?.catalog_id || layer.layer_id.replace(/^one_map_/, "")))}
          onFocusEvidenceLayer={onFocusEvidenceLayer}
          onRequestPlaneView={onRequestPlaneView}
          onAssistantPrompt={onAssistantPrompt}
        />
      ) : null}
      {teachPanelVisible && projectionQuestion ? (
        <QuestionPracticeModal
          question={projectionQuestion}
          busy={workflowBusy}
          onTimerAction={(action) => void projectionTimerAction(action)}
          onReveal={() => void projectionReveal()}
          onClose={() => void closeProjection()}
          onObservation={(verdict, tag, note) =>
            recordObservation(verdict, tag, note, String(projectionQuestion.question_id || ""))}
        />
      ) : null}
      <div className="bottom-stack">
        <div className="bottom-dock">
          {statusBar}
          <div className="lesson-workflow-launcher" data-testid="lesson-workflow-launcher">
            <button
              type="button"
              className="toolbar-button compact"
              onClick={openDesign}
              data-testid="lesson-design-launcher"
            >
              教案设计
            </button>
            <button
              type="button"
              className={`toolbar-button compact ${lessonMode === "teach" || lessonMode === "prep" ? "active" : ""}`}
              onClick={() =>
                setLessonMode((value) => (value === "teach" ? "off" : activeSession?.status === "running" ? "teach" : "prep"))
              }
              data-testid="class-mode-toggle"
              title={activeSession?.status === "running" ? "进入课堂面板" : "先选择课时并开始上课"}
            >
              课堂模式
            </button>
            <button
              type="button"
              className={`toolbar-button compact ${lessonMode === "review" ? "active" : ""}`}
              onClick={() => setLessonMode((value) => (value === "review" ? "off" : "review"))}
            >
              教学复盘
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
          prepResult={prepResult}
          prepProgress={prepProgress}
          populationSources={populationSources}
          populationSourceVersions={populationSourceVersions}
          populationSourceVersion={populationSourceVersion}
          onPrepareLesson={(input) => void prepareLesson(input)}
          onChangePopulationSourceVersion={(version) => void changePopulationSourceVersion(version)}
          onResolvePrepChangeSet={(decision, stageIds) => void resolvePrepChangeSet(decision, stageIds)}
          onDesignFromLesson={onOpenDesignWorkspace ? (lesson) => void designFromLesson(lesson) : undefined}
          onStartClass={() => void startClass()}
          onStartRehearsal={startRehearsal}
          onClose={() => setLessonMode("off")}
        />
      ) : null}

      {project && lessonMode === "rehearsal" && activeLesson ? (
        <RehearsalPanel
          key={activeLesson.lesson_id}
          projectId={project.project_id}
          lesson={activeLesson}
          getSceneSnapshot={() => currentLayerSnapshot(layerState, getGlobeSceneSnapshot?.())}
          onApplyGlobeScene={(globe) => onApplyGlobeScene?.(globe)}
          onRefresh={onRefresh}
          onLessonCommitted={(lesson) => {
            setActiveLesson(lesson);
            setLessons((previous) => previous.map((item) => (item.lesson_id === lesson.lesson_id ? lesson : item)));
          }}
          onClose={() => setLessonMode("prep")}
        />
      ) : null}

      {project && lessonMode === "review" ? <ReportPanel projectId={project.project_id} onClose={() => setLessonMode("off")} /> : null}

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
