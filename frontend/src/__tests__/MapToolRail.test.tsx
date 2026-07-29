import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MapToolRail } from "../components/MapToolRail";

function renderRail(viewMode: "plane" | "globe") {
  return render(
    <MapToolRail
      mode="browse"
      viewMode={viewMode}
      hasSearchArea={false}
      hasMeasurements={false}
      hasAnnotations={false}
      busy={false}
      showGraticule={false}
      onChangeMode={vi.fn()}
      onChangeViewMode={vi.fn()}
      onZoomIn={vi.fn()}
      onZoomOut={vi.fn()}
      onClear={vi.fn()}
      onToggleGraticule={vi.fn()}
      onResetView={vi.fn()}
    />
  );
}

describe("MapToolRail", () => {
  afterEach(cleanup);

  it("renders the plane tools in a single ordered column", () => {
    renderRail("plane");

    const group = screen.getByRole("group", { name: "交互模式" });
    expect(group).toHaveAttribute("data-layout", "single-column");

    const labels = Array.from(group.querySelectorAll(".tool-rail-label")).map(
      (item) => item.textContent
    );
    expect(labels).toEqual(["选择", "标注", "测距", "绘区", "画笔", "经纬网", "重置视角"]);
  });

  it("keeps unsupported drawing tools out of the globe rail", () => {
    renderRail("globe");

    const group = screen.getByRole("group", { name: "交互模式" });
    const labels = Array.from(group.querySelectorAll(".tool-rail-label")).map(
      (item) => item.textContent
    );
    expect(labels).toEqual(["选择", "经纬网", "重置视角"]);
    expect(
      screen.getByRole("button", { name: "切换到 2D 平面地图" })
    ).toBeInTheDocument();
  });
});
