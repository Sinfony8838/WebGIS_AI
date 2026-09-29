import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PptBrushFloat } from "../components/PptBrushFloat";
import type { BrushSettings } from "../components/BrushOverlay";

describe("PptBrushFloat", () => {
  const settings: BrushSettings = { tool: "freehand", color: "#ff4444", lineWidth: 4 };
  const base = {
    settings,
    hasContent: false,
    onChangeSettings: vi.fn(),
    onUndo: vi.fn(),
    onClear: vi.fn(),
    onExit: vi.fn()
  };

  beforeEach(() => vi.clearAllMocks());
  afterEach(cleanup);

  it("selecting a tool applies it and collapses the settings", () => {
    const onChangeSettings = vi.fn();
    render(<PptBrushFloat {...base} onChangeSettings={onChangeSettings} />);
    expect(screen.getByTestId("ppt-brush-float")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "画笔工具箭头" }));
    expect(onChangeSettings).toHaveBeenCalledWith({ tool: "arrow" });
    expect(screen.queryByTestId("ppt-brush-float")).toBeNull();
    expect(screen.getByTestId("ppt-brush-mini")).toBeVisible();
  });

  it("keeps settings open when only picking a color, then re-expands from the handle", () => {
    render(<PptBrushFloat {...base} />);
    fireEvent.click(screen.getByRole("button", { name: "画笔颜色#4488ff" }));
    expect(base.onChangeSettings).toHaveBeenCalledWith({ color: "#4488ff" });
    expect(screen.getByTestId("ppt-brush-float")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "画笔工具橡皮" }));
    fireEvent.click(screen.getByRole("button", { name: "展开画笔设置" }));
    expect(screen.getByTestId("ppt-brush-float")).toBeVisible();
  });

  it("exits brush mode from both states", async () => {
    const { rerender } = render(<PptBrushFloat {...base} />);
    fireEvent.click(screen.getByTestId("ppt-brush-exit"));
    await waitFor(() => expect(base.onExit).toHaveBeenCalledTimes(1));
    rerender(<PptBrushFloat {...base} />);
    fireEvent.click(screen.getByRole("button", { name: "画笔工具直线" }));
    fireEvent.click(screen.getByTestId("ppt-brush-exit"));
    await waitFor(() => expect(base.onExit).toHaveBeenCalledTimes(2));
  });
});
