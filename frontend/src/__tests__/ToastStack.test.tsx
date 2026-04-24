import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ToastStack } from "../components/ToastStack";

describe("ToastStack", () => {
  it("renders notifications and dismisses a toast", () => {
    const onDismiss = vi.fn();

    render(
      <ToastStack
        items={[
          {
            id: "toast_1",
            tone: "success",
            title: "模板已切换",
            detail: "当前已进入人口专题包。"
          }
        ]}
        onDismiss={onDismiss}
      />
    );

    expect(screen.getByText("模板已切换")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("关闭通知"));
    expect(onDismiss).toHaveBeenCalledWith("toast_1");
  });
});
