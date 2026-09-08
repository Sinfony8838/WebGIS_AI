import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { MapToolsDock } from "../components/MapToolsDock";
afterEach(cleanup);
function Tools() { const [selected, setSelected] = useState(false); return <button aria-pressed={selected} onClick={() => setSelected(!selected)}>人口密度</button>; }
it("collapses both panels and preserves selection when reopened", () => {
  render(<MapToolsDock><button>地图测距</button><Tools /></MapToolsDock>);
  fireEvent.click(screen.getByRole("button", { name: "人口密度" }));
  fireEvent.click(screen.getByRole("button", { name: "收起地图工具与可视化地图" }));
  expect(screen.queryByRole("button", { name: "地图测距" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "人口密度" })).not.toBeInTheDocument();
  const toggle = screen.getByRole("button", { name: "展开地图工具与可视化地图" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(toggle);
  expect(screen.getByRole("button", { name: "地图测距" })).toBeVisible();
  expect(screen.getByRole("button", { name: "人口密度" })).toHaveAttribute("aria-pressed", "true");
});
