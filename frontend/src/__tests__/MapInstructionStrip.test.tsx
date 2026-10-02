import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MapInstructionStrip } from "../components/MapInstructionStrip";
import type { InteractionMode } from "../components/MapToolRail";

describe("MapInstructionStrip", () => {
  afterEach(cleanup);

  it("keeps finish and cancel available with the lengthy help closed", () => {
    const onFinishMeasure = vi.fn();
    const onCancel = vi.fn();
    render(<MapInstructionStrip mode="measure" measureTotalKm={12.345} hasSearchArea={false}
      onCancel={onCancel} onFinishMeasure={onFinishMeasure} />);
    expect(screen.getByLabelText("当前测距")).toHaveTextContent("12.35 千米");
    expect(screen.queryByText(/依次点击地图添加测点/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onFinishMeasure).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("opens current help on demand and closes it when the tool changes", () => {
    const props = { hasSearchArea: true, onCancel: vi.fn() };
    const { rerender } = render(<MapInstructionStrip {...props} mode="draw-search" />);
    fireEvent.click(screen.getByRole("button", { name: "绘区模式操作帮助" }));
    expect(screen.getByText(/已存在检索区/)).toBeVisible();
    expect(screen.getByRole("button", { name: "绘区模式操作帮助" })).toHaveAttribute("aria-expanded", "true");
    rerender(<MapInstructionStrip {...props} mode="brush" />);
    expect(screen.queryByText(/已存在检索区/)).toBeNull();
    expect(screen.getByRole("button", { name: "画笔模式操作帮助" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "完成" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "画笔模式操作帮助" }));
    expect(screen.getByText(/在地图上自由圈画/)).toBeVisible();
    rerender(<MapInstructionStrip {...props} mode="browse" />);
    expect(screen.queryByRole("region")).toBeNull();
  });

  it.each<InteractionMode>(["annotate", "measure", "draw-search", "brush"])("keeps a clickable exit for %s", (mode) => {
    const onCancel = vi.fn();
    render(<MapInstructionStrip mode={mode} hasSearchArea={false} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
