import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BrushToolbar } from "../components/BrushToolbar";
import type { BrushSettings } from "../components/BrushOverlay";

describe("BrushToolbar", () => {
  afterEach(cleanup);
  const initial: BrushSettings = { tool: "freehand", color: "#ff4444", lineWidth: 4 };

  it("starts compact and preserves selected color and width when picking a tool collapses it", () => {
    function Harness() {
      const [settings, setSettings] = useState(initial);
      return <BrushToolbar settings={settings} hasContent={false} onUndo={vi.fn()} onClear={vi.fn()}
        onChangeSettings={next => setSettings(previous => ({ ...previous, ...next }))} />;
    }
    render(<Harness />);
    expect(screen.queryByRole("toolbar")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "展开地图画笔设置" }));
    fireEvent.click(screen.getByRole("button", { name: "蓝", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "粗", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "箭头", exact: true }));
    expect(screen.queryByRole("toolbar")).toBeNull();
    expect(screen.getByRole("button", { name: "展开地图画笔设置" })).toHaveTextContent("箭头");
    fireEvent.click(screen.getByRole("button", { name: "展开地图画笔设置" }));
    for (const name of ["蓝", "粗", "箭头"]) {
      expect(screen.getByRole("button", { name, exact: true })).toHaveAttribute("aria-pressed", "true");
    }
  });

  it("allows undo after clear even when the canvas is empty", () => {
    const props = { settings: initial, onChangeSettings: vi.fn(), onUndo: vi.fn(), onClear: vi.fn() };
    const { rerender } = render(<BrushToolbar {...props} hasContent={false} canUndo />);
    fireEvent.click(screen.getByRole("button", { name: "展开地图画笔设置" }));
    expect(screen.getByRole("button", { name: "撤销" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "清除" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "撤销" }));
    expect(props.onUndo).toHaveBeenCalledTimes(1);
    rerender(<BrushToolbar {...props} hasContent={false} canUndo={false} />);
    expect(screen.getByRole("button", { name: "撤销" })).toBeDisabled();
  });

  it("keeps undo and clear gated by the current drawing and passes actions to the owner", () => {
    const props = { settings: initial, onChangeSettings: vi.fn(), onUndo: vi.fn(), onClear: vi.fn() };
    const { rerender } = render(<BrushToolbar {...props} hasContent={false} />);
    fireEvent.click(screen.getByRole("button", { name: "展开地图画笔设置" }));
    expect(screen.getByRole("button", { name: "撤销" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "清除" })).toBeDisabled();
    rerender(<BrushToolbar {...props} hasContent />);
    fireEvent.click(screen.getByRole("button", { name: "撤销" }));
    fireEvent.click(screen.getByRole("button", { name: "清除" }));
    expect(props.onUndo).toHaveBeenCalledTimes(1);
    expect(props.onClear).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "收起地图画笔设置" }));
    expect(screen.queryByRole("toolbar")).toBeNull();
  });
});
