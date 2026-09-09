import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThinkingIndicator } from "../components/ThinkingIndicator";

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("ThinkingIndicator", () => {
  it("shows elapsed waiting without inventing progress and releases its timer", () => {
    vi.useFakeTimers();
    const view = render(<ThinkingIndicator label="正在检索知识库" />);
    expect(screen.getByRole("status")).toHaveTextContent("正在检索知识库");
    act(() => vi.advanceTimersByTime(21000));
    expect(screen.getByText("21 秒")).toBeInTheDocument();
    expect(screen.getByText(/本次处理时间较长/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("正在检索知识库");
    view.rerender(<ThinkingIndicator label="正在整合答复" />);
    expect(screen.getByRole("status")).toHaveTextContent("正在整合答复");
    expect(screen.getByText("21 秒")).toBeInTheDocument();
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
    render(<ThinkingIndicator />);
    expect(screen.getByText("0 秒")).toBeInTheDocument();
  });
});
