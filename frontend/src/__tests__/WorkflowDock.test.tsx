import { createRef } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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

  it("marks every native selector for the dark readable option palette", async () => {
    render(
      <WorkflowDock
        projectId="project_demo"
        mapRef={createRef<Map>()}
        open
      />
    );

    const templateSelect = screen.getByTestId("workflow-template-select");
    const datasetSelect = screen.getByTestId("workflow-primary-dataset-select");
    expect(templateSelect).toHaveClass("workflow-dock__select");
    expect(datasetSelect).toHaveClass("workflow-dock__select");
    expect(screen.getByRole("option", { name: "自动识别" })).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByRole("option", { name: "人口密度分级设色图" })
      ).toBeInTheDocument();
    });
  });
});
