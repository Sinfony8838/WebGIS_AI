import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QuestionPracticeModal } from "../components/QuestionPracticeModal";
import type { LessonQuestion, QuestionTimerState } from "../types";

const timer = (overrides: Partial<QuestionTimerState> = {}): QuestionTimerState => ({
  status: "idle",
  suggested_seconds: 120,
  elapsed_seconds: 0,
  running_since: "",
  question_source: "question_bank",
  revealed: false,
  revealed_at: "",
  actual_seconds: null,
  overtime_seconds: 0,
  reset_count: 0,
  ai_explanation: null,
  ...overrides
});

const question = (overrides: Partial<LessonQuestion> = {}, timerOverride?: QuestionTimerState): LessonQuestion => ({
  question_id: "qb_1",
  type: "choice",
  text: "影响人口分布的主要自然因素是？",
  options: ["气候和地形", "宗教信仰"],
  answer_index: 0,
  expected_points: [],
  misconceptions: [],
  source: "question_bank",
  material: "下图示意世界人口密度分布。",
  task_text: "读图完成下列各题。",
  answer: "气候和地形",
  answer_letter: "A",
  explanation: "中低纬度沿海平原气候适宜、地形平坦。",
  knowledge_points: ["人口分布", "自然因素"],
  answer_complete: true,
  suggested_seconds: 120,
  images: [{ url: "/files/uploads/question_banks/b1/img1.png", width: 600, height: 400 }],
  timer: timerOverride ?? timer(),
  ...overrides
});

const props = (overrides: Record<string, unknown> = {}) => ({
  busy: false,
  onTimerAction: vi.fn(),
  onReveal: vi.fn(),
  onClose: vi.fn(),
  onObservation: vi.fn(),
  ...overrides
});

afterEach(cleanup);

describe("QuestionPracticeModal", () => {
  it("shows material, images, stem and options only — no answer before reveal", () => {
    render(<QuestionPracticeModal question={question()} {...props()} />);

    expect(screen.getByTestId("question-practice-modal")).toBeTruthy();
    expect(screen.getByTestId("qpm-material")).toBeTruthy();
    expect(screen.getByTestId("qpm-images")).toBeTruthy();
    expect(screen.getByTestId("qpm-stem").textContent).toContain("影响人口分布的主要自然因素");
    expect(screen.getByTestId("qpm-options").children.length).toBe(2);
    // 揭示前不出现任何答案区块：无官方答案/解析/AI 讲解。
    expect(screen.queryByTestId("qpm-answer")).toBeNull();
    expect(screen.queryByText("官方答案")).toBeNull();
    expect(screen.queryByText(/中低纬度沿海平原气候适宜/)).toBeNull();
    expect(screen.queryByTestId("qpm-ai")).toBeNull();
    // 倒计时从建议秒数开始。
    expect(screen.getByTestId("qpm-clock").textContent).toContain("2:00");
    expect(screen.getByTestId("qpm-start")).toBeTruthy();
    expect(screen.getByTestId("qpm-reveal")).toBeTruthy();
  });

  it("drives timer actions through callbacks", () => {
    const onTimerAction = vi.fn();
    render(<QuestionPracticeModal question={question()} {...props({ onTimerAction })} />);

    fireEvent.click(screen.getByTestId("qpm-start"));
    expect(onTimerAction).toHaveBeenCalledWith("start");

    // 模拟服务端响应：进入 running。
    cleanup();
    render(
      <QuestionPracticeModal
        question={question(undefined, timer({ status: "running", elapsed_seconds: 10, running_since: new Date().toISOString() }))}
        {...props({ onTimerAction })}
      />
    );
    expect(screen.getByTestId("qpm-pause")).toBeTruthy();
    expect(screen.getByTestId("qpm-reset")).toBeTruthy();
    fireEvent.click(screen.getByTestId("qpm-pause"));
    expect(onTimerAction).toHaveBeenLastCalledWith("pause");

    // 暂停后提供 继续。
    cleanup();
    render(
      <QuestionPracticeModal
        question={question(undefined, timer({ status: "paused", elapsed_seconds: 30 }))}
        {...props({ onTimerAction })}
      />
    );
    expect(screen.getByTestId("qpm-resume")).toBeTruthy();
    fireEvent.click(screen.getByTestId("qpm-resume"));
    expect(onTimerAction).toHaveBeenLastCalledWith("resume");
    fireEvent.click(screen.getByTestId("qpm-reset"));
    expect(onTimerAction).toHaveBeenLastCalledWith("reset");
  });

  it("reveals official answer, explanation, knowledge tags and AI explanation", () => {
    const onReveal = vi.fn();
    render(
      <QuestionPracticeModal
        question={question(undefined, timer({
          status: "revealed",
          revealed: true,
          actual_seconds: 200,
          overtime_seconds: 80,
          ai_explanation: { text: "【讲解要点】\n官方答案：气候和地形", generator: "rules" }
        }))}
        {...props({ onReveal })}
      />
    );

    const answer = screen.getByTestId("qpm-answer");
    expect(answer.textContent).toContain("A. 气候和地形");
    expect(answer.textContent).toContain("中低纬度沿海平原气候适宜、地形平坦。");
    expect(screen.getByTestId("qpm-ai").textContent).toContain("官方答案：气候和地形");
    expect(screen.getByTestId("qpm-ai").textContent).toContain("规则生成");
    expect(screen.getByTestId("qpm-revealed-timer").textContent).toContain("3:20");
    expect(screen.getByTestId("qpm-revealed-timer").textContent).toContain("1:20");
    // 揭示后不再出现计时控制。
    expect(screen.queryByTestId("qpm-reveal")).toBeNull();
    // 揭示后提供学情速记。
    expect(screen.getByTestId("qpm-notes")).toBeTruthy();
  });

  it("submits quick notes including misconception tags", () => {
    const onObservation = vi.fn();
    render(
      <QuestionPracticeModal
        question={question(undefined, timer({ status: "revealed", revealed: true, actual_seconds: 60 }))}
        {...props({ onObservation })}
      />
    );

    fireEvent.change(screen.getByPlaceholderText("一句话描述学生表现（可留空）"), {
      target: { value: "多数学生答对" }
    });
    fireEvent.click(screen.getByTestId("qpm-note-correct"));
    expect(onObservation).toHaveBeenCalledWith("correct", "", "多数学生答对");

    fireEvent.click(screen.getByTestId("qpm-note-misconception"));
    fireEvent.change(screen.getByPlaceholderText("输入误区标签"), {
      target: { value: "混淆人口数量与密度" }
    });
    fireEvent.click(screen.getByTestId("qpm-note-confirm"));
    expect(onObservation).toHaveBeenLastCalledWith("misconception", "混淆人口数量与密度", "");
  });

  it("close button and ESC both request closing", () => {
    const onClose = vi.fn();
    render(<QuestionPracticeModal question={question()} {...props({ onClose })} />);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("qpm-close-footer"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
