import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ClassRunPanel } from "../components/ClassRunPanel";
import { LessonPanel } from "../components/LessonPanel";
import { QuizOverlay } from "../components/QuizOverlay";
import type { ClassSessionRecord, LessonRecord, PopulationLessonPrepResult } from "../types";

vi.mock("qrcode", () => ({
  default: { toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,stub") }
}));

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    fetchSessionLive: vi.fn().mockResolvedValue({
      status: "success",
      session_id: "session_1",
      session_status: "running",
      current_stage_id: "s1",
      active_question: {
        question_id: "s1q1",
        text: "中国人口分布均匀吗？",
        type: "choice",
        options: ["均匀", "东南密西北疏"],
        answer_index: 1
      },
      tally: {
        question_id: "s1q1",
        total: 3,
        option_counts: [1, 2],
        answer_index: 1,
        correct_rate: 0.6667,
        texts: []
      },
      joined_count: 5,
      recent_events: []
    })
  };
});

function makeLesson(): LessonRecord {
  return {
    lesson_id: "lesson_1",
    title: "人口分布",
    subject: "地理",
    grade: "高一",
    objectives: [],
    source: "builtin",
    metadata: {},
    created_at: "",
    updated_at: "",
    stages: [
      {
        stage_id: "s1",
        title: "问题导入",
        minutes: 3,
        scene: {
          basemap_id: "amap_light",
          templates: ["population_distribution"],
          layer_visibility: { builtin_population_regions: true },
          view: { center: [104, 35], zoom: 4 },
          annotations: [],
          visual_query: null
        },
        script: ["先看地图"],
        questions: [
          {
            question_id: "s1q1",
            type: "choice",
            text: "中国人口分布均匀吗？",
            options: ["均匀", "东南密西北疏"],
            answer_index: 1,
            expected_points: [],
            misconceptions: [{ tag: "只见城市不见格局", description: "" }]
          }
        ],
        assistant_prompts: []
      },
      {
        stage_id: "s2",
        title: "概念建构",
        minutes: 4,
        scene: {
          basemap_id: "",
          templates: [],
          layer_visibility: {},
          view: {},
          annotations: [],
          visual_query: null
        },
        script: [],
        questions: [
          {
            question_id: "s2q1",
            type: "open",
            text: "为什么要看人口密度？",
            options: [],
            answer_index: null,
            expected_points: ["面积不同不可直接比较", "密度反映单位面积人口"],
            misconceptions: [{ tag: "混淆数量与密度", description: "" }]
          }
        ],
        assistant_prompts: ["请用密度概念解释东西部人口疏密差异。"]
      }
    ]
  };
}

