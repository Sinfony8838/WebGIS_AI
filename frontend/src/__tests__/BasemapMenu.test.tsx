import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BasemapMenu } from "../components/BasemapMenu";

describe("BasemapMenu", () => {
  it("renders a single trigger and allows switching basemaps", async () => {
    const onSelect = vi.fn();

    render(
      <BasemapMenu
        activeId="amap_vector"
        items={[
          {
            id: "amap_vector",
            title: "高德标准",
            description: "标准中文底图。",
            type: "stack",
            provider: "amap",
            layers: []
          },
          {
            id: "amap_imagery",
            title: "高德影像",
            description: "影像底图。",
            type: "stack",
            provider: "amap",
            layers: []
          }
        ]}
        onSelect={onSelect}
      />
    );

    expect(screen.getByRole("button", { name: "底图 · 高德标准" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "底图 · 高德标准" }));
    expect(screen.getByRole("menu", { name: "底图选择" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitemradio", { name: /高德影像/ }));
    expect(onSelect).toHaveBeenCalledWith("amap_imagery");
  });
});
