import {render,screen,fireEvent,waitFor,cleanup} from "@testing-library/react";
import {it,expect,vi,afterEach} from "vitest";
import {AssistantImage} from "../components/AssistantImage";
import {saveAssistantImage} from "../api";
vi.mock("../api",()=>({getApiBase:()=>"http://127.0.0.1:8017",saveAssistantImage:vi.fn(async()=>({artifact:{}}))}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const artifact={artifact_id:"a1",artifact_type:"assistant_image_preview",title:"地理示意图",metadata:{public_url:"/files/image.png",saved_to_library:false}};
it("renders server image directly without automatically saving",()=>{render(<AssistantImage artifact={artifact}/>);expect(screen.getByRole("img")).toHaveAttribute("src","http://127.0.0.1:8017/files/image.png");expect(saveAssistantImage).not.toHaveBeenCalled();fireEvent.click(screen.getByRole("button",{name:"暂不保存"}));expect(screen.getByText("仅保留在会话中")).toBeVisible();expect(saveAssistantImage).not.toHaveBeenCalled();});
it("only confirms saving after server success",async()=>{render(<AssistantImage artifact={artifact}/>);fireEvent.click(screen.getByRole("button",{name:"保存到素材库"}));await waitFor(()=>expect(screen.getByText("已保存到素材库")).toBeVisible());expect(saveAssistantImage).toHaveBeenCalledWith("a1");});
it("does not label a failed save successful",async()=>{vi.mocked(saveAssistantImage).mockRejectedValueOnce(new Error("offline"));render(<AssistantImage artifact={artifact}/>);fireEvent.click(screen.getByRole("button",{name:"保存到素材库"}));await screen.findByRole("alert");expect(screen.queryByText("已保存到素材库")).not.toBeInTheDocument();expect(screen.getByRole("img")).toBeVisible();});

it.each(["fail","unknown"])("keeps %s geography review visible and blocks library save",status=>{
  render(<AssistantImage artifact={{...artifact,metadata:{...artifact.metadata,geography_review:{status,summary:"箭头方向不能确认"}}}}/>);
  expect(screen.getByRole("img")).toBeVisible();
  const save=screen.getByRole("button",{name:"保存到素材库"});expect(save).toBeDisabled();fireEvent.click(save);expect(saveAssistantImage).not.toHaveBeenCalled();
});
it("shows actual checks and identifies reference redraw",()=>{
  render(<AssistantImage artifact={{...artifact,metadata:{...artifact.metadata,geography_review:{status:"pass",summary:"未发现明显错误",checks:[{requirement:"径流向下",status:"pass",evidence:"箭头指向河谷"}]},geography_brief:{generation_method:"reference_redraw"}}}}/>);
  fireEvent.click(screen.getByText("地理自动检查完成 · 仍需教师审阅"));expect(screen.getByText(/未在原图上编辑/)).toBeInTheDocument();expect(screen.getByText(/箭头指向河谷/)).toBeInTheDocument();
});
