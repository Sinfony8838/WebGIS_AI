import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GlobeThemePanel } from "../components/GlobeThemePanel";
import { GLOBE_SCENE_PRESETS } from "../lib/globeThemes";

function renderExpanded(props: ComponentProps<typeof GlobeThemePanel>) {
  const result = render(<GlobeThemePanel {...props} />);
  // The panel defaults to collapsed; expand so tests can exercise its body.
  fireEvent.click(screen.getByLabelText("展开三维专题面板"));
  return result;
}

describe("GlobeThemePanel", () => {
  afterEach(cleanup);

  it("renders scene presets and theme toggles", () => {
    renderExpanded({
      activeThemeIds: [],
      onChangeThemes: vi.fn(),
      onApplyScene: vi.fn()
    });

    expect(screen.getByTestId("globe-theme-panel")).toBeTruthy();
    expect(screen.getByTestId("globe-scene-hu_density")).toBeTruthy();
    expect(screen.getByTestId("globe-theme-toggle-population_columns")).toBeTruthy();
    expect(screen.getByText("胡焕庸线")).toBeTruthy();
  });

  it("toggles a theme on and off", () => {
    const onChangeThemes = vi.fn();
    const { rerender } = renderExpanded({
      activeThemeIds: [],
      onChangeThemes,
      onApplyScene: vi.fn()
    });

    fireEvent.click(screen.getByTestId("globe-theme-toggle-hu_line"));
    expect(onChangeThemes).toHaveBeenCalledWith(["hu_line"]);

    rerender(
      <GlobeThemePanel
        activeThemeIds={["hu_line"]}
        onChangeThemes={onChangeThemes}
        onApplyScene={vi.fn()}
      />
    );
    fireEvent.click(screen.getByTestId("globe-theme-toggle-hu_line"));
    expect(onChangeThemes).toHaveBeenLastCalledWith([]);
  });

  it("keeps density fill and density 3d mutually exclusive", () => {
    const onChangeThemes = vi.fn();
    renderExpanded({
      activeThemeIds: ["density_fill"],
      onChangeThemes,
      onApplyScene: vi.fn()
    });

    fireEvent.click(screen.getByTestId("globe-theme-toggle-density_3d"));
    expect(onChangeThemes).toHaveBeenCalledWith(["density_3d"]);
  });

  it("applies a scene preset with its camera", () => {
    const onApplyScene = vi.fn();
    renderExpanded({
      activeThemeIds: [],
      onChangeThemes: vi.fn(),
      onApplyScene
    });

    fireEvent.click(screen.getByTestId("globe-scene-population_columns"));
    const preset = GLOBE_SCENE_PRESETS.find((item) => item.id === "population_columns");
    expect(onApplyScene).toHaveBeenCalledWith(preset);
  });

  it("shows a legend when an active theme provides one", () => {
    renderExpanded({
      activeThemeIds: ["density_fill"],
      onChangeThemes: vi.fn(),
      onApplyScene: vi.fn()
    });

    expect(screen.getByTestId("globe-theme-legends")).toBeTruthy();
    expect(screen.getByText("人口密度（2020）")).toBeTruthy();
    expect(screen.getByText("≥800 人/km²")).toBeTruthy();
  });
});
