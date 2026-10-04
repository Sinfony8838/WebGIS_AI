import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BasemapLoadStatus } from "../components/BasemapLoadStatus";
import { BasemapLoadWatchdog } from "../lib/basemapLoadStatus";

afterEach(() => vi.useRealTimers());

describe("basemap loading recovery", () => {
  it("reports a stalled source, then accepts an actual late tile", () => {
    vi.useFakeTimers();
    const update = vi.fn();
    const watch = new BasemapLoadWatchdog(update);
    act(() => vi.advanceTimersByTime(12_000));
    expect(update.mock.calls.map(([phase]) => phase)).toEqual(["loading", "error"]);
    watch.ready();
    watch.failed();
    expect(update).toHaveBeenLastCalledWith("ready");
    watch.dispose();
  });

  it("cancels obsolete timers and callbacks when changing view or source", () => {
    vi.useFakeTimers();
    const update = vi.fn();
    const watch = new BasemapLoadWatchdog(update);
    watch.dispose();
    act(() => vi.advanceTimersByTime(12_000));
    watch.ready();
    watch.failed();
    expect(update.mock.calls).toEqual([["loading"]]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("offers recovery only on failure and performs no automatic provider change", () => {
    const onRetry = vi.fn(), onRestore = vi.fn();
    const props = { title: "兼容底图", busy: false, onRetry, onRestore };
    const view = render(<BasemapLoadStatus {...props} phase="loading" />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    view.rerender(<BasemapLoadStatus {...props} phase="error" />);
    expect(onRestore).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "重试当前底图" }));
    expect(onRetry).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "切换高德标准" }));
    expect(onRestore).toHaveBeenCalledOnce();
    view.rerender(<BasemapLoadStatus {...props} phase="ready" />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
