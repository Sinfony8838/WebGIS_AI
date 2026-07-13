import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CopilotWidget, exceedsDragThreshold, normalizePanelRect } from "../components/CopilotWidget";

class MockSpeechRecognition {
  static lastInstance: MockSpeechRecognition | null = null;

  lang = "";
  continuous = false;
  interimResults = false;
  onresult: ((event: { resultIndex?: number; results: ArrayLike<{ isFinal: boolean; length: number; 0: { transcript: string } }> }) => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn(() => {
    this.onend?.();
  });

  constructor() {
    MockSpeechRecognition.lastInstance = this;
  }

  emitTranscript(transcript: string) {
    this.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, length: 1, 0: { transcript } }]
    });
  }

  emitError(error: string) {
    this.onerror?.({ error });
    this.onend?.();
  }

  emitEndWithoutResult() {
    this.onend?.();
  }
}

function setSpeechRecognitionSupport(enabled: boolean) {
  const speechWindow = window as Window & typeof globalThis & { webkitSpeechRecognition?: typeof MockSpeechRecognition };
  if (enabled) {
    speechWindow.webkitSpeechRecognition = MockSpeechRecognition;
    return;
  }
  delete speechWindow.webkitSpeechRecognition;
}

function renderWidget(overrides: Partial<ComponentProps<typeof CopilotWidget>> = {}) {
  const onSubmit = vi.fn();
  const onInputChange = vi.fn();
  const onAssistantModeChange = vi.fn();
  const onConfirm = vi.fn();
  const onVoiceSubmit = vi.fn();
  const onVoiceNotice = vi.fn();

  render(
    <CopilotWidget
      assistantMode="tool"
      busy={false}
      currentJob={null}
      chatLog={[
        {
          role: "assistant",
          text: "课堂助教已准备就绪。",
          timestamp: "1"
        }
      ]}
      inputValue="搜索当前区域内港口"
      onInputChange={onInputChange}
      onAssistantModeChange={onAssistantModeChange}
      onSubmit={onSubmit}
      onConfirm={onConfirm}
      onVoiceSubmit={onVoiceSubmit}
      onVoiceNotice={onVoiceNotice}
      {...overrides}
    />
  );

  return { onSubmit, onInputChange, onAssistantModeChange, onConfirm, onVoiceSubmit, onVoiceNotice };
}