function makeSession(): ClassSessionRecord {
  return {
    session_id: "session_1",
    lesson_id: "lesson_1",
    project_id: "project_1",
    status: "running",
    join_code: "123456",
    current_stage_id: "s1",
    started_at: "2026-07-03T01:00:00+00:00",
    ended_at: "",
    events: [],
    active_question: {},
    responses: {},
    metadata: {}
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("LessonPanel", () => {
  it("renders stages and fires scene apply with the stage id", () => {
    const onApplyScene = vi.fn();
    render(
      <LessonPanel
        lessons={[makeLesson()]}
        activeLesson={makeLesson()}
        busy={false}
        onSelectLesson={vi.fn()}
        onApplyScene={onApplyScene}
        onCaptureScene={vi.fn().mockResolvedValue(null)}
        onSaveStages={vi.fn()}
        onImportText={vi.fn()}
        onStartClass={vi.fn()}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText("问题导入")).toBeTruthy();
    expect(screen.getByText("概念建构")).toBeTruthy();

    fireEvent.click(screen.getByText("问题导入"));
    fireEvent.click(screen.getByTestId("apply-scene-s1"));
    expect(onApplyScene).toHaveBeenCalledWith("s1");
  });

  it("start class button is disabled without an active lesson", () => {
    render(
      <LessonPanel
        lessons={[]}
        activeLesson={null}
        busy={false}
        onSelectLesson={vi.fn()}
        onApplyScene={vi.fn()}
        onCaptureScene={vi.fn().mockResolvedValue(null)}
        onSaveStages={vi.fn()}
        onImportText={vi.fn()}
        onStartClass={vi.fn()}
        onClose={vi.fn()}
      />
    );
    expect((screen.getByTestId("start-class") as HTMLButtonElement).disabled).toBe(true);
  });

  it("collects population prep constraints and keeps generated changes behind teacher confirmation", async () => {
    const onPrepareLesson = vi.fn();
    const onResolvePrepChangeSet = vi.fn();
    const lesson = makeLesson();
    const prepResult: PopulationLessonPrepResult = {
      status: "success",
      capability: "population_lesson_prep",
      job_id: "job_prep_1",
      warnings: ["地形图为教学示意数据"],
      rehearsal: {
        status: "passed",
        errors: [],
        warnings: ["地形图为教学示意数据"],
        checks: { stage_count: 2 }
      },
      change_set: {
        change_set_id: "job_prep_1",
        status: "pending",
        lesson_id: lesson.lesson_id,
        base_lesson_fingerprint: "before",
        source_version: "1.0.0",
        source_pack_fingerprint: "pack",
        source_refs: [{ source_id: "population_density_china_2020", title: "人口密度" }],
        changes: lesson.stages.map((stage) => ({
          stage_id: stage.stage_id,
          title: stage.title,
          change_types: ["证据引用", "教师环节指导"],
          before_fingerprint: "a",
          after_fingerprint: "b",
          evidence_count: 2,
          question_count: stage.questions.length
        })),
        proposed_lesson: lesson,
        created_at: "2026-07-29T00:00:00Z"
      }
    };
    render(
      <LessonPanel
        lessons={[lesson]}
        activeLesson={lesson}
        busy={false}
        onSelectLesson={vi.fn()}
        onApplyScene={vi.fn()}
        onCaptureScene={vi.fn().mockResolvedValue(null)}
        onSaveStages={vi.fn()}
        onImportText={vi.fn()}
        prepResult={prepResult}
        prepProgress="预演通过"
        onPrepareLesson={onPrepareLesson}
        onResolvePrepChangeSet={onResolvePrepChangeSet}
        onStartClass={vi.fn()}
        onClose={vi.fn()}
      />
    );

    fireEvent.click(screen.getByTestId("population-prep-toggle"));
    fireEvent.click(screen.getByTestId("population-prep-submit"));
    expect(onPrepareLesson).toHaveBeenCalledWith(
      expect.objectContaining({
        objective: expect.stringContaining("人口分布"),
        duration_minutes: 10,
        region: "中国"
      })
    );

    expect(screen.getByTestId("population-change-set").textContent).toContain("教师确认式变更草稿");
    expect(screen.getByText("1 条来源或教学限制提示")).toBeTruthy();
    await waitFor(() => expect((screen.getByTestId("population-prep-apply") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("population-prep-apply"));
    expect(onResolvePrepChangeSet).toHaveBeenCalledWith("apply", ["s1", "s2"]);
  });
});

describe("ClassRunPanel", () => {
  function renderPanel(overrides: Partial<Parameters<typeof ClassRunPanel>[0]> = {}) {
    const props = {
      lesson: makeLesson(),
      session: makeSession(),
      currentStageId: "s1",
      stageEnteredAt: Date.now(),
      busy: false,
      quizActive: false,
      collapsed: false,
      onToggleCollapsed: vi.fn(),
      onEnterStage: vi.fn(),
      onLaunchQuestion: vi.fn(),
      onLaunchAdhocQuestion: vi.fn(),
      onObservation: vi.fn(),
      onSnapshot: vi.fn(),
      onEndSession: vi.fn(),
      ...overrides
    };
    render(<ClassRunPanel {...props} />);
    return props;
  }

  it("switches stage via the vertical stage list", () => {
    const props = renderPanel();
    fireEvent.click(screen.getByTestId("stage-chip-s2"));
    expect(props.onEnterStage).toHaveBeenCalledWith("s2");
  });

  it("presents choice questions orally without exposing the answer until the teacher reveals it", () => {
    const props = renderPanel();
    fireEvent.click(screen.getByTestId("oral-toggle-s1q1"));
    expect(props.onLaunchQuestion).toHaveBeenCalledWith("s1q1", "s1");
    const oralCard = screen.getByTestId("oral-prompt-s1q1");
    expect(oralCard.textContent).toContain("A");
    expect(oralCard.textContent).toContain("B");
    expect(oralCard.textContent).not.toContain("参考答案");
    fireEvent.click(screen.getByTestId("oral-reveal-s1q1"));
    expect(screen.getByTestId("oral-answer-s1q1").textContent).toContain("B. 东南密西北疏");
  });

  it("records quick observation and misconception tag", () => {
    const props = renderPanel();
    fireEvent.click(screen.getByText("答对"));
    expect(props.onObservation).toHaveBeenCalledWith("correct", "", "", "");

    fireEvent.click(screen.getByText("误区"));
    const picker = screen.getByTestId("misconception-picker");
    expect(picker).toBeTruthy();
    fireEvent.click(within(picker).getByText("只见城市不见格局"));
    fireEvent.click(screen.getByText("记录误区"));
    expect(props.onObservation).toHaveBeenCalledWith("misconception", "只见城市不见格局", "", "");
  });

  it("expands question detail with options, expected points and misconception shortcuts", () => {
    const props = renderPanel();
    fireEvent.click(screen.getByTestId("question-toggle-s1q1"));
    expect(screen.getByText(/东南密西北疏/)).toBeTruthy();
    const card = screen.getByTestId("question-toggle-s1q1").closest(".class-question-card") as HTMLElement;
    fireEvent.click(within(card).getByText("只见城市不见格局"));
    expect(props.onObservation).toHaveBeenCalledWith("misconception", "只见城市不见格局", "", "s1q1");
  });

  it("launches ad-hoc questions with optional options", () => {
    const props = renderPanel();
    const adhoc = screen.getByTestId("adhoc-question");
    fireEvent.change(within(adhoc).getByPlaceholderText("输入课堂即兴问题…"), {
      target: { value: "临时问题？" }
    });
    fireEvent.change(within(adhoc).getByPlaceholderText("选项用 / 分隔（留空为开放题）"), {
      target: { value: "甲 / 乙" }
    });
    fireEvent.click(screen.getByTestId("launch-adhoc"));
    expect(props.onLaunchAdhocQuestion).toHaveBeenCalledWith("临时问题？", ["甲", "乙"]);
  });

  it("toggles the oral-question read-aloud prompt card and primes the recorder", () => {
    const props = renderPanel({ currentStageId: "s2" });
    const toggle = screen.getByTestId("oral-toggle-s2q1");
    fireEvent.click(toggle);
    const card = screen.getByTestId("oral-prompt-s2q1");
    expect(card.textContent).toContain("朗读提问卡");
    expect(card.textContent).toContain("为什么要看人口密度？");
    expect(card.textContent).not.toContain("面积不同不可直接比较");
    fireEvent.click(screen.getByTestId("oral-reveal-s2q1"));
    expect(card.textContent).toContain("面积不同不可直接比较");
    expect(card.textContent).toContain("请用密度概念解释东西部人口疏密差异。");
    // 朗读提问卡预置学情速记到 s2q1
    fireEvent.click(screen.getByText("答对"));
    expect(props.onObservation).toHaveBeenCalledWith("correct", "", "", "s2q1");
    // 再次点击收起卡片
    fireEvent.click(toggle);
    expect(screen.queryByTestId("oral-prompt-s2q1")).toBeNull();
  });

  it("renders the generated teacher guidance card", () => {
    const lesson = makeLesson();
    lesson.stages[0].teacher_guidance = {
      observation_prompt: "先找图例、年份和空间差异。",
      evidence_points: ["人口密度图", "胡焕庸线"],
      oral_question: "中国人口分布均匀吗？",
      expected_response: "东南稠密、西北稀疏",
      misconception_cue: "不要只说不均匀",
      closing: "用区域—证据—解释收束。",
      fallback: "三维异常时使用二维图。"
    };
    renderPanel({ lesson });
    const guidance = screen.getByTestId("stage-teacher-guidance");
    expect(guidance.textContent).toContain("先找图例、年份和空间差异");
    expect(guidance.textContent).toContain("人口密度图");
    expect(guidance.textContent).toContain("三维异常时使用二维图");
  });

  it("focuses one evidence layer at a time from the stage guide", () => {
    const lesson = makeLesson();
    lesson.stages[0].scene.catalog_layers = ["china_climate_types", "china_terrain_steps", "china_major_rivers"];
    const onFocusEvidenceLayer = vi.fn();
    renderPanel({
      lesson,
      visibleCatalogLayerIds: ["china_climate_types"],
      onFocusEvidenceLayer
    });

    const steps = screen.getByTestId("evidence-layer-steps");
    expect(within(steps).getByText("① 气候").className).toContain("active");
    fireEvent.click(within(steps).getByTestId("evidence-layer-china_terrain_steps"));
    expect(onFocusEvidenceLayer).toHaveBeenCalledWith("china_terrain_steps", [
      "china_climate_types",
      "china_terrain_steps",
      "china_major_rivers"
    ]);
  });

  it("offers a one-click handoff from a 3D introduction to 2D map reading", () => {
    const lesson = makeLesson();
    lesson.stages[0].scene.globe = { enabled: true, themes: ["density_fill", "hu_line"] };
    const onRequestPlaneView = vi.fn();
    renderPanel({ lesson, onRequestPlaneView });

    const handoff = screen.getByTestId("stage-view-handoff");
    expect(handoff.textContent).toContain("3D 用于宏观导入");
    fireEvent.click(within(handoff).getByText("切回二维判读"));
    expect(onRequestPlaneView).toHaveBeenCalledOnce();
  });

  it("collapses to a slim tab and expands back", () => {
    const props = renderPanel({ collapsed: true });
    const tab = screen.getByTestId("class-run-panel-expand");
    fireEvent.click(tab);
    expect(props.onToggleCollapsed).toHaveBeenCalled();
  });

  it("renders stage-level AI follow-up chips and dispatches the prompt to the agent", () => {
    const onAssistantPrompt = vi.fn();
    renderPanel({ currentStageId: "s2", onAssistantPrompt });
    const chips = screen.getByTestId("stage-assistant-prompts");
    fireEvent.click(within(chips).getByTestId("stage-assistant-prompt-0"));
    expect(onAssistantPrompt).toHaveBeenCalledWith("请用密度概念解释东西部人口疏密差异。");
  });

  it("hides the AI follow-up section without prompts or without a dispatcher", () => {
    renderPanel({ currentStageId: "s2" });
    expect(screen.queryByTestId("stage-assistant-prompts")).toBeNull();
    cleanup();
    renderPanel({ currentStageId: "s1", onAssistantPrompt: vi.fn() });
    expect(screen.queryByTestId("stage-assistant-prompts")).toBeNull();
  });

  it("dispatches oral-card assistant prompts to the agent", () => {
    const onAssistantPrompt = vi.fn();
    renderPanel({ currentStageId: "s2", onAssistantPrompt });
    fireEvent.click(screen.getByTestId("oral-toggle-s2q1"));
    fireEvent.click(screen.getByTestId("oral-assistant-prompt-0"));
    expect(onAssistantPrompt).toHaveBeenCalledWith("请用密度概念解释东西部人口疏密差异。");
  });
});

describe("QuizOverlay", () => {
  it("renders live tally with joined count", async () => {
    render(
      <QuizOverlay
        sessionId="session_1"
        joinUrl="http://192.168.1.10:18999/student/123456"
        onCloseQuestion={vi.fn()}
        onDismiss={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId("joined-count").textContent).toContain("在线 5 人");
    });
    expect(screen.getByText("中国人口分布均匀吗？")).toBeTruthy();
    expect(screen.getByText(/B\. 东南密西北疏/)).toBeTruthy();
  });
});
