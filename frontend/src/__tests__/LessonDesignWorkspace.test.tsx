import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LessonDesignWorkspace } from "../components/LessonDesignWorkspace";
import type { LessonDesignSession, LessonDesignTurnResult, LessonPlanProfile } from "../types";

const createMock = vi.fn();
const fetchDesignMock = vi.fn();
const turnMock = vi.fn();
const resolveMock = vi.fn();
const finalizeMock = vi.fn();
const bindMock = vi.fn();
const searchMock = vi.fn();
const fetchBanksMock = vi.fn();

vi.mock("../api", () => ({
  createLessonDesign: (...args: unknown[]) => createMock(...args),
  fetchLessonDesign: (...args: unknown[]) => fetchDesignMock(...args),
  turnLessonDesign: (...args: unknown[]) => turnMock(...args),
  resolveLessonDesignSection: (...args: unknown[]) => resolveMock(...args),
  finalizeLessonDesign: (...args: unknown[]) => finalizeMock(...args),
  bindLessonDesignQuestion: (...args: unknown[]) => bindMock(...args),
  searchQuestionBanks: (...args: unknown[]) => searchMock(...args),
  fetchQuestionBanks: (...args: unknown[]) => fetchBanksMock(...args),
  fetchLesson: vi.fn().mockResolvedValue({ lesson_id: "lesson_1", title: "人口分布", metadata: {} }),
  importQuestionBanks: vi.fn().mockResolvedValue({ job_id: "j1" }),
  fetchJob: vi.fn().mockResolvedValue({ status: "completed", stages: {} }),
  exportLessonDocx: vi.fn().mockResolvedValue({ status: "success", artifact: { metadata: { public_url: "/files/x.docx" } }, job_id: "j2" })
}));

const emptyPlan = {} as LessonPlanProfile;

const session = (overrides: Partial<LessonDesignSession> = {}): LessonDesignSession => ({
  design_id: "design_1",
  project_id: "p1",
  owner_user_id: "u1",
  base_lesson_id: "",
  current_step: "requirements",
  requirements: {},
  draft: { title: "人口分布", topic: "人口分布", grade: "高一", duration_minutes: 40, objectives: [], stages: [] },
  base_draft: emptyPlan,
  diff_summary: [],
  section_status: {},
  source_refs: [],
  capability_bindings: [],
  turns: [],
  status: "active",
  revision: 0,
  final_lesson_id: "",
  pending_next_step: "",
  created_at: "",
  updated_at: "",
  plan_items: [],
  active_design_question: "请先告诉我年级、课题与课时。",
  ...overrides
});

const turnResult = (overrides: Partial<LessonDesignTurnResult> = {}): LessonDesignTurnResult => ({
  status: "success",
  assistant_message: "我理解你的课题。",
  next_step: "analysis",
  step_label: "课标与学情",
  draft: { title: "人口分布", topic: "人口分布", grade: "高一", objectives: [], stages: [] },
  section_status: { requirements: "proposed" },
  source_refs: [],
  capability_bindings: [],
  revision: 1,
  suggestions: [],
  plan_items: [{ key: "requirements", label: "教学需求", status: "proposed", value: "高一人口分布" }],
  retrieval_candidates: [],
  auto_bound_questions: [],
  active_design_question: "这节课的课标重点是什么？",
  ...overrides
});

