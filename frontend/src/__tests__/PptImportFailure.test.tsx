import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PptImportFailure } from "../components/PptImportFailure";
afterEach(cleanup);
it("waits for the teacher to choose simple preview and keeps the failure actionable", () => {
  const onSimplePreview = vi.fn(); const onRetry = vi.fn(); const onClose = vi.fn();
  render(<PptImportFailure fileName="课堂.pptx" message="Office 无法打开课件" busy={false} {...{ onSimplePreview, onRetry, onClose }} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Office 无法打开课件");
  expect(onSimplePreview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "使用简易预览" }));
  expect(onSimplePreview).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "重新渲染" }));
  expect(onRetry).toHaveBeenCalledTimes(1);
});
