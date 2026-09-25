import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MapProfilePanel } from "../components/MapProfilePanel";
import { previewMapProfile } from "../api";

vi.mock("../api", () => ({ previewMapProfile: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("MapProfilePanel", () => {
  it("submits measured coordinates, shows source and numeric profile", async () => {
    vi.mocked(previewMapProfile).mockResolvedValue({
      kind: "population", source_id: "gpw_2020", source_name: "NASA GPW", source_year: "2020", unit: "人/km²",
      sampling: "原始栅格", resolution_m: 1000, total_distance_km: 2, sample_spacing_m: 1000, no_data_count: 1,
      samples: [{ distance_km: 0, lon: 121, lat: 31, value: 120 }, { distance_km: 1, lon: 121.01, lat: 31, value: null }, { distance_km: 2, lon: 121.02, lat: 31, value: 240 }]
    });
    render(<MapProfilePanel projectId="project_test" coordinates={[[121, 31], [121.02, 31]]}
      densitySources={[{ id: "gpw_2020", name: "全球 GPW" }]} onHover={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "人口密度变化" }));
    await waitFor(() => expect(screen.getByRole("img", { name: "人口密度沿线剖面图" })).toBeInTheDocument());
    expect(previewMapProfile).toHaveBeenCalledWith("project_test", {
      coordinates: [[121, 31], [121.02, 31]], kind: "population", source_id: "gpw_2020"
    });
    expect(screen.getByText(/无数据 1 点/)).toBeInTheDocument();
  });
  it("reports external-service failures without plotting fake values", async () => {
    vi.mocked(previewMapProfile).mockRejectedValue(new Error("公开数据服务暂时不可用"));
    render(<MapProfilePanel projectId="project_test" coordinates={[[121, 31], [121.02, 31]]}
      densitySources={[]} onHover={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "地形剖面" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("公开数据服务暂时不可用"));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
