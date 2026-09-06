import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { AgentControlOverlay } from "../components/AgentControlOverlay";

afterEach(cleanup);

describe("AgentControlOverlay（智能交互操控光晕层）", () => {
  it("空闲时不渲染", () => {
    const { container } = render(
      <AgentControlOverlay active={false} listening={false} partialTranscript="" capturedCommand="" workingDetail="" pulseSignal={0} />
    );
    expect(container.querySelector(".agent-control-overlay")).toBeNull();
    expect(screen.queryByTestId("agent-control-overlay")).toBeNull();
  });

  it("执行中显示「智能交互中」徽标与当前动作副文案", () => {
    render(
      <AgentControlOverlay active listening={false} partialTranscript="" capturedCommand="" workingDetail="正在执行 1 项操作" pulseSignal={0} />
    );
    expect(screen.getByTestId("agent-control-overlay").className).toContain("working");
    expect(screen.getByText("智能交互中")).toBeInTheDocument();
    expect(screen.getByText("正在执行 1 项操作")).toBeInTheDocument();
  });

  it("聆听态显示绿色徽标与实时转写", () => {
    render(
      <AgentControlOverlay active={false} listening partialTranscript="小智切…" capturedCommand="" workingDetail="" pulseSignal={0} />
    );
    const badge = document.querySelector(".agent-control-badge") as HTMLElement;
    expect(badge.getAttribute("data-state")).toBe("listening");
    expect(screen.getByText("聆听中")).toBeInTheDocument();
    expect(screen.getByText(/小智切…/)).toBeInTheDocument();
  });

  it("捕获指令态显示剥离后的指令文本", () => {
    render(
      <AgentControlOverlay active={false} listening partialTranscript="" capturedCommand="切换到三维地球" workingDetail="" pulseSignal={0} />
    );
    const badge = document.querySelector(".agent-control-badge") as HTMLElement;
    expect(badge.getAttribute("data-state")).toBe("captured");
    expect(screen.getByText(/“切换到三维地球”/)).toBeInTheDocument();
  });

  it("pulseSignal 自增时短暂叠加脉冲高亮类", () => {
    vi.useFakeTimers();
    const { rerender } = render(
      <AgentControlOverlay active listening={false} partialTranscript="" capturedCommand="" workingDetail="" pulseSignal={0} />
    );
    rerender(
      <AgentControlOverlay active listening={false} partialTranscript="" capturedCommand="" workingDetail="" pulseSignal={1} />
    );
    expect(screen.getByTestId("agent-control-overlay").className).toContain("pulse");
    act(() => {
      vi.advanceTimersByTime(700);
    });
    expect(screen.getByTestId("agent-control-overlay").className).not.toContain("pulse");
    vi.useRealTimers();
  });

  it("active 变 false 后延迟淡出移除", () => {
    vi.useFakeTimers();
    const { rerender } = render(
      <AgentControlOverlay active listening={false} partialTranscript="" capturedCommand="" workingDetail="" pulseSignal={0} />
    );
    rerender(
      <AgentControlOverlay active={false} listening={false} partialTranscript="" capturedCommand="" workingDetail="" pulseSignal={0} />
    );
    // 淡出窗口内仍在（渐隐动画）。
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(screen.getByTestId("agent-control-overlay")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(800);
    });
    expect(screen.queryByTestId("agent-control-overlay")).toBeNull();
    vi.useRealTimers();
  });
});