describe("LessonDesignWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createMock.mockResolvedValue(session());
    fetchBanksMock.mockResolvedValue({ status: "success", items: [] });
  });

  afterEach(cleanup);

  it("shows the same read-only report from both buttons and clears it after a draft edit", async () => {
    createMock.mockResolvedValue(session({ current_step: "rehearsal", revision: 3 }));
    fetchDesignMock.mockResolvedValue({ ...session({ current_step: "rehearsal", revision: 3 }), rehearsal_report: {
      ready: false, errors: ["上海环节缺少活动"], warnings: [], total_minutes: 32, duration_minutes: 40
    }});
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    fireEvent.click(await screen.findByTestId("ldw-run-rehearsal"));
    await screen.findByText(/必须处理：上海环节缺少活动/);
    expect(screen.getByTestId("ldw-rehearsal").textContent).toContain("32 分钟 / 计划 40 分钟");
    fireEvent.click(screen.getByRole("button", { name: "重新检查" }));
    await waitFor(() => expect(fetchDesignMock).toHaveBeenCalledTimes(2));
    await screen.findByText(/必须处理：上海环节缺少活动/);
    expect(turnMock).not.toHaveBeenCalled();
    turnMock.mockResolvedValue(turnResult({ revision: 4, next_step: "rehearsal" }));
    fireEvent.change(screen.getByLabelText("教案设计对话输入"), { target: { value: "修改上海活动" } });
    fireEvent.click(screen.getByTestId("ldw-send"));
    await waitFor(() => expect(turnMock).toHaveBeenCalledWith("design_1", "修改上海活动", 3, "rehearsal"));
    await screen.findByText("尚未检查当前草稿，请运行预演。");
    expect(screen.queryByText(/必须处理：上海环节缺少活动/)).toBeNull();
    turnMock.mockResolvedValue(turnResult({ revision: 5, next_step: "rehearsal", rehearsal_report: { ready: true, errors: [], warnings: [] } }));
    fireEvent.change(screen.getByLabelText("教案设计对话输入"), { target: { value: "请检查修改后的草稿" } });
    fireEvent.click(screen.getByTestId("ldw-send"));
    await screen.findByText("结构检查通过，仍需教师核对内容并确认章节");
  });

  it("surfaces a check failure without retaining a stale successful report", async () => {
    createMock.mockResolvedValue(session({ current_step: "rehearsal" }));
    fetchDesignMock.mockResolvedValueOnce({ ...session({ current_step: "rehearsal" }), rehearsal_report: { ready: true, errors: [], warnings: [] } });
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    fireEvent.click(await screen.findByTestId("ldw-run-rehearsal"));
    await screen.findByText("结构检查通过，仍需教师核对内容并确认章节");
    fetchDesignMock.mockRejectedValueOnce(new Error("检查服务暂时不可用"));
    fireEvent.click(screen.getByRole("button", { name: "重新检查" }));
    await screen.findByText("检查服务暂时不可用");
    expect(screen.queryByText("结构检查通过，仍需教师核对内容并确认章节")).toBeNull();
    expect(turnMock).not.toHaveBeenCalled();
  });

  it("renders the nine steps, asks the active question and sends a turn", async () => {
    turnMock.mockResolvedValue(turnResult());
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);

    expect(await screen.findByText("需求确认")).toBeTruthy();
    expect(screen.getByText("课标与学情")).toBeTruthy();
    expect(screen.getByText("题目匹配")).toBeTruthy();
    expect(screen.getByText("预演检查")).toBeTruthy();
    expect(screen.getByText("确认发布")).toBeTruthy();
    expect(screen.getByTestId("ldw-active-question").textContent).toContain("年级、课题与课时");

    fireEvent.change(screen.getByLabelText("教案设计对话输入"), { target: { value: "高一《人口分布》40分钟" } });
    fireEvent.click(screen.getByTestId("ldw-send"));

    await waitFor(() => expect(turnMock).toHaveBeenCalledWith("design_1", "高一《人口分布》40分钟", 0, "requirements"));
    expect(await screen.findByText("我理解你的课题。")).toBeTruthy();
    expect(screen.getByTestId("ldw-active-question").textContent).toContain("课标重点");
  });

  it("exits the design workspace via the sidebar exit button", async () => {
    const onClose = vi.fn();
    render(<LessonDesignWorkspace projectId="p1" onClose={onClose} />);
    await screen.findByTestId("ldw-exit");

    fireEvent.click(screen.getByTestId("ldw-exit"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("accepts the current step via resolve", async () => {
    resolveMock.mockResolvedValue({ status: "success", design: session({ current_step: "analysis", revision: 1 }) });
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-accept-step");

    fireEvent.click(screen.getByTestId("ldw-accept-step"));
    await waitFor(() => expect(resolveMock).toHaveBeenCalledWith("design_1", "requirements", "accept", "", 0));
  });

  it("binds a bank question from search results to a stage", async () => {
    createMock.mockResolvedValue(
      session({
        current_step: "question_matching",
        revision: 3,
        draft: {
          title: "人口分布",
          topic: "人口分布",
          grade: "高一",
          duration_minutes: 40,
          objectives: [],
          stages: [
            { stage_id: "s1", title: "情境导入", minutes: 8, questions: [] } as never
          ]
        }
      })
    );
    fetchBanksMock.mockResolvedValue({
      status: "success",
      items: [
        {
          bank_id: "qb_1", project_id: "p1", title: "专题08 人口", base_name: "专题08",
          import_mode: "paired", answer_missing: false, section_count: 3, group_count: 49,
          question_count: 94, answer_complete_count: 94, answer_coverage: 1, image_count: 40,
          pairing_note_count: 0, stats: {}, created_at: "", updated_at: ""
        }
      ]
    });
    searchMock.mockResolvedValue({
      status: "success",
      items: [
        {
          question_id: "qb_1_g01_007_q1", bank_id: "qb_1", group_id: "g1", group_key: "g01_007",
          number: "13", type: "choice", is_composite: false, section_index: 1, section_title: "人口分布",
          knowledge_points: ["人口分布"], year: "2023", region: "浙江", source_paper: "高考真题",
          material: "", stem: "下列中亚国家中，人口密度最小的是", task_text: "", options: [],
          answer: "B", answer_letter: "B", answer_index: 1, explanation: "…", sub_questions: [],
          answer_complete: true, relevance: 0.9, auto_selectable: true, selection_reason: "", images: []
        }
      ],
      candidates_count: 94,
      generator: "rules",
      query: {}
    });
    bindMock.mockResolvedValue({
      status: "success",
      message: "题目已更新。",
      design: session({ revision: 4 }),
      stage: { stage_id: "s1", title: "情境导入", minutes: 8, questions: [] } as never
    });

    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-search-input");

    fireEvent.change(screen.getByTestId("ldw-search-input"), { target: { value: "人口分布 自然因素" } });
    fireEvent.click(screen.getByTestId("ldw-search-button"));
    await waitFor(() => expect(searchMock).toHaveBeenCalled());
    expect(await screen.findByText(/中亚国家/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "选用" }));
    await waitFor(() =>
      expect(bindMock).toHaveBeenCalledWith("design_1", {
        stage_id: "s1",
        question_id: "qb_1_g01_007_q1",
        expected_revision: 3
      })
    );
  });

  it("binds a manual question with answer and explanation", async () => {
    createMock.mockResolvedValue(
      session({
        current_step: "question_matching",
        draft: {
          title: "人口分布", topic: "人口分布", grade: "高一", duration_minutes: 40, objectives: [],
          stages: [{ stage_id: "s1", title: "情境导入", minutes: 8, questions: [] } as never]
        }
      })
    );
    fetchBanksMock.mockResolvedValue({
      status: "success",
      items: [
        {
          bank_id: "qb_1", project_id: "p1", title: "专题08 人口", base_name: "专题08",
          import_mode: "paired", answer_missing: false, section_count: 3, group_count: 49,
          question_count: 94, answer_complete_count: 94, answer_coverage: 1, image_count: 40,
          pairing_note_count: 0, stats: {}, created_at: "", updated_at: ""
        }
      ]
    });
    bindMock.mockResolvedValue({
      status: "success",
      message: "题目已更新。",
      design: session({ revision: 1 }),
      stage: { stage_id: "s1", title: "情境导入", minutes: 8, questions: [] } as never
    });

    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    await screen.findByTestId("ldw-manual-toggle");
    fireEvent.click(screen.getByTestId("ldw-manual-toggle"));

    fireEvent.change(screen.getByLabelText("手动题目题干"), { target: { value: "简述地形对人口分布的影响。" } });
    fireEvent.change(screen.getByLabelText("手动题目参考答案"), { target: { value: "山区人口稀疏。" } });
    fireEvent.change(screen.getByLabelText("手动题目解析"), { target: { value: "地形影响交通与耕地。" } });
    fireEvent.click(screen.getByTestId("ldw-manual-bind"));

    await waitFor(() =>
      expect(bindMock).toHaveBeenCalledWith("design_1", {
        stage_id: "s1",
        manual: { text: "简述地形对人口分布的影响。", answer: "山区人口稀疏。", explanation: "地形影响交通与耕地。" },
        expected_revision: 0
      })
    );
  });

  it("finalizes to a draft lesson and offers the Word download", async () => {
    createMock.mockResolvedValue(session({ current_step: "confirmation", revision: 9 }));
    finalizeMock.mockResolvedValue({
      status: "success",
      lesson: {
        lesson_id: "lesson_1", title: "人口分布", subject: "地理", grade: "高一", objectives: [],
        stages: [], source: "assistant_draft", metadata: { ready_for_class: false, lesson_version: 1 }, created_at: "", updated_at: ""
      },
      design: session({ current_step: "confirmation", status: "finalized", revision: 10, final_lesson_id: "lesson_1" }),
      capability_report: { ready: true },
      export: { status: "success", artifact: { metadata: { public_url: "/files/lesson.docx" } } }
    });

    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} onFinalized={vi.fn()} />);
    await screen.findByTestId("ldw-finalize-button");

    fireEvent.click(screen.getByTestId("ldw-finalize-button"));
    await waitFor(() => expect(finalizeMock).toHaveBeenCalledWith("design_1", 9));
    expect(await screen.findByText("下载教案 Word")).toBeTruthy();
    expect(screen.getByText(/待模拟测试/)).toBeTruthy();
  });

  it("enters the rehearsal for the finalized lesson", async () => {
    createMock.mockResolvedValue(session({ current_step: "confirmation", revision: 9 }));
    const finalizedLesson = {
      lesson_id: "lesson_1", title: "人口分布", subject: "地理", grade: "高一", objectives: [],
      stages: [], source: "assistant_draft", metadata: { ready_for_class: false, lesson_version: 1 }, created_at: "", updated_at: ""
    };
    finalizeMock.mockResolvedValue({
      status: "success",
      lesson: finalizedLesson,
      design: session({ current_step: "confirmation", status: "finalized", revision: 10, final_lesson_id: "lesson_1" }),
      capability_report: { ready: true },
      export: { status: "success", artifact: { metadata: { public_url: "/files/lesson.docx" } } }
    });
    const enterRehearsal = vi.fn();

    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} onEnterRehearsal={enterRehearsal} />);
    await screen.findByTestId("ldw-finalize-button");

    fireEvent.click(screen.getByTestId("ldw-finalize-button"));
    fireEvent.click(await screen.findByTestId("ldw-enter-rehearsal"));

    await waitFor(() => expect(enterRehearsal).toHaveBeenCalledWith(finalizedLesson));
  });

  it("resumes an existing design by id", async () => {
    fetchDesignMock.mockResolvedValue(session({ current_step: "process", revision: 5 }));
    render(<LessonDesignWorkspace projectId="p1" initialDesignId="design_9" onClose={vi.fn()} />);
    await waitFor(() => expect(fetchDesignMock).toHaveBeenCalledWith("design_9"));
    expect(createMock).not.toHaveBeenCalled();
    expect((await screen.findAllByText(/教学过程/)).length).toBeGreaterThan(0);
  });

  it("generates a full draft from one requirement paragraph and shows the focus card", async () => {
    const multiSectionDraft = {
      title: "胡焕庸线与中国人口分布", topic: "胡焕庸线与中国人口分布", grade: "高一", duration_minutes: 45,
      objectives: ["运用地图说出分布特征", "解释成因", "迁移方法"],
      core_questions: { core: "为什么呈现东南密集西北稀疏？", sub_questions: ["格局？", "自然因素？", "人文因素？"] },
      stages: [
        { stage_id: "s1", title: "情境导入与地图观察", minutes: 9, questions: [] },
        { stage_id: "s2", title: "胡焕庸线两侧对比与成因探究", minutes: 18, questions: [] },
        { stage_id: "s3", title: "归纳迁移与课堂小结", minutes: 18, questions: [] }
      ],
      homework: { basic: ["基础练习"], inquiry: ["沿胡焕庸线比较省区"] }
    };
    turnMock.mockResolvedValue({
      ...turnResult({
        assistant_message: "已按你的完整需求生成初稿……以上内容全部为「待确认」。还缺：暂无阻断性缺口。",
        next_step: "requirements",
        draft: multiSectionDraft,
        section_status: { requirements: "proposed", objectives: "proposed", stages: "proposed" },
        review_sections: ["requirements", "objectives", "stages"]
      }),
      focus_summary: {
        changed_labels: ["教学需求", "教学目标", "教学过程", "课题", "课时"],
        confirmed_labels: [],
        missing: [],
        next_confirm_sections: ["教学需求", "课标解读"],
        next_confirm_question: "这节课面向哪个年级？",
        unverified_note: "初稿中未经核实的内容均为教学建议；发布前请核对数据、年份与来源。"
      }
    });
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);

    await screen.findByTestId("ldw-active-question");
    await waitFor(() => expect(screen.getByTestId("ldw-full-draft")).not.toBeDisabled());
    fireEvent.change(
      screen.getByLabelText("教案设计对话输入"),
      { target: { value: "设计一节胡焕庸线与中国人口分布课，45分钟，重点分析东南密集西北稀疏。" } }
    );
    fireEvent.click(screen.getByTestId("ldw-full-draft"));

    await waitFor(() =>
      expect(turnMock).toHaveBeenCalledWith(
        "design_1",
        "生成完整初稿：设计一节胡焕庸线与中国人口分布课，45分钟，重点分析东南密集西北稀疏。",
        0,
        "requirements"
      )
    );
    const focus = await screen.findByTestId("ldw-focus");
    expect(focus.textContent).toContain("刚修改");
    expect(focus.textContent).toContain("教学过程");
    expect(focus.textContent).toContain("暂无阻断缺口");
    expect(focus.textContent).toContain("下一步确认");
    expect(focus.textContent).toContain("这节课面向哪个年级？");
    expect(focus.textContent).toContain("教学建议");
  });

  it("shows the focus card immediately when resuming an old design", async () => {
    fetchDesignMock.mockResolvedValue({
      ...session({ current_step: "process", revision: 7 }),
      focus_summary: {
        changed_labels: [],
        confirmed_labels: [],
        missing: ["还缺少一个贯穿课堂的核心问题。"],
        next_confirm_sections: ["教学过程", "板书设计"],
        next_confirm_question: "教学过程从哪个情境或现象切入？",
        unverified_note: "初稿中未经核实的内容均为教学建议；发布前请核对数据、年份与来源。"
      }
    });
    render(<LessonDesignWorkspace projectId="p1" initialDesignId="design_9" onClose={vi.fn()} />);

    const focus = await screen.findByTestId("ldw-focus");
    expect(focus.textContent).toContain("还缺少一个贯穿课堂的核心问题。");
    expect(focus.textContent).toContain("教学过程");
  });

  it("adopts the current suggestion and continues, then shows confirmed focus", async () => {
    createMock.mockResolvedValue(
      session({
        current_step: "process",
        revision: 5,
        draft: {
          title: "人口分布", topic: "人口分布", grade: "高一", duration_minutes: 40, objectives: [],
          stages: [{ stage_id: "s1", title: "导入", minutes: 10 } as never],
          board_design: "板书"
        },
        section_status: { stages: "proposed", board_design: "proposed" }
      })
    );
    resolveMock.mockResolvedValue({
      status: "success",
      design: session({
        current_step: "question_matching",
        revision: 6,
        section_status: { stages: "confirmed", board_design: "confirmed" }
      }),
      focus_summary: {
        changed_labels: [],
        confirmed_labels: ["教学过程", "板书设计"],
        missing: ["还缺少一个贯穿课堂的核心问题。"],
        next_confirm_sections: ["核心问题与问题链"],
        next_confirm_question: "贯穿这节课的核心问题用一句话怎么说？",
        unverified_note: "初稿中未经核实的内容均为教学建议；发布前请核对数据、年份与来源。"
      }
    });
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);
    const adopt = await screen.findByTestId("ldw-adopt-continue");
    await waitFor(() => expect(adopt).not.toBeDisabled());

    fireEvent.click(adopt);
    await waitFor(() => expect(resolveMock).toHaveBeenCalledWith("design_1", "process", "accept", "", 5));
    const focus = await screen.findByTestId("ldw-focus");
    expect(focus.textContent).toContain("已确认：教学过程、板书设计");
  });

  it("sends a scoped edit that only touches the current step, and disables it without input", async () => {
    createMock.mockResolvedValue(
      session({
        current_step: "process",
        revision: 4,
        draft: {
          title: "人口分布", topic: "人口分布", grade: "高一", duration_minutes: 40, objectives: [],
          stages: [{ stage_id: "s1", title: "导入", minutes: 10 } as never]
        },
        section_status: { stages: "proposed" }
      })
    );
    turnMock.mockResolvedValue({
      ...turnResult({ revision: 5, next_step: "process" }),
      focus_summary: {
        changed_labels: ["教学过程"],
        confirmed_labels: [],
        missing: [],
        next_confirm_sections: ["教学过程"],
        next_confirm_question: "",
        unverified_note: "初稿中未经核实的内容均为教学建议；发布前请核对数据、年份与来源。"
      }
    });
    render(<LessonDesignWorkspace projectId="p1" onClose={vi.fn()} />);

    expect(await screen.findByTestId("ldw-scoped-edit")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("教案设计对话输入"), { target: { value: "把导入的提问改为胡焕庸线两侧差异" } });
    expect(screen.getByTestId("ldw-scoped-edit")).not.toBeDisabled();
    fireEvent.click(screen.getByTestId("ldw-scoped-edit"));

    await waitFor(() =>
      expect(turnMock).toHaveBeenCalledWith(
        "design_1",
        "只修改当前环节：把导入的提问改为胡焕庸线两侧差异",
        4,
        "process"
      )
    );
    const focus = await screen.findByTestId("ldw-focus");
    expect(focus.textContent).toContain("教学过程");
  });
});
