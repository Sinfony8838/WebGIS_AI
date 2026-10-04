import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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
    // 题图地址必须拼成后端 API 的可访问 URL（相对 /files/ 路径在 dev 前端源下拿不到文件）。
    const img = document.querySelector('[data-testid="qpm-images"] img') as HTMLImageElement;
    expect(img.src).toContain("/files/uploads/question_banks/b1/img1.png");
    expect(img.src.startsWith("http")).toBe(true);
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
    expect(screen.getByTestId("qpm-ai").textContent).toContain("规则整理");
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

it("keeps the reference answer and close control usable while commentary is pending", () => {
  const callbacks=props();
  const {rerender}=render(<QuestionPracticeModal {...callbacks} question={question({},timer({status:"revealed",revealed:true,ai_explanation_status:"pending"}))}/>);
  expect(screen.getByTestId("qpm-answer").textContent).toContain("气候和地形");
  expect(screen.getByRole("status").textContent).toContain("正在整理讲解");
  expect(screen.getByTestId("qpm-close")).not.toBeDisabled();
  rerender(<QuestionPracticeModal {...callbacks} question={question({},timer({status:"revealed",revealed:true,ai_explanation_status:"interrupted"}))}/>);
  fireEvent.click(screen.getByText("重试讲解"));
  expect(callbacks.onReveal).toHaveBeenCalledTimes(1);
});

describe("QuestionPracticeModal student display", () => {
  it("does not mount teacher controls, source labels or unrevealed knowledge hints", () => {
    const callbacks = props();
    render(<QuestionPracticeModal studentDisplay question={question({ knowledge_points: ["尚未揭示的知识标签"] })} {...callbacks} />);
    const modal = screen.getByTestId("question-practice-modal");
    expect(modal).toHaveTextContent("课堂练习");
    expect(modal).not.toHaveTextContent("题库题");
    expect(modal).not.toHaveTextContent("尚未揭示的知识标签");
    expect(within(modal).getAllByRole("button")).toEqual([within(modal).getByRole("button", { name: "放大题图 1" })]);
    expect(within(modal).queryByRole("textbox")).toBeNull();
    expect(screen.queryByTestId("qpm-answer")).toBeNull();
    expect(screen.getByTestId("qpm-options").querySelector(".correct")).toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(callbacks.onClose).not.toHaveBeenCalled();
  });

  it("shows only server-revealed answers and hides observations and AI recovery details", () => {
    const callbacks = props();
    const { rerender } = render(<QuestionPracticeModal studentDisplay question={question()} {...callbacks} />);
    rerender(<QuestionPracticeModal studentDisplay question={question({}, timer({
      revealed: true, status: "revealed", actual_seconds: 30,
      ai_explanation_status: "interrupted", ai_explanation_note: "内部任务失败提示",
      ai_explanation: { text: "阅读人口图可以概括分布差异。", generator: "rules" }
    }))} {...callbacks} />);
    expect(screen.getByTestId("qpm-answer")).toHaveTextContent("中低纬度沿海平原气候适宜");
    expect(screen.getByTestId("qpm-ai")).toHaveTextContent("阅读人口图可以概括分布差异");
    expect(screen.queryByTestId("qpm-notes")).toBeNull();
    expect(screen.queryByText(/学情速记|内部任务失败提示|重试讲解|讲解任务已中断/)).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getAllByRole("button")).toEqual([screen.getByRole("button", { name: "放大题图 1" })]);
    rerender(<QuestionPracticeModal studentDisplay question={question({ question_id: "next", explanation: "新题尚未揭示的解析" })} {...callbacks} />);
    expect(screen.queryByTestId("qpm-answer")).toBeNull();
    expect(screen.queryByText("新题尚未揭示的解析")).toBeNull();
    expect(screen.getByTestId("qpm-options").querySelector(".correct")).toBeNull();
  });

  it("keeps the last long option and subquestion inside the keyboard-readable content", () => {
    const longStem = `${"比较两个地区的人口空间分布。".repeat(70)}题干最后一句`;
    render(<QuestionPracticeModal studentDisplay question={question({
      text: longStem,
      options: ["第一项", `${"根据图示信息分析原因。".repeat(60)}末尾选项`],
      sub_questions: [{ index: "1", text: "最后一道小题", options: ["小题选项末尾"], answer: "秘密小题答案", answer_index: 0, explanation: "秘密小题解析" }]
    })} {...props()} />);
    const content = screen.getByRole("region", { name: "题目与讲解" });
    expect(content).toHaveAttribute("tabindex", "0");
    content.focus();
    expect(content).toHaveFocus();
    expect(content).toHaveTextContent("题干最后一句");
    expect(content).toHaveTextContent("末尾选项");
    expect(content).toHaveTextContent("小题选项末尾");
    expect(content).not.toHaveTextContent("秘密小题答案");
    expect(content).not.toHaveTextContent("秘密小题解析");
  });

  it("clears a teacher observation draft when the question changes", () => {
    const callbacks = props();
    const revealed = timer({ status: "revealed", revealed: true });
    const { rerender } = render(<QuestionPracticeModal question={question({}, revealed)} {...callbacks} />);
    fireEvent.change(screen.getByPlaceholderText("一句话描述学生表现（可留空）"), { target: { value: "上道题观察" } });
    fireEvent.click(screen.getByTestId("qpm-note-misconception"));
    fireEvent.change(screen.getByPlaceholderText("输入误区标签"), { target: { value: "上道题误区" } });
    rerender(<QuestionPracticeModal question={question({ question_id: "next" }, revealed)} {...callbacks} />);
    expect(screen.getByPlaceholderText("一句话描述学生表现（可留空）")).toHaveValue("");
    expect(screen.queryByPlaceholderText("输入误区标签")).toBeNull();
    fireEvent.click(screen.getByTestId("qpm-note-correct"));
    expect(callbacks.onObservation).toHaveBeenCalledWith("correct", "", "");
  });
});

