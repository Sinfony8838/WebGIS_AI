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
  useWorkflowStream: vi.fn(() => ({
    workflowId: "",
    status: "idle",
    intent: "",
    steps: [],
    artifacts: [],
    error: null,
    lastEvent: null
  }))
}));

import { WorkflowDock } from "../components/WorkflowDock";
import { useWorkflowStream } from "../hooks/useWorkflowStream";

describe("WorkflowDock", () => {
  afterEach(cleanup);

  it("subscribes to an assistant-submitted workflow without submitting again", async () => {
    const { rerender } = render(<WorkflowDock projectId="project_demo" mapRef={createRef<Map>()} />);
    rerender(<WorkflowDock projectId="project_demo" mapRef={createRef<Map>()} assistantJob={{
      job_id: "assistant_job", project_id: "project_demo", status: "completed",
      result: { actions_executed: [{ action: { tool_name: "run_workflow", tool_params: {} }, result: { workflow: { workflow_id: "wf_assistant" } } }] }
    } as never} />);
    await waitFor(() => expect(useWorkflowStream).toHaveBeenLastCalledWith("wf_assistant"));
  });

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

  it("renders a cancelled workflow as 已取消 instead of a failure", () => {
    vi.mocked(useWorkflowStream).mockReturnValue({
      workflowId: "wf_cancelled",
      status: "cancelled",
      intent: "胡焕庸线对比分析",
      steps: [
        { id: "s1", op: "load_layer", status: "success", outputs: {}, error: null, started_at: "", finished_at: "" },
        {
          id: "s4", op: "choropleth", status: "error", outputs: {}, started_at: "", finished_at: "",
          error: { code: "STEP_CANCELLED", message: "cancelled", user_friendly: "已取消本次分析，未保存结果图层。可以调整参数后重新提交。" }
        }
      ],
      artifacts: [],
      error: { code: "STEP_CANCELLED", message: "cancelled", user_friendly: "已取消本次分析，未保存结果图层。可以调整参数后重新提交。" },
      lastEvent: null
    });
    render(<WorkflowDock projectId="project_demo" mapRef={createRef<Map>()} />);

    expect(screen.getByTestId("workflow-panel")).toHaveTextContent("已取消");
    expect(screen.getByTestId("workflow-panel")).toHaveTextContent("[STEP_CANCELLED]");
    expect(screen.getByTestId("workflow-panel")).toHaveTextContent("已取消本次分析，未保存结果图层。可以调整参数后重新提交。");
    // A cancel is not a failure: the ❌ 失败 label must not appear.
    expect(screen.getByTestId("workflow-panel")).not.toHaveTextContent("失败");
  });

  it("surfaces a preflight rejection as a toast while keeping the form filled", async () => {
    const { submitWorkflow } = await import("../api");
    vi.mocked(submitWorkflow).mockResolvedValue({
      status: "error",
      workflow_id: "wf_preflight",
      workflow_status: "error",
      intent: "制作人口密度分级设色图",
      template_id: "population_choropleth",
      parameters: { dataset: "builtin:one_map/population/does_not_exist.geojson" },
      error: {
        code: "VALIDATION_FAILED",
        message: "workflow preflight failed",
        user_friendly: "找不到数据集 builtin:one_map/population/does_not_exist.geojson（步骤 s1）。请确认数据已上传，或在数据集下拉里重新选择。",
        details: {}
      }
    } as never);
    const onToast = vi.fn();
    render(
      <WorkflowDock
        projectId="project_demo"
        mapRef={createRef<Map>()}
        open
        onToast={onToast}
      />
    );

    fireEvent.change(screen.getByDisplayValue(""), { target: { value: "制作人口密度图" } });
    fireEvent.click(screen.getByRole("button", { name: "提交工作流" }));

    await waitFor(() => {
      expect(onToast).toHaveBeenCalledWith(
        "error",
        "找不到数据集 builtin:one_map/population/does_not_exist.geojson（步骤 s1）。请确认数据已上传，或在数据集下拉里重新选择。"
      );
    });
    // 保留已填参数：输入框内容在预检失败后不丢失，教师可直接修正后重跑。
    expect(screen.getByDisplayValue("制作人口密度图")).toBeTruthy();
  });
});
