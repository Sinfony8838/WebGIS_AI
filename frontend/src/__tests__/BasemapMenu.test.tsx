import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BasemapMenu } from "../components/BasemapMenu";

afterEach(cleanup);

const basicItems = [
  {
    id: "amap_vector",
    title: "高德标准",
    description: "适合课堂整体讲解的标准中文底图。",
    type: "stack",
    provider: "amap",
    layers: []
  },
  {
    id: "amap_imagery",
    title: "高德影像",
    description: "适合展示地貌、海岸与城市分布的影像底图。",
    type: "stack",
    provider: "amap",
    layers: []
  }
];

const weatherItems = [
  {
    id: "weather_precipitation",
    title: "天气 · 降水",
    description: "高德底图叠加 OpenWeather 实时降水网格。",
    type: "stack",
    provider: "openweather",
    layers: []
  }
];

describe("BasemapMenu", () => {
  it("renders grouped basemap sections and allows selecting nested options", async () => {
    const onSelect = vi.fn();

    render(
      <BasemapMenu
        activeId="amap_vector"
        items={[...basicItems, ...weatherItems]}
        onSelect={onSelect}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "底图 · 高德标准" }));

    expect(screen.getByRole("menu", { name: "底图选择" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /基础底图/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /天气底图/ })).toBeInTheDocument();
    expect(screen.queryByRole("menuitemradio", { name: /高德影像/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /基础底图/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /高德影像/ }));

    expect(onSelect).toHaveBeenCalledWith("amap_imagery");
  });

  it("keeps the current basemap and explains how to configure when weather is not enabled", async () => {
    const onSelect = vi.fn();
    const onWeatherBlocked = vi.fn();

    render(
      <BasemapMenu
        activeId="amap_vector"
        items={[...basicItems, ...weatherItems]}
        weatherEnabled={false}
        onWeatherBlocked={onWeatherBlocked}
        onSelect={onSelect}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "底图 · 高德标准" }));
    fireEvent.click(screen.getByRole("button", { name: /天气底图/ }));

    // 天气分组与选项都带有「未配置」徽标
    const weatherOption = screen.getByRole("menuitemradio", { name: /天气 · 降水/ });
    expect(weatherOption).toHaveAttribute("aria-disabled", "true");

    fireEvent.click(weatherOption);

    // 不切换底图，仅给出可操作提示（菜单内提示 + 宿主回调）
    expect(onSelect).not.toHaveBeenCalled();
    expect(onWeatherBlocked).toHaveBeenCalledWith(
      "天气 · 降水",
      expect.stringContaining("WEBGIS_AI_OPENWEATHERMAP_API_KEY")
    );
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/天气底图未配置/);
    });
    // 底图菜单保持打开，当前底图仍是高德标准
    expect(screen.getByRole("menu", { name: "底图选择" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "底图 · 高德标准" })).toBeInTheDocument();
  });

  it("marks the weather group with an unconfigured badge", () => {
    render(
      <BasemapMenu
        activeId="amap_vector"
        items={[...basicItems, ...weatherItems]}
        weatherEnabled={false}
        onSelect={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "底图 · 高德标准" }));

    const groupToggle = screen.getByRole("button", { name: /天气底图/ });
    expect(groupToggle).toHaveTextContent("未配置");
  });
});
