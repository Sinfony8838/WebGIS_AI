import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatsPanel } from "../components/StatsPanel";
import { WorkflowParameters } from "../components/WorkflowParameters";
import type { WorkflowPreview } from "../types";

const preview: WorkflowPreview = {
  valid: true, template_id: "classify_field",
  parameters: {field: "mag", classes: 3, method: "equal", output_field: "mag_class"},
  parameter_sources: {field: "message", classes: "message", method: "message", output_field: "message"},
  fields: [{name: "mag", numeric: true, numeric_count: 35, non_null_count: 35},
           {name: "place", numeric: false, numeric_count: 0, non_null_count: 35}],
  issues: []
};

afterEach(cleanup);

describe("GIS parameter and statistical truth", () => {
  it("shows the actual parsed parameters, numeric choices and manual edits", () => {
    const changed = vi.fn();
    render(<WorkflowParameters preview={preview} busy={false} onChange={changed} onReset={vi.fn()} />);
    expect(screen.getByLabelText("分级字段")).toHaveValue("mag");
    expect(screen.getByLabelText("分级数")).toHaveValue(3);
    expect(screen.getByLabelText("分级方法")).toHaveValue("equal");
    expect(screen.queryByRole("option", {name: "place"})).toBeNull();
    fireEvent.change(screen.getByLabelText("分级数"), {target: {value: "4"}});
    expect(changed).toHaveBeenCalledWith("classes", "4");
  });

  it("distinguishes a 20-row sample from the 35-row population", () => {
    render(<StatsPanel stats={{all_rows_count:35, summary:{count:35}, fields:["mag"], rows:Array.from({length:20},()=>({mag:5}))}} />);
    expect(screen.getByText("共 35 条，展示前 20 条")).toBeTruthy();
  });
});