it("lets the teacher adjust projection text without revealing answers or changing the timer", () => {
  const callbacks = props(); const onFontSizeChange = vi.fn();
  const { rerender } = render(<QuestionPracticeModal question={question()} {...callbacks} fontSize={40} onFontSizeChange={onFontSizeChange}/>);
  fireEvent.click(screen.getByRole("button", { name: "放大题目字号" }));
  expect(onFontSizeChange).toHaveBeenCalledWith(42);
  fireEvent.click(screen.getByRole("button", { name: "缩小题目字号" }));
  expect(onFontSizeChange).toHaveBeenLastCalledWith(38);
  expect(callbacks.onTimerAction).not.toHaveBeenCalled();
  expect(callbacks.onReveal).not.toHaveBeenCalled();
  expect(screen.queryByTestId("qpm-answer")).not.toBeInTheDocument();
  rerender(<QuestionPracticeModal question={question()} {...callbacks} fontSize={56} onFontSizeChange={onFontSizeChange}/>);
  expect(screen.getByRole("button", { name: "放大题目字号" })).toBeDisabled();
  rerender(<QuestionPracticeModal question={question()} {...callbacks} fontSize={28} onFontSizeChange={onFontSizeChange}/>);
  expect(screen.getByRole("button", { name: "缩小题目字号" })).toBeDisabled();
});

it("presents the question before its material and enlarges images without closing the active question", () => {
  const callbacks = props();
  render(<QuestionPracticeModal question={question()} {...callbacks}/>);
  const body = screen.getByRole("region", { name: "题目与讲解" });
  expect(body.firstElementChild).toBe(screen.getByTestId("qpm-stem"));
  const enlarge = screen.getByRole("button", { name: "放大题图 1" });
  enlarge.focus(); fireEvent.click(enlarge);
  expect(screen.getByRole("dialog", { name: "题图 1放大题图" })).toBeVisible();
  expect(screen.getByRole("button", { name: "关闭题图" })).toHaveFocus();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog", { name: "题图 1放大题图" })).not.toBeInTheDocument();
  expect(screen.getByTestId("question-practice-modal")).toBeVisible();
  expect(enlarge).toHaveFocus();
  expect(callbacks.onClose).not.toHaveBeenCalled();
  expect(callbacks.onTimerAction).not.toHaveBeenCalled();
  expect(screen.queryByTestId("qpm-answer")).not.toBeInTheDocument();
});
