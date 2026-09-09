import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MapEvidenceLegend } from "../components/MapEvidenceLegend";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const props = { basemapId: "nasa_nightlights_2016", layers: [], globe: false, themeIds: [], showFit: false, onShowFit: vi.fn() };
describe("MapEvidenceLegend", () => {
  it("lets a narrow classroom open and close readable source details", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));
    render(<MapEvidenceLegend {...props} />);
    const toggle = screen.getByRole("button", { name: "图例与数据" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: /NASA Black Marble/ })).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: /NASA Black Marble/ })).toBeVisible();
    fireEvent.click(toggle);
    expect(screen.queryByRole("link", { name: /NASA Black Marble/ })).not.toBeInTheDocument();
  });
  it("keeps the desktop legend expanded and hides it when no thematic layer is visible", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
    const { rerender } = render(<MapEvidenceLegend {...props} />);
    expect(screen.getByRole("button", { name: "图例与数据" })).toHaveAttribute("aria-expanded", "true");
    rerender(<MapEvidenceLegend {...props} basemapId="amap_light" />);
    expect(screen.queryByRole("button", { name: "图例与数据" })).not.toBeInTheDocument();
  });
});