describe("CopilotWidget", () => {
  beforeEach(() => {
    window.localStorage.clear();
    MockSpeechRecognition.lastInstance = null;
    setSpeechRecognitionSupport(true);
  });

  afterEach(() => {
    cleanup();
    setSpeechRecognitionSupport(false);
    vi.clearAllMocks();
  });

  it("renders messages, submits input, and can minimize", () => {
    const { onSubmit } = renderWidget();

    expect(screen.getByText("课堂助教已准备就绪。")).toBeInTheDocument();
    fireEvent.submit(screen.getByTestId("copilot-input").closest("form")!);
    expect(onSubmit).toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText("最小化助教"));
    expect(screen.getByLabelText("展开智能助教")).toBeInTheDocument();
  });

  it("submits the final transcript after clicking the microphone", async () => {
    const { onVoiceSubmit } = renderWidget();

    fireEvent.click(screen.getByLabelText("开始语音控制"));
    expect(screen.getByText("正在聆听课堂指令，请开始说话。")).toBeInTheDocument();

    MockSpeechRecognition.lastInstance?.emitTranscript("我们把目光转向上海区域");

    await waitFor(() => {
      expect(onVoiceSubmit).toHaveBeenCalledWith("我们把目光转向上海区域");
    });
    expect(screen.getByText("最近转写：我们把目光转向上海区域")).toBeInTheDocument();
  });

  it("shows unsupported status when the browser does not provide speech recognition", () => {
    setSpeechRecognitionSupport(false);
    cleanup();
    renderWidget();

    expect(screen.getByText("当前浏览器不支持语音控制，请使用桌面版 Chrome 或 Edge。")).toBeInTheDocument();
    expect(screen.getByLabelText("开始语音控制")).toBeDisabled();
  });

  it("keeps the microphone disabled while a job is running", () => {
    renderWidget({ busy: true });
    expect(screen.getByLabelText("开始语音控制")).toBeDisabled();
  });

  it("reports microphone permission errors through the notice callback", async () => {
    const { onVoiceNotice, onVoiceSubmit } = renderWidget();

    fireEvent.click(screen.getByLabelText("开始语音控制"));
    MockSpeechRecognition.lastInstance?.emitError("not-allowed");

    await waitFor(() => {
      expect(onVoiceNotice).toHaveBeenCalledWith(
        "error",
        "语音权限不可用",
        "浏览器没有授予麦克风权限，请允许访问麦克风后重试。"
      );
    });
    expect(onVoiceSubmit).not.toHaveBeenCalled();
  });

  it("reports empty recognition sessions", async () => {
    const { onVoiceNotice, onVoiceSubmit } = renderWidget();

    fireEvent.click(screen.getByLabelText("开始语音控制"));
    MockSpeechRecognition.lastInstance?.emitEndWithoutResult();

    await waitFor(() => {
      expect(onVoiceNotice).toHaveBeenCalledWith(
        "error",
        "没有识别到语音",
        "没有识别到有效语音，请点击麦克风后直接说出课堂指令。"
      );
    });
    expect(onVoiceSubmit).not.toHaveBeenCalled();
  });

  it("treats orb movement beyond the threshold as a drag gesture", () => {
    expect(exceedsDragThreshold({ x: 20, y: 20 }, { x: 72, y: 96 })).toBe(true);
    expect(exceedsDragThreshold({ x: 20, y: 20 }, { x: 22, y: 23 })).toBe(false);
  });

  it("normalizes persisted panel sizes to safe minimum bounds", () => {
    const normalized = normalizePanelRect({ x: 9999, y: -20, width: 120, height: 100 });

    expect(normalized.width).toBeGreaterThanOrEqual(440);
    expect(normalized.height).toBeGreaterThanOrEqual(420);
    expect(normalized.x).toBeGreaterThanOrEqual(8);
    expect(normalized.y).toBeGreaterThanOrEqual(8);
  });

  it("keeps scrollable content separate from the input form in compact mode", () => {
    window.localStorage.setItem(
      "webgis-ai-copilot-panel",
      JSON.stringify({ x: 24, y: 24, width: 520, height: 440 })
    );

    renderWidget({
      currentJob: {
        job_id: "job_compact",
        project_id: "project_1",
        job_type: "assistant",
        title: "compact",
        workflow_type: "assistant_message",
        status: "completed",
        updated_at: "1",
        steps: [],
        stages: {
          routing: { status: "success", summary: "Intent: knowledge", detail: "" },
          retrieval: { status: "success", summary: "Answer type: identity", detail: "" }
        },
        result: {
          knowledge: {
            direct_answer: "assistant",
            mechanism_explanation: "helper",
            map_grounding: "map",
            teaching_points: [],
            citations: [],
            confidence: 0.99,
            answer_type: "assistant_identity"
          }
        }
      },
      assistantMode: "knowledge"
    });

    expect(document.querySelector(".copilot-widget")).toHaveClass("compact");
    expect(document.querySelector(".copilot-widget-content")).toBeInTheDocument();
    expect(screen.getByTestId("copilot-chat-log").closest(".copilot-widget-content")).not.toBeNull();
    expect(screen.getByTestId("copilot-input").closest(".copilot-widget-form")).toBeInTheDocument();
  });

  it("renders v2 confirmation and citation cards", () => {
    const { onConfirm, onAssistantModeChange } = renderWidget({
      assistantMode: "knowledge",
      currentJob: {
        job_id: "job_1",
        project_id: "project_1",
        job_type: "assistant",
        title: "知识回答",
        workflow_type: "assistant_message",
        status: "completed",
        updated_at: "1",
        steps: [],
        stages: {
          routing: { status: "success", summary: "Intent: knowledge", detail: "" }
        },
        result: {
          requires_confirmation: true,
          confirmation_id: "confirm_1",
          citations: [{ title: "CAS", url: "https://www.igsnrr.ac.cn/" }],
          knowledge: {
            direct_answer: "胡焕庸线是人口地理分界线。",
            mechanism_explanation: "它反映了东南密集、西北稀疏。",
            map_grounding: "Grounded on current map.",
            teaching_points: ["点 1"],
            citations: [{ title: "CAS", url: "https://www.igsnrr.ac.cn/" }],
            confidence: 0.9,
            answer_type: "regional_geography"
          }
        }
      }
    });

    // v1.2: the per-stage "ROUTING / RETRIEVAL / …" debug strip and the
    // "回答类型 / 置信度" knowledge meta card were retired in favour of a
    // single ChatGPT-style thinking indicator. Only functional cards
    // (confirmation + citations) remain.
    expect(screen.queryByText(/回答类型：/)).not.toBeInTheDocument();
    expect(screen.queryByText(/置信度：/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^ROUTING$/i)).not.toBeInTheDocument();
    expect(screen.getByText("引用来源")).toBeInTheDocument();
    fireEvent.click(screen.getByText("知识助手"));
    fireEvent.click(screen.getByText("确认执行"));
    expect(onAssistantModeChange).toHaveBeenCalledWith("knowledge");
    expect(onConfirm).toHaveBeenCalledWith("confirm_1", "approve");
  });

  it("shows a generic thinking indicator while busy and hides it when done", () => {
    const { rerender } = render(
      <CopilotWidget
        assistantMode="knowledge"
        busy
        currentJob={{
          job_id: "job_pending",
          project_id: "project_1",
          job_type: "assistant",
          title: "处理中",
          workflow_type: "assistant_message",
          status: "running",
          updated_at: "1",
          steps: [],
          stages: {
            routing: { status: "success", summary: "Intent: knowledge", detail: "" },
            retrieval: { status: "running", summary: "正在查询", detail: "" },
            planning: { status: "pending", summary: "", detail: "" }
          },
          result: null
        }}
        chatLog={[
          { role: "user", text: "胡焕庸线两侧降水差异如何？", timestamp: "1" }
        ]}
        inputValue=""
        onInputChange={vi.fn()}
        onAssistantModeChange={vi.fn()}
        onSubmit={vi.fn()}
        onConfirm={vi.fn()}
        onVoiceSubmit={vi.fn()}
        onVoiceNotice={vi.fn()}
      />
    );

    const indicator = screen.getByTestId("copilot-thinking");
    expect(indicator).toBeInTheDocument();
    // Friendly verb picked from the running stage (retrieval → 正在检索知识库).
    expect(indicator).toHaveTextContent("正在检索知识库");

    // Re-render the same root with busy=false; the indicator must disappear.
    rerender(
      <CopilotWidget
        assistantMode="knowledge"
        busy={false}
        currentJob={null}
        chatLog={[{ role: "assistant", text: "答复已生成。", timestamp: "1" }]}
        inputValue=""
        onInputChange={vi.fn()}
        onAssistantModeChange={vi.fn()}
        onSubmit={vi.fn()}
        onConfirm={vi.fn()}
        onVoiceSubmit={vi.fn()}
        onVoiceNotice={vi.fn()}
      />
    );
    expect(screen.queryByTestId("copilot-thinking")).not.toBeInTheDocument();
  });

  it("falls back to generic 正在思考 when no stage is running but still busy", () => {
    render(
      <CopilotWidget
        assistantMode="tool"
        busy
        currentJob={null}
        chatLog={[]}
        inputValue=""
        onInputChange={vi.fn()}
        onAssistantModeChange={vi.fn()}
        onSubmit={vi.fn()}
        onConfirm={vi.fn()}
        onVoiceSubmit={vi.fn()}
        onVoiceNotice={vi.fn()}
      />
    );
    expect(screen.getByTestId("copilot-thinking")).toHaveTextContent("正在思考");
  });
});
