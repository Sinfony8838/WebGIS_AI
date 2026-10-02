import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ProfileManagerBar } from "../components/ProfileManagerBar";

describe("ProfileManagerBar", () => {
  afterEach(cleanup);

  it("keeps one-click visibility available while detailed record controls start collapsed", () => {
    const onToggleCollapsed = vi.fn();
    const { rerender } = render(<ProfileManagerBar count={2} collapsed={false} onToggleCollapsed={onToggleCollapsed}>
      <button type="button">人口密度变化</button><button type="button">地形剖面</button>
    </ProfileManagerBar>);
    expect(screen.queryByRole("button", { name: "人口密度变化" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "一键暂收全部剖面" }));
    expect(onToggleCollapsed).toHaveBeenCalledTimes(1);
    rerender(<ProfileManagerBar count={2} collapsed onToggleCollapsed={onToggleCollapsed}>
      <button type="button">人口密度变化</button><button type="button">地形剖面</button>
    </ProfileManagerBar>);
    expect(screen.getByRole("button", { name: "恢复显示全部剖面" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "展开剖面管理" }));
    expect(screen.getByRole("button", { name: "人口密度变化" })).toBeVisible();
    expect(screen.getByRole("button", { name: "人口密度变化" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "地形剖面" })).toBeVisible();
    fireEvent.keyDown(screen.getByRole("button", { name: "地形剖面" }), { key: "Escape" });
    expect(screen.queryByRole("button", { name: "地形剖面" })).toBeNull();
    expect(screen.getByRole("button", { name: "展开剖面管理" })).toHaveFocus();
  });

  it("passes record actions through and dismisses on outside interaction without changing windows", () => {
    const onOpen = vi.fn(), onToggleCollapsed = vi.fn();
    render(<ProfileManagerBar count={1} collapsed={false} onToggleCollapsed={onToggleCollapsed}>
      <button type="button" onClick={onOpen}>打开测线 1 地形</button>
    </ProfileManagerBar>);
    fireEvent.click(screen.getByRole("button", { name: "展开剖面管理" }));
    fireEvent.click(screen.getByRole("button", { name: "打开测线 1 地形" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("button", { name: "打开测线 1 地形" })).toBeNull();
    expect(onToggleCollapsed).not.toHaveBeenCalled();
  });
});
