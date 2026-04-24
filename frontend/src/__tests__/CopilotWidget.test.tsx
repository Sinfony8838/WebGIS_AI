import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CopilotWidget, exceedsDragThreshold, normalizePanelRect } from "../components/CopilotWidget";

describe("CopilotWidget", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders messages, submits input, and can minimize", () => {
    const onSubmit = vi.fn();
    const onInputChange = vi.fn();

    render(
      <CopilotWidget
        busy={false}
        currentJob={null}
        chatLog={[
          {
            role: "assistant",
            text: "\u8bfe\u5802\u52a9\u6559\u5df2\u51c6\u5907\u5c31\u7eea\u3002",
            timestamp: "1"
          }
        ]}
        inputValue="\u641c\u7d22\u5f53\u524d\u533a\u57df\u5185\u6e2f\u53e3"
        onInputChange={onInputChange}
        onSubmit={onSubmit}
      />
    );

    expect(screen.getByText("\u8bfe\u5802\u52a9\u6559\u5df2\u51c6\u5907\u5c31\u7eea\u3002")).toBeInTheDocument();
    fireEvent.submit(screen.getByTestId("copilot-input").closest("form")!);
    expect(onSubmit).toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText("\u6700\u5c0f\u5316\u52a9\u6559"));
    expect(screen.getByLabelText("\u5c55\u5f00\u667a\u80fd\u52a9\u6559")).toBeInTheDocument();
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
});
