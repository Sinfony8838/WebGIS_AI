import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ClassRunPanel } from "../components/ClassRunPanel";
import { LessonPanel } from "../components/LessonPanel";
import type { ClassSessionRecord, LessonRecord, PopulationLessonPrepResult } from "../types";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual };
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
        assistant_prompts: [],
        brainstorm: {
          title: "随机地区的人口格局猜想",
          prompt: "比较该地区与全国人口格局。",
          regions: ["黑河", "腾冲", "台湾省"],
          button_label: "转动地区并生成探究"
        }
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
        assistant_prompts: ["请用密度概念解释东西部人口疏密差异。"],
        brainstorm: {
          title: "总量与密度的反直觉比较",
          prompt: "判断更应关注人口总量还是人口密度。",
          regions: ["北京市", "西藏自治区"],
          button_label: "抽取省区并生成比较"
        }
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
  if (vi.isMockFunction(Math.random)) {
    vi.mocked(Math.random).mockRestore();
  }
  vi.clearAllMocks();
  vi.useRealTimers();
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

  it("does not mark skipped stages as completed", () => {
    renderPanel({ currentStageId: "s2" });
    expect(screen.getByTestId("stage-chip-s1").className).not.toContain("done");
  });

  it("presents choice questions orally without exposing teacher answers", () => {
    const props = renderPanel();
    fireEvent.click(screen.getByTestId("oral-toggle-s1q1"));
    expect(props.onLaunchQuestion).toHaveBeenCalledWith("s1q1", "s1");
    const oralCard = screen.getByTestId("oral-prompt-s1q1");
    expect(oralCard.textContent).toContain("A");
    expect(oralCard.textContent).toContain("B");
    expect(oralCard.textContent).not.toContain("参考答案");
    expect(screen.queryByTestId("oral-reveal-s1q1")).toBeNull();
    expect(screen.queryByTestId("oral-answer-s1q1")).toBeNull();
  });

  it("records quick observation and misconception tag", () => {
    const props = renderPanel();
    fireEvent.click(screen.getByText("答对"));
    expect(props.onObservation).toHaveBeenCalledWith("correct", "", "", "");

    fireEvent.click(screen.getByText("误区"));
    const picker = screen.getByTestId("misconception-picker");
    expect(picker).toBeTruthy();
    fireEvent.change(within(picker).getByPlaceholderText("教师现场输入误区标签"), {
      target: { value: "只见城市不见格局" }
    });
    fireEvent.click(screen.getByText("记录误区"));
    expect(props.onObservation).toHaveBeenCalledWith("misconception", "只见城市不见格局", "", "");
  });

  it("expands only student-visible options without answers or teacher hints", () => {
    renderPanel();
    fireEvent.click(screen.getByTestId("question-toggle-s1q1"));
    expect(screen.getByText(/东南密西北疏/)).toBeTruthy();
    const card = screen.getByTestId("question-toggle-s1q1").closest(".class-question-card") as HTMLElement;
    expect(card.textContent).not.toContain("✓ 正确");
    expect(card.textContent).not.toContain("只见城市不见格局");
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
    expect(screen.queryByText("显示答案与教师收束")).toBeNull();
    // 朗读提问卡预置学情速记到 s2q1
    fireEvent.click(screen.getByText("答对"));
    expect(props.onObservation).toHaveBeenCalledWith("correct", "", "", "s2q1");
    // 再次点击收起卡片
    fireEvent.click(toggle);
    expect(screen.queryByTestId("oral-prompt-s2q1")).toBeNull();
  });

  it("keeps teacher guidance out of the projected classroom panel", () => {
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
    expect(screen.queryByTestId("stage-teacher-guidance")).toBeNull();
    expect(screen.queryByText("先找图例、年份和空间差异。")).toBeNull();
  });

  it("opens student-facing textbook knowledge in a movable enlarged overlay", () => {
    renderPanel();
    expect(screen.queryByText("先看地图")).toBeNull();
    fireEvent.click(within(screen.getByTestId("basic-knowledge-launcher")).getByText("放大展示"));
    const overlay = screen.getByTestId("basic-knowledge-overlay");
    expect(overlay.textContent).toContain("基础知识讲解");
    expect(overlay.textContent).toContain("先看地图");
    const header = overlay.querySelector(".basic-knowledge-overlay-header") as HTMLElement;
    fireEvent.pointerDown(header, { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(header, { pointerId: 1, clientX: 180, clientY: 150 });
    fireEvent.pointerUp(header, { pointerId: 1, clientX: 180, clientY: 150 });
    expect(overlay.getAttribute("style")).toContain("left:");
    fireEvent.click(screen.getByLabelText("关闭基础知识讲解"));
    expect(screen.queryByTestId("basic-knowledge-overlay")).toBeNull();
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
    expect(within(steps).getByText("气候").className).toContain("active");
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

  it("runs a GeoBot brainstorm without exposing the internal prompt", () => {
    vi.useFakeTimers();
    const randomSpy = vi.spyOn(Math, "random").mockReturnValue(0);
    const onAssistantPrompt = vi.fn();
    renderPanel({ currentStageId: "s2", onAssistantPrompt });
    const card = screen.getByTestId("stage-brainstorm");
    expect(card.textContent).toContain("GeoBot AI");
    expect(card.textContent).not.toContain("判断更应关注人口总量还是人口密度");
    fireEvent.click(screen.getByTestId("run-brainstorm"));
    act(() => vi.advanceTimersByTime(1100));
    expect(onAssistantPrompt).toHaveBeenCalledOnce();
    expect(onAssistantPrompt.mock.calls[0][0]).toContain("随机抽中的地区是：北京市");
    expect(onAssistantPrompt.mock.calls[0][0]).toContain("只输出“头脑风暴问题”“回答”“回答总结”");
    expect(onAssistantPrompt.mock.calls[0][1]).toBe("GeoBot 头脑风暴 · 北京市");
    randomSpy.mockRestore();
  });

  it("hides the brainstorm activity when no dispatcher is available", () => {
    renderPanel({ currentStageId: "s2" });
    expect(screen.queryByTestId("stage-brainstorm")).toBeNull();
  });
});
