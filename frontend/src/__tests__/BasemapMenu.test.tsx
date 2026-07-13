import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BasemapMenu } from "../components/BasemapMenu";

describe("BasemapMenu", () => {
  it("renders grouped basemap sections and allows selecting nested options", async () => {
    const onSelect = vi.fn();

    render(
      <BasemapMenu
        activeId="amap_vector"
        items={[
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
          },
          {
            id: "weather_precipitation",
            title: "天气 · 降水",
            description: "高德底图叠加 OpenWeather 实时降水网格。",
            type: "stack",
            provider: "openweather",
            layers: []
          }
        ]}
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
});
