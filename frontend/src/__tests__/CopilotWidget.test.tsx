import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  const onConfirm = vi.fn();
  const onVoiceSubmit = vi.fn();
  const onVoiceNotice = vi.fn();
  const onQuickPrompt = vi.fn();

  render(
    <CopilotWidget
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
      onSubmit={onSubmit}
      onConfirm={onConfirm}
      onVoiceSubmit={onVoiceSubmit}
      onVoiceNotice={onVoiceNotice}
      onQuickPrompt={onQuickPrompt}
      {...overrides}
    />
  );

  // The widget defaults to minimized; expand so tests can exercise the panel.
  fireEvent.click(screen.getByLabelText("展开智能助教"));

  return { onSubmit, onInputChange, onConfirm, onVoiceSubmit, onVoiceNotice, onQuickPrompt };
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

  it("renders assistant replies naturally without rebuilding legacy teaching cards", () => {
    renderWidget({
      chatLog: [
        {
          role: "assistant",
          text: "东部人口密集与自然条件、经济机会相关。\n\n教学处理：\n- 证据或观察点：基于当前地图：可见图层包括 人口密度。\n- 给学生的问题：观察高值区与低值区的分布。\n- 教师收束语或下一步：收束到区域认知方法。",
          timestamp: "1",
          teaching_contract: {
            evidence: "基于当前地图：可见图层包括 人口密度。",
            question: "观察高值区与低值区的分布。",
            closing: "收束到区域认知方法：位置-格局-成因。"
          }
        }
      ]
    });

    expect(screen.queryByText("证据或观察点")).toBeNull();
    expect(screen.queryByText("给学生的问题")).toBeNull();
    expect(screen.queryByRole("button", { name: "复制问题" })).toBeNull();
    expect(screen.getByText(/东部人口密集与自然条件/)).toBeInTheDocument();
  });

  it("fills the composer instead of auto-sending when the 读图 chip is clicked", () => {
    const { onInputChange, onQuickPrompt } = renderWidget();

    expect(screen.getByTestId("copilot-capability-chips")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("copilot-chip-read-map"));

    expect(onQuickPrompt).not.toHaveBeenCalled();
    expect(onInputChange).toHaveBeenCalledTimes(1);
    expect(String(onInputChange.mock.calls[0][0])).toContain("附加的图片");
  });

  it("previews, removes, uploads, and sends an image without text", () => {
    const onRemoveImage = vi.fn();
    const onUploadImage = vi.fn();
    const { onSubmit } = renderWidget({
      inputValue: "",
      pendingImage: {
        artifact_id: "artifact_1",
        title: "河流地貌",
        public_url: "http://localhost/image.png",
        mime_type: "image/png"
      },
      onRemoveImage,
      onUploadImage
    });

    expect(screen.getByTestId("copilot-image-preview")).toHaveTextContent("河流地貌");
    fireEvent.submit(screen.getByTestId("copilot-input").closest("form")!);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByLabelText("移除待发送图片"));
    expect(onRemoveImage).toHaveBeenCalledTimes(1);

    const file = new File(["image"], "map.webp", { type: "image/webp" });
    const input = document.querySelector(".copilot-image-input") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    expect(onUploadImage).toHaveBeenCalledWith(file);
  });

  it("accepts an image dragged from the project library", () => {
    const onAttachImage = vi.fn();
    renderWidget({ onAttachImage });
    const form = screen.getByTestId("copilot-input").closest("form")!;
    const attachment = { artifact_id: "artifact_2", title: "气候图", public_url: "/files/climate.png" };
    fireEvent.drop(form, {
      dataTransfer: {
        files: [],
        getData: (type: string) => type === "application/x-webgis-image" ? JSON.stringify(attachment) : ""
      }
    });
    expect(onAttachImage).toHaveBeenCalledWith(attachment);
  });

  it("shows the teaching phase chip when a workflow phase is active", () => {
    renderWidget({ teachingPhase: "in_class" });
    expect(screen.getByTestId("copilot-phase-chip")).toHaveTextContent("课堂进行中");
  });

  it("hides the phase chip outside the lesson workflow", () => {
    renderWidget();
    expect(screen.queryByTestId("copilot-phase-chip")).toBeNull();
  });

  it("reorders capability chips by phase so the most relevant action comes first", () => {
    renderWidget({ teachingPhase: "post_class" });
    const chips = within(screen.getByTestId("copilot-capability-chips")).getAllByRole("button");
    expect(chips[0]).toHaveTextContent("复盘");

    cleanup();
    window.localStorage.clear();
    setSpeechRecognitionSupport(true);
    renderWidget({ teachingPhase: "in_class" });
    const inClassChips = within(screen.getByTestId("copilot-capability-chips")).getAllByRole("button");
    expect(inClassChips[0]).toHaveTextContent("读图");
  });

  it("shows an intent badge derived from the routed intent on assistant messages", () => {
    renderWidget({
      chatLog: [
        {
          role: "assistant",
          text: "已切换到地形底图。",
          timestamp: "1",
          intent: "teaching_action"
        }
      ]
    });

    const badge = screen.getByTestId("copilot-intent-badge");
    expect(badge).toHaveTextContent("操作");
  });

  it("renders a collapsible tool-use trace when actions_executed is present", () => {
    renderWidget({
      chatLog: [
        {
          role: "assistant",
          text: "已切换到地形底图。",
          timestamp: "1",
          intent: "teaching_action",
          actions_executed: [
            {
              action: { tool_name: "switch_basemap", tool_params: { basemap_id: "terrain" } },
              risk_level: "low",
              result: { basemap_id: "terrain" }
            }
          ]
        }
      ]
    });

    const trace = screen.getByTestId("copilot-tool-trace-0");
    // Collapsed by default: the toggle is visible but the tool name is hidden.
    expect(trace).toHaveTextContent("工具调用 (1)");
    expect(within(trace).queryByText("switch_basemap")).toBeNull();

    // Expand the trace.
    fireEvent.click(screen.getByText(/工具调用 \(1\)/));
    expect(trace).toHaveTextContent("switch_basemap");
    expect(trace).toHaveTextContent("✓");
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

  it("renders the teaching pet in both the collapsed orb and expanded header", () => {
    renderWidget();
    expect(screen.getByTestId("teaching-pet-header")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("最小化助教"));
    expect(screen.getByTestId("teaching-pet-orb")).toBeInTheDocument();
  });

  it("shows the confirm pose while a high-risk confirmation is pending", () => {
    renderWidget({
      busy: true,
      currentJob: {
        job_id: "job_confirm",
        project_id: "project_1",
        job_type: "assistant",
        title: "高风险操作",
        workflow_type: "assistant_message",
        status: "running",
        updated_at: "1",
        steps: [],
        stages: { execution: { status: "running", summary: "", detail: "" } },
        result: {
          requires_confirmation: true,
          confirmation_id: "confirm_pet",
          actions_planned: [
            {
              name: "delete_layer",
              target: "layer",
              category: "map",
              risk_level: "high",
              reversible: false,
              requires_confirmation: true,
              requires_map_context: true,
              tool_params: {}
            }
          ]
        }
      }
    });

    // Confirmation must outrank the map-execution busy state.
    expect(screen.getByTestId("teaching-pet-header")).toHaveAttribute("data-pose", "confirm");
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
      }
    });

    expect(document.querySelector(".copilot-widget")).toHaveClass("compact");
    expect(document.querySelector(".copilot-widget-content")).toBeInTheDocument();
    expect(screen.getByTestId("copilot-chat-log").closest(".copilot-widget-content")).not.toBeNull();
    expect(screen.getByTestId("copilot-input").closest(".copilot-widget-form")).toBeInTheDocument();
  });

  it("renders the teaching agent without a mode switch or coding copy", () => {
    renderWidget();

    expect(screen.getByText("专业教学智能体")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByText("知识助手")).not.toBeInTheDocument();
    expect(screen.queryByText("Agent 助手")).not.toBeInTheDocument();
    const placeholder = screen.getByTestId("copilot-input").getAttribute("placeholder") || "";
    expect(placeholder).not.toMatch(/检查项目结构|coding agent|AGENT_AUTO_APPROVE/i);
  });

  it("shows the plan summary card for teaching actions", () => {
    renderWidget({
      currentJob: {
        job_id: "job_plan",
        project_id: "project_1",
        job_type: "assistant",
        title: "切换底图",
        workflow_type: "assistant_message",
        status: "completed",
        updated_at: "1",
        steps: [],
        stages: { routing: { status: "success", summary: "Intent: teaching_action", detail: "" } },
        result: {
          actions_planned: [
            { name: "switch_basemap", risk_level: "low", tool_params: { basemap_id: "amap_light" } }
          ]
        }
      }
    });

    expect(screen.getByText("计划摘要")).toBeInTheDocument();
  });

  it("renders v2 confirmation and citation cards", () => {
    const { onConfirm } = renderWidget({
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
    fireEvent.click(screen.getByText("确认执行"));
    expect(onConfirm).toHaveBeenCalledWith("confirm_1", "approve");
  });

  it("shows a generic thinking indicator while busy and hides it when done", () => {
    const { rerender } = render(
      <CopilotWidget
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
        onSubmit={vi.fn()}
        onConfirm={vi.fn()}
        onVoiceSubmit={vi.fn()}
        onVoiceNotice={vi.fn()}
      />
    );

    fireEvent.click(screen.getByLabelText("展开智能助教"));

    const indicator = screen.getByTestId("copilot-thinking");
    expect(indicator).toBeInTheDocument();
    // Friendly verb picked from the running stage (retrieval → 正在检索知识库).
    expect(indicator).toHaveTextContent("正在检索知识库");

    // Re-render the same root with busy=false; the indicator must disappear.
    rerender(
      <CopilotWidget
        busy={false}
        currentJob={null}
        chatLog={[{ role: "assistant", text: "答复已生成。", timestamp: "1" }]}
        inputValue=""
        onInputChange={vi.fn()}
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
        busy
        currentJob={null}
        chatLog={[]}
        inputValue=""
        onInputChange={vi.fn()}
        onSubmit={vi.fn()}
        onConfirm={vi.fn()}
        onVoiceSubmit={vi.fn()}
        onVoiceNotice={vi.fn()}
      />
    );
    fireEvent.click(screen.getByLabelText("展开智能助教"));
    expect(screen.getByTestId("copilot-thinking")).toHaveTextContent("正在思考");
  });
});
