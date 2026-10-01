import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DocxImportReview, type ImportReviewApplyPayload } from "../components/DocxImportReview";
import type { LessonDocxUnclassified, LessonStage } from "../types";

vi.mock("../api", () => ({
  buildAuthenticatedUrl: (path: string) => path
}));

const stages = [
  { stage_id: "s1", title: "情境导入", scene: {} },
  { stage_id: "s2", title: "成因探究", scene: {} }
] as unknown as LessonStage[];

const textItem: LessonDocxUnclassified = {
  kind: "text",
  heading: "未知标题",
  text: "一段教师手写的补充说明"
};

const imageItem: LessonDocxUnclassified = {
  kind: "image",
  name: "map.png",
  content_type: "image/png",
  url: "/files/uploads/p1/lesson_imports/d1/map.png"
};

afterEach(cleanup);

describe("DocxImportReview", () => {
  it("renders source text, origin and recognition result for unassigned items", () => {
    render(<DocxImportReview mapping={[]} unclassified={[textItem]} stages={stages} busy={false} onApply={vi.fn()} />);
    expect(screen.getByTestId("dir-item-0")).toHaveAttribute("data-status", "unassigned");
    expect(screen.getByText("段落 · 未知标题 · #1")).toBeInTheDocument();
    expect(screen.getByText("一段教师手写的补充说明")).toBeInTheDocument();
    expect(screen.getByTestId("dir-result-0")).toHaveTextContent("未归类");
  });

  it("applies a section assignment with append mode", () => {
    const onApply = vi.fn();
    render(<DocxImportReview mapping={[]} unclassified={[textItem]} stages={stages} busy={false} onApply={onApply} />);
    fireEvent.change(screen.getByLabelText("选择教案字段（#1）"), { target: { value: "objectives" } });
    fireEvent.click(screen.getByRole("button", { name: "采用" }));
    expect(onApply).toHaveBeenCalledWith<ImportReviewApplyPayload[]>({
      item_index: 0,
      action: "assign",
      target: { section: "objectives" },
      mode: "append"
    });
  });

  it("applies a stage-column assignment with replace mode", () => {
    const onApply = vi.fn();
    render(<DocxImportReview mapping={[]} unclassified={[textItem]} stages={stages} busy={false} onApply={onApply} />);
    fireEvent.change(screen.getByLabelText("选择归类方式（#1）"), { target: { value: "stage" } });
    fireEvent.change(screen.getByLabelText("选择目标环节（#1）"), { target: { value: "s2" } });
    fireEvent.change(screen.getByLabelText("选择环节栏目（#1）"), { target: { value: "material" } });
    fireEvent.change(screen.getByLabelText("选择写入效果（#1）"), { target: { value: "replace" } });
    fireEvent.click(screen.getByRole("button", { name: "采用" }));
    expect(onApply).toHaveBeenCalledWith<ImportReviewApplyPayload[]>({
      item_index: 0,
      action: "assign",
      target: { stage_id: "s2", column: "material" },
      mode: "replace"
    });
  });

  it("binds an image to a stage material list", () => {
    const onApply = vi.fn();
    render(<DocxImportReview mapping={[]} unclassified={[imageItem]} stages={stages} busy={false} onApply={onApply} />);
    fireEvent.change(screen.getByLabelText("选择图片目标环节（#1）"), { target: { value: "s2" } });
    fireEvent.click(screen.getByRole("button", { name: "绑定到环节素材" }));
    expect(onApply).toHaveBeenCalledWith<ImportReviewApplyPayload[]>({
      item_index: 0,
      action: "assign",
      target: { stage_id: "s2" }
    });
    expect(screen.getByAltText("map.png")).toBeInTheDocument();
  });

  it("marks items ignored and shows assignment results", () => {
    const assigned: LessonDocxUnclassified = {
      ...textItem,
      status: "assigned",
      assignment: { kind: "section", section: "objectives", label: "教学目标" }
    };
    const onApply = vi.fn();
    render(<DocxImportReview mapping={[]} unclassified={[textItem, assigned]} stages={stages} busy={false} onApply={onApply} />);
    expect(screen.getByTestId("dir-result-1")).toHaveTextContent("教案字段：教学目标");
    fireEvent.click(screen.getAllByRole("button", { name: "忽略" })[0]);
    expect(onApply).toHaveBeenCalledWith<ImportReviewApplyPayload[]>({ item_index: 0, action: "ignore" });
  });
});
