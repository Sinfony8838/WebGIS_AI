import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WeatherOverlayStatus } from "../components/WeatherOverlayStatus";

afterEach(cleanup);

describe("WeatherOverlayStatus", () => {
  it("shows loading state while overlay tiles are in flight", () => {
    render(
      <WeatherOverlayStatus basemapId="weather_precipitation" title="天气 · 降水" phase="loading" />
    );

    const chip = screen.getByRole("status");
    expect(chip).toHaveTextContent("加载中");
    expect(screen.getByText(/OpenWeatherMap 实时栅格/)).toBeInTheDocument();
  });

  it("shows the ready state after real tiles load", () => {
    render(
      <WeatherOverlayStatus basemapId="weather_precipitation" title="天气 · 降水" phase="ready" />
    );

    expect(screen.getByRole("status")).toHaveTextContent("实时瓦片已加载");
    // 图例展示降水色带说明，不伪造数值断点
    expect(screen.getByText(/降水强度/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /OpenWeatherMap 官方图例/ })).toBeInTheDocument();
  });

  it("explains failure, keeps the reference basemap note, and offers restore", () => {
    const onRestore = vi.fn();
    render(
      <WeatherOverlayStatus
        basemapId="weather_precipitation"
        title="天气 · 降水"
        phase="error"
        onRestoreBasemap={onRestore}
      />
    );

    expect(screen.getByRole("status")).toHaveTextContent("加载失败");
    expect(screen.getByText(/未能加载/)).toHaveTextContent(/WEBGIS_AI_OPENWEATHERMAP_API_KEY/);
    expect(screen.getByText(/高德参考底图不受影响/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "恢复高德标准底图" }));
    expect(onRestore).toHaveBeenCalledTimes(1);
  });

  it("hides the restore button when no handler is provided", () => {
    render(
      <WeatherOverlayStatus basemapId="weather_precipitation" title="天气 · 降水" phase="error" />
    );

    expect(screen.queryByRole("button", { name: "恢复高德标准底图" })).not.toBeInTheDocument();
  });
});
