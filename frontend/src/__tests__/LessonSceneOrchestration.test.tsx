import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LessonWorkflowShell } from "../components/LessonWorkflowShell";
import type { LessonRecord } from "../types";

const apiMocks = vi.hoisted(() => ({
  fetchLessons: vi.fn(),
  fetchLesson: vi.fn(),
  fetchClassSessions: vi.fn().mockResolvedValue({ status: "success", items: [] }),
  applyLessonScene: vi.fn(),
  captureLessonScene: vi.fn(),
  fetchPopulationSources: vi.fn(),
  fetchPopulationSourceVersions: vi.fn(),
  updateLesson: vi.fn(),
  fetchJob: vi.fn(),
  preparePopulationLesson: vi.fn(),
  resolvePopulationLessonPrep: vi.fn()
}));

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, ...apiMocks };
});

function lesson(): LessonRecord {
  return {
    lesson_id: "lesson_population",
    title: "中国人口分布",
    subject: "地理",
    grade: "高一",
    objectives: ["解释人口分布格局"],
    source: "builtin",
    metadata: {},
    created_at: "",
    updated_at: "",
    stages: [
      {
        stage_id: "s4",
        title: "胡焕庸线",
        minutes: 7,
        scene: {
          basemap_id: "amap_light",
          templates: [],
          layer_visibility: {},
          catalog_layers: [],
          view: { center: [104, 35], zoom: 4 },
          annotations: [],
          visual_query: null,
          globe: {
            enabled: true,
            themes: ["density_fill", "hu_line"],
            camera: { lon: 103.8, lat: 36, altitudeMeters: 7_200_000, pitchDeg: -90 }
          }
        },
        script: [],
        questions: [],
        assistant_prompts: []
      }
    ]
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("LessonWorkflowShell globe scene orchestration", () => {
  it("forwards the backend globe scene and captures the current globe snapshot", async () => {
    const item = lesson();
    apiMocks.fetchLessons.mockResolvedValue({ status: "success", items: [item] });
    apiMocks.fetchLesson.mockResolvedValue(item);
    apiMocks.applyLessonScene.mockResolvedValue({
      status: "success",
      globe: item.stages[0].scene.globe
    });
    apiMocks.captureLessonScene.mockResolvedValue({ status: "success", scene: item.stages[0].scene });
    apiMocks.fetchPopulationSources.mockResolvedValue({
      status: "success",
      version: "1.0.0",
      pack_fingerprint: "pack",
      items: []
    });
    apiMocks.fetchPopulationSourceVersions.mockResolvedValue({
      status: "success",
      active_version: "1.0.0",
      versions: []
    });
    const onApplyGlobeScene = vi.fn();
    const getGlobeSceneSnapshot = vi.fn().mockReturnValue({
      enabled: true,
      themes: ["density_fill"],
      camera: { lon: 104, lat: 35, altitudeMeters: 8_000_000, pitchDeg: -90 }
    });

    render(
      <LessonWorkflowShell
        project={{ project_id: "project_1" } as never}
        layerState={{
          status: "success",
          project_id: "project_1",
          items: [],
          base_map: { id: "amap_light" },
          view: { center: [104, 35], zoom: 4 },
          enabled_templates: []
        } as never}
        openSignal={1}
        onRefresh={vi.fn()}
        onApplyGlobeScene={onApplyGlobeScene}
        getGlobeSceneSnapshot={getGlobeSceneSnapshot}
      />
    );

    await waitFor(() => expect(screen.getByText("胡焕庸线")).toBeTruthy());
    fireEvent.click(screen.getByText("胡焕庸线"));
    fireEvent.click(screen.getByTestId("apply-scene-s4"));
    await waitFor(() =>
      expect(onApplyGlobeScene).toHaveBeenCalledWith(
        expect.objectContaining({ enabled: true, themes: ["density_fill", "hu_line"] })
      )
    );

    fireEvent.click(screen.getByText("存当前地图为场景"));
    await waitFor(() =>
      expect(apiMocks.captureLessonScene).toHaveBeenCalledWith(
        "lesson_population",
        "s4",
        expect.objectContaining({
          globe: expect.objectContaining({ enabled: true, themes: ["density_fill"] })
        })
      )
    );
  });

  it("restores a running class after refresh and requests a real evidence screenshot", async () => {
    const item = lesson();
    const running = { session_id: "session_running", lesson_id: item.lesson_id, project_id: "project_1", status: "running", join_code: "123456", current_stage_id: "s4", started_at: "2026-08-22T08:00:00Z", ended_at: "", events: [], active_question: {}, responses: {}, metadata: {}, updated_at: "" };
    apiMocks.fetchLessons.mockResolvedValue({ status: "success", items: [item] });
    apiMocks.fetchLesson.mockResolvedValue(item);
    apiMocks.fetchClassSessions.mockResolvedValue({ status: "success", items: [running] });
    const onCaptureEvidence = vi.fn();
    render(<LessonWorkflowShell project={{ project_id: "project_1" } as never} layerState={null} onRefresh={vi.fn()} onCaptureEvidence={onCaptureEvidence} />);
    await waitFor(() => expect(screen.getByText("截图存证")).toBeTruthy());
    fireEvent.click(screen.getByText("截图存证"));
    expect(onCaptureEvidence).toHaveBeenCalledWith("session_running", "s4");
  });
});

it("adopts assistant classroom results without starting a second class", async () => {
  const item = lesson();
  apiMocks.fetchLessons.mockResolvedValue({ status: "success", items: [item] });
  apiMocks.fetchClassSessions.mockResolvedValue({ status: "success", items: [] });
  const onTeachingContextChange = vi.fn();
  const onApplyGlobeScene = vi.fn();
  const props = { project: { project_id: "project_1" } as never, layerState: null, onRefresh: vi.fn(), onTeachingContextChange, onApplyGlobeScene };
  const { rerender } = render(<LessonWorkflowShell {...props} />);
  await waitFor(() => expect(apiMocks.fetchLessons).toHaveBeenCalled());
  const session = { session_id: "assistant_session", project_id: "project_1", lesson_id: item.lesson_id, status: "running", current_stage_id: "", started_at: "2026-09-08T00:00:00Z", metadata: { lesson_snapshot: item }, events: [], responses: {}, active_question: {} };
  const job = (id: string, tool: string, result: object) => ({ job_id: id, project_id: "project_1", status: "completed", result: { actions_executed: [{ action: { tool_name: tool, tool_params: {} }, result }] } } as never);
  rerender(<LessonWorkflowShell {...props} assistantJob={job("start", "start_class_session", { class_session: session })} />);
  await waitFor(() => expect(onTeachingContextChange).toHaveBeenLastCalledWith(expect.objectContaining({ session_id: "assistant_session", phase: "in_class" })));
  expect(screen.getByText("结束上课")).toBeInTheDocument();
  rerender(<LessonWorkflowShell {...props} assistantJob={job("stage", "enter_lesson_stage", { stage: item.stages[0] })} />);
  await waitFor(() => expect(onTeachingContextChange).toHaveBeenLastCalledWith(expect.objectContaining({ stage_id: "s4" })));
  expect(onApplyGlobeScene).toHaveBeenCalledWith(item.stages[0].scene.globe);
  rerender(<LessonWorkflowShell {...props} assistantJob={job("end", "end_class_session", { class_session: { ...session, status: "ended" } })} />);
  await waitFor(() => expect(onTeachingContextChange).toHaveBeenLastCalledWith(expect.objectContaining({ phase: "post_class" })));
  expect(screen.getByLabelText("关闭复盘面板")).toBeInTheDocument();
});
