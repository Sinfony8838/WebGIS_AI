import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  buildAuthenticatedUrl: (value: string) => value,
  fetchClassSessions: vi.fn().mockResolvedValue({
    status: "success",
    items: [
      {
        session_id: "session_teacher_only",
        lesson_id: "lesson_population",
        project_id: "project_1",
        status: "ended",
        join_code: "",
        current_stage_id: "s1",
        started_at: "2026-08-04T08:00:00+00:00",
        ended_at: "2026-08-04T08:40:00+00:00",
        events: [],
        active_question: {},
        responses: {},
        metadata: { lesson_title: "人口分布" }
      }
    ]
  }),
  generateSessionReport: vi.fn().mockResolvedValue({ job_id: "job_report" }),
  exportSessionPractice: vi.fn().mockResolvedValue({
    status: "success",
    job_id: "job_practice",
    session_id: "session_teacher_only",
    student_artifact: {
      artifact_id: "artifact_student",
      artifact_type: "practice_paper_student",
      title: "人口分布 课后练习卷（学生卷）",
      path: "C:/outputs/practice_student.docx",
      metadata: { public_url: "/files/outputs/practice_student.docx", session_id: "session_teacher_only", format: "docx" }
    },
    teacher_artifact: {
      artifact_id: "artifact_teacher",
      artifact_type: "practice_paper_teacher",
      title: "人口分布 课后练习卷（教师卷）",
      path: "C:/outputs/practice_teacher.docx",
      metadata: { public_url: "/files/outputs/practice_teacher.docx", session_id: "session_teacher_only", format: "docx" }
    },
    selection_summary: [
      { origin: "lesson_homework_basic", label: "教案课后作业（基础）", level: "基础必做", count: 1 },
      { origin: "lesson_homework_inquiry", label: "教案课后作业（探究）", level: "拓展选做", count: 0 },
      { origin: "class_observation", label: "教师课堂速记（原题回炉）", level: "课堂巩固", count: 2 },
      { origin: "observation_variant", label: "误区变式（题库检索）", level: "课堂巩固", count: 0 },
      { origin: "bank_core", label: "核心目标巩固（题库检索）", level: "课后巩固", count: 0 }
    ],
    notes: ["教师卷中的课堂实测仅统计本次课堂的真实计时与作答记录。"]
  }),
  fetchJob: vi.fn().mockResolvedValue({
    status: "completed",
    result: {
      statistics: {
        session_id: "session_teacher_only",
        lesson_id: "lesson_population",
        lesson_title: "人口分布",
        started_at: "2026-08-04T08:00:00+00:00",
        ended_at: "2026-08-04T08:40:00+00:00",
        duration_minutes: 40,
        participant_count: 0,
        participants: [],
        response_data_collected: false,
        stages: [],
        questions: [
          {
            question_id: "s1q1",
            stage_id: "s1",
            text: "中国人口分布均匀吗？",
            type: "choice",
            collection_mode: "teacher_observation",
            options: ["均匀", "东南稠密、西北稀疏"],
            answer_index: 1,
            response_count: 0,
            option_counts: [0, 0],
            correct_rate: null,
            sample_texts: [],
            misconceptions: []
          }
        ],
        observations: {
          total: 1,
          verdict_counts: { correct: 0, partial: 1, misconception: 0 },
          misconception_tags: [],
          notes: []
        },
        snapshot_count: 1,
        assistant_exchange_count: 0,
        event_count: 4
      },
      diagnosis: { text: "### 学情诊断\n仅依据教师观察。", generator: "rules" },
      practice_recommendations: [
        {
          practice_id: "population_metric_check",
          level: "基础必做",
          title: "人口总量与人口密度辨析",
          suggested_minutes: 6,
          prompt: "计算两地人口密度并解释差异。",
          answer_points: ["人口密度需同时考虑人口与面积"],
          evidence_basis: "教师记录到一次部分正确，安排核心目标复测。"
        }
      ],
      report_url: ""
    }
  })
}));

import { ReportPanel } from "../components/ReportPanel";
import { fetchJob } from "../api";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ReportPanel", () => {
  it("marks student response data as uncollected and renders teacher oral evidence", async () => {
    render(<ReportPanel projectId="project_1" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("option", { name: /人口分布/ })).toBeTruthy());
    fireEvent.click(screen.getByTestId("generate-report"));

    await waitFor(() => expect(screen.getByText("未采集")).toBeTruthy());
    expect(screen.getByText("课堂作答")).toBeTruthy();
    expect(screen.getByText(/教师口头呈现 · 表现见教师观察/)).toBeTruthy();
    expect(screen.getByText(/规则生成 · 证据保护/)).toBeTruthy();
    expect(screen.getByText("课后推荐练习巩固")).toBeTruthy();
    expect(screen.getByText(/人口总量与人口密度辨析/)).toBeTruthy();
    expect(screen.getByText(/不计入40分钟课时/)).toBeTruthy();
    expect(screen.queryByText(/正确率/)).toBeNull();
  });

  it("exports practice papers with student and teacher downloads", async () => {
    render(<ReportPanel projectId="project_1" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("option", { name: /人口分布/ })).toBeTruthy());
    fireEvent.click(screen.getByTestId("export-practice"));

    await waitFor(() => expect(screen.getByTestId("practice-export-result")).toBeTruthy());
    const studentLink = screen.getByTestId("practice-student-link") as HTMLAnchorElement;
    const teacherLink = screen.getByTestId("practice-teacher-link") as HTMLAnchorElement;
    expect(studentLink.getAttribute("href")).toBe("/files/outputs/practice_student.docx");
    expect(teacherLink.getAttribute("href")).toBe("/files/outputs/practice_teacher.docx");
    expect(screen.getByText(/下载学生卷（无答案）/)).toBeTruthy();
    expect(screen.getByText(/下载教师卷（含答案与课堂实测）/)).toBeTruthy();
    // 选题来源如实标注，零计数来源不展示
    expect(screen.getByText(/教案课后作业（基础） ×1/)).toBeTruthy();
    expect(screen.getByText(/教师课堂速记（原题回炉） ×2/)).toBeTruthy();
    expect(screen.queryByText(/教案课后作业（探究）/)).toBeNull();
  });
});

it("labels a projection without responses as uncollected instead of drawing zero-percent bars", async () => {
  const payload = await fetchJob("fixture");
  const result = structuredClone(payload) as any;
  result.result.statistics.questions[0].collection_mode = "student_response";
  vi.mocked(fetchJob).mockResolvedValueOnce(result);
  render(<ReportPanel projectId="project_1" onClose={vi.fn()} />);
  await waitFor(() => expect(screen.getByTestId("generate-report")).toBeEnabled());
  fireEvent.click(screen.getByTestId("generate-report"));
  await waitFor(() => expect(screen.getByText(/本题未采集作答数据/)).toBeTruthy());
  expect(screen.queryByText(/0 人作答/)).toBeNull();
  expect(document.querySelector(".tally-bar")).toBeNull();
});
