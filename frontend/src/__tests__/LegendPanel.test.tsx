import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LegendPanel } from "../components/LegendPanel";
import type { GraduatedStyle } from "../types";

const STYLE: GraduatedStyle = {
  type: "graduated",
  field: "density",
  classes: [],
  legend: {
    title: "人口密度",
    items: [
      { label: "低", color: "#eff3ff" },
      { label: "中", color: "#6baed6" },
      { label: "高", color: "#08519c" }
    ]
  }
};

describe("LegendPanel", () => {
  afterEach(cleanup);

  it("renders every item fully revealed by default", () => {
    const { container } = render(<LegendPanel style={STYLE} />);
    expect(screen.getByTestId("legend-panel")).toBeTruthy();
    expect(container.querySelectorAll(".legend-panel__item")).toHaveLength(3);
    expect(container.querySelectorAll(".legend-panel__item--pending")).toHaveLength(0);
  });

  it("dims items the replay has not revealed yet", () => {
    const { container } = render(<LegendPanel style={STYLE} revealedItems={1} />);
    const items = container.querySelectorAll(".legend-panel__item");
    expect(items[0].className).not.toContain("legend-panel__item--pending");
    expect(items[1].className).toContain("legend-panel__item--pending");
    expect(items[2].className).toContain("legend-panel__item--pending");
  });
});
