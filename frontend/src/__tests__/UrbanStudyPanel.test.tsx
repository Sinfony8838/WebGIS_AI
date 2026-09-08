import { cleanup,fireEvent,render,screen } from "@testing-library/react";
import { afterEach,expect,it,vi } from "vitest";
import { UrbanStudyPanel } from "../components/UrbanStudyPanel";
afterEach(cleanup);
it("keeps unconfigured map visits distinct from real 3D loading and preserves source provenance",()=>{
  const visit=vi.fn(), source=vi.fn();
  render(<UrbanStudyPanel active={false} source={null} status="idle" onVisit={visit} onSource={source} onExit={vi.fn()}/>);
  fireEvent.click(screen.getByText("城市空间与人口"));
  fireEvent.click(screen.getByRole("button",{name:"陆家嘴"}));
  expect(visit.mock.calls[0][0].name).toBe("陆家嘴");
  expect(source).not.toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent("未接入三维数据");
  fireEvent.click(screen.getByText("接入三维数据"));
  fireEvent.change(screen.getByLabelText("3D Tiles 地址"),{target:{value:"https://example.com/shanghai/tileset.json"}});
  fireEvent.change(screen.getByLabelText("数据来源与署名"),{target:{value:"教学模型 · 2026"}});
  fireEvent.change(screen.getByLabelText("数据类型"),{target:{value:"buildings"}});
  fireEvent.click(screen.getByRole("button",{name:"连接数据"}));
  expect(source).toHaveBeenCalledWith({url:"https://example.com/shanghai/tileset.json",credit:"教学模型 · 2026",kind:"buildings"});
});
