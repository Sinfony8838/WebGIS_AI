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
      report_url: ""
    }
  })
}));

import { ReportPanel } from "../components/ReportPanel";

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
    expect(screen.getByText("学生端作答")).toBeTruthy();
    expect(screen.getByText(/教师口头呈现 · 表现见教师观察/)).toBeTruthy();
    expect(screen.queryByText(/正确率/)).toBeNull();
  });
});
