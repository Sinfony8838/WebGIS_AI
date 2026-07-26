import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { VisualMapPanel } from "../components/VisualMapPanel";
import { GLOBE_SCENE_PRESETS } from "../lib/globeThemes";

function renderExpanded(props: Partial<ComponentProps<typeof VisualMapPanel>> = {}) {
  const onChangeThemes = vi.fn();
  const onApplyScene = vi.fn();
  const onToggleTextbook = vi.fn();
  const onSwitchViewMode = vi.fn();
  const result = render(
    <VisualMapPanel
      viewMode="globe"
      activeThemeIds={[]}
      onChangeThemes={onChangeThemes}
      onApplyScene={onApplyScene}
      onSwitchViewMode={onSwitchViewMode}
      textbookItems={[]}
      textbookActiveIds={new Set<string>()}
      busy={false}
      onToggleTextbook={onToggleTextbook}
      {...props}
    />
  );
  // The panel defaults to collapsed; expand so tests can exercise its body.
  fireEvent.click(screen.getByTestId("visual-map-panel").querySelector(".visual-map-header")!);
  return { ...result, onChangeThemes, onApplyScene, onToggleTextbook, onSwitchViewMode };
}

describe("VisualMapPanel", () => {
  afterEach(cleanup);

  it("renders scene presets and theme toggles under the merged header", () => {
    renderExpanded();

    expect(screen.getByTestId("visual-map-panel")).toBeTruthy();
    expect(screen.getByText("可视化地图")).toBeTruthy();
    expect(screen.getByTestId("visual-map-scenes")).toBeTruthy();
    expect(screen.getByTestId("globe-scene-hu_density")).toBeTruthy();
    expect(screen.getByTestId("globe-theme-toggle-population_columns")).toBeTruthy();
    // 胡焕庸线既是主题组标题也是图层名，至少存在一处即可。
    expect(screen.getAllByText("胡焕庸线").length).toBeGreaterThanOrEqual(1);
  });

  it("toggles a 3D theme on and off", () => {
    const { onChangeThemes, rerender } = renderExpanded();

    fireEvent.click(screen.getByTestId("globe-theme-toggle-hu_line"));
    expect(onChangeThemes).toHaveBeenCalledWith(["hu_line"]);

    rerender(
      <VisualMapPanel
        viewMode="globe"
        activeThemeIds={["hu_line"]}
        onChangeThemes={onChangeThemes}
        onApplyScene={vi.fn()}
        onSwitchViewMode={vi.fn()}
        textbookItems={[]}
        textbookActiveIds={new Set<string>()}
        busy={false}
        onToggleTextbook={vi.fn()}
      />
    );
    fireEvent.click(screen.getByTestId("globe-theme-toggle-hu_line"));
    expect(onChangeThemes).toHaveBeenLastCalledWith([]);
  });

  it("keeps density fill and density 3d mutually exclusive", () => {
    const { onChangeThemes } = renderExpanded({ activeThemeIds: ["density_fill"] });

    fireEvent.click(screen.getByTestId("globe-theme-toggle-density_3d"));
    expect(onChangeThemes).toHaveBeenCalledWith(["density_3d"]);
  });

  it("applies a scene preset with its camera", () => {
    const { onApplyScene } = renderExpanded();

    fireEvent.click(screen.getByTestId("globe-scene-population_columns"));
    const preset = GLOBE_SCENE_PRESETS.find((item) => item.id === "population_columns");
    expect(onApplyScene).toHaveBeenCalledWith(preset);
  });

  it("shows a legend when an active theme provides one", () => {
    renderExpanded({ activeThemeIds: ["density_fill"] });

    expect(screen.getByTestId("globe-theme-legends")).toBeTruthy();
    expect(screen.getByText("人口密度（2020）")).toBeTruthy();
    expect(screen.getByText("≥800 人/km²")).toBeTruthy();
  });

  it("renders 2D textbook items with a 2D badge under their category topic", () => {
    const { onToggleTextbook } = renderExpanded({
      textbookItems: [
        { id: "china_province_population_density", name: "省级人口密度", category: "人口", category_order: 1 }
      ]
    });

    // 人口 topic group contains the 2D item with a 2D badge.
    const populationTopic = screen.getByTestId("visual-map-topic-人口");
    expect(populationTopic).toBeTruthy();
    expect(populationTopic.querySelector(".visual-map-badge-2d")).toBeTruthy();
    expect(screen.getByText("省级人口密度")).toBeTruthy();

    fireEvent.click(screen.getByText("省级人口密度"));
    expect(onToggleTextbook).toHaveBeenCalledWith("china_province_population_density", true);
  });

  it("marks 3D theme toggles with a 3D badge", () => {
    renderExpanded();

    const huLineToggle = screen.getByTestId("globe-theme-toggle-hu_line");
    expect(huLineToggle.querySelector(".visual-map-badge-3d")).toBeTruthy();
  });

  it("renders an explicit mode switch that reflects the current view mode", () => {
    const { onSwitchViewMode } = renderExpanded({ viewMode: "plane" });

    const globeButton = screen.getByTestId("visual-map-mode-globe");
    const planeButton = screen.getByTestId("visual-map-mode-plane");
    expect(planeButton.getAttribute("aria-pressed")).toBe("true");
    expect(globeButton.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(globeButton);
    expect(onSwitchViewMode).toHaveBeenCalledWith("globe");
  });

  it("marks schematic datasets with a quality badge", () => {
    renderExpanded({
      textbookItems: [
        {
          id: "china_terrain_steps",
          name: "三级阶梯",
          category: "专题",
          category_order: 5,
          status: "schematic",
          source_name: "按省级区划归并"
        }
      ]
    });

    const badge = screen.getByTestId("quality-badge-china_terrain_steps");
    expect(badge.textContent).toBe("示意");
  });

  it("keeps unknown-category datasets visible under the 其他 group", () => {
    renderExpanded({
      textbookItems: [{ id: "mystery_dataset", name: "神秘数据集", category: "其他", category_order: 99 }]
    });

    expect(screen.getByTestId("visual-map-topic-其他")).toBeTruthy();
    expect(screen.getByText("神秘数据集")).toBeTruthy();
  });

  it("shows a loading empty state before the catalog arrives", () => {
    renderExpanded({ textbookItems: [] });
    expect(screen.getByTestId("visual-map-empty")).toBeTruthy();
  });

  it("marks the estimated 3D migration theme with a quality badge", () => {
    renderExpanded();
    const migrationToggle = screen.getByTestId("globe-theme-toggle-migration_flows");
    expect(migrationToggle.querySelector(".visual-map-quality-badge")?.textContent).toBe("估算");
  });
});
