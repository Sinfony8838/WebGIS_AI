import { createRef } from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type Map from "ol/Map";

vi.mock("../api", () => ({
  buildWorkflowFileUrl: (path: string) => path,
  fetchDatasetCatalog: vi.fn().mockResolvedValue({ items: [] }),
  listWorkflowTemplates: vi.fn().mockResolvedValue({
    items: [
      { id: "population_choropleth", title: "人口密度分级设色图" },
      { id: "buffer_facilities", title: "设施缓冲区分析" }
    ]
  }),
  submitWorkflow: vi.fn()
}));

vi.mock("../hooks/useWorkflowStream", () => ({
  useWorkflowStream: () => ({
    workflowId: "",
    status: "idle",
    intent: "",
    steps: [],
    artifacts: [],
    error: null,
    lastEvent: null
  })
}));

import { WorkflowDock } from "../components/WorkflowDock";

describe("WorkflowDock", () => {
  afterEach(cleanup);

  it("opens in-panel dropdown menus instead of native selects", async () => {
    render(
      <WorkflowDock
        projectId="project_demo"
        mapRef={createRef<Map>()}
        open
      />
    );

    // 折叠态：按钮显示占位文案
    const templateButton = screen.getByTestId("workflow-template-select");
    expect(templateButton.tagName).toBe("BUTTON");
    expect(templateButton).toHaveTextContent("自动识别");

    // 展开后模板选项在面板内列表中（原生 select 弹层会飞出窗口）
    fireEvent.click(templateButton);
    const list = screen.getByTestId("workflow-template-select-list");
    expect(within(list).getByRole("option", { name: "自动识别" })).toBeTruthy();

    await waitFor(() => {
      expect(within(list).getByRole("option", { name: "人口密度分级设色图" })).toBeTruthy();
    });

    // 选择模板：回调收起列表，按钮显示所选模板
    fireEvent.click(within(list).getByRole("option", { name: "人口密度分级设色图" }));
    expect(screen.queryByTestId("workflow-template-select-list")).toBeNull();
    expect(screen.getByTestId("workflow-template-select")).toHaveTextContent("人口密度分级设色图");

    // 数据集下拉同样可用
    fireEvent.click(screen.getByTestId("workflow-primary-dataset-select"));
    expect(screen.getByTestId("workflow-primary-dataset-select-list")).toBeTruthy();
  });
});
