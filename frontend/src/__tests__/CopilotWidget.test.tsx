import {afterEach,describe,expect,it,vi} from "vitest";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import type {ComponentProps} from "react";
import {CopilotWidget} from "../components/CopilotWidget";
vi.mock("../speechSynthesis",()=>({cancelSpeech:vi.fn(),speak:vi.fn()}));
vi.mock("../api",()=>({getApiBase:()=>"",fetchAssistantConversations:vi.fn(async()=>({items:[{conversation_id:"c1",title:"北京上海测线",assistant_mode:"operate",updated_at:"now"}]}))}));
vi.mock("../voiceStream",()=>({createVoiceStream:vi.fn()}));
const props=():ComponentProps<typeof CopilotWidget>=>({chatLog:[],currentJob:null,inputValue:"",onInputChange:vi.fn(),onSubmit:vi.fn(),onConfirm:vi.fn(),onVoiceSubmit:vi.fn(),onVoiceNotice:vi.fn(),busy:false,assistantTab:"teaching",onTabChange:vi.fn()});
afterEach(cleanup);
describe("Chat and Operate panel",()=>{
 it("puts new conversation in the mode history sidebar",async()=>{const p=props();p.onNewConversation=vi.fn();p.onSelectConversation=vi.fn(async()=>{});render(<CopilotWidget {...p} projectId="p1" assistantTab="interaction"/>);expect(screen.queryByRole("button",{name:/新建会话/})).not.toBeInTheDocument();fireEvent.click(screen.getByRole("button",{name:"历史会话"}));expect(screen.getByRole("navigation",{name:"Operate 历史会话"})).toBeVisible();fireEvent.click(await screen.findByRole("button",{name:"北京上海测线"}));await waitFor(()=>expect(p.onSelectConversation).toHaveBeenCalledWith("c1"));});
 it("shows elapsed time above summary without usage footer",()=>{const execution={job_id:"job1",status:"completed" as const,usage:{elapsed_ms:1272000,model_calls:2,model_call_limit:3,input_tokens:10,output_tokens:20},activity:{timeline:[{phase:"tool",label:"采样地形",started_ms:0,ended_ms:1000}]}};render(<CopilotWidget {...props()} assistantTab="interaction" chatLog={[{role:"assistant",text:"已完成对比",timestamp:"now",execution}]}/>);expect(screen.getByText("用时 21m 12s")).toBeVisible();expect(screen.queryByText("调用记录")).not.toBeInTheDocument();expect(screen.queryByText(/token/)).not.toBeInTheDocument();fireEvent.click(screen.getByText("用时 21m 12s"));expect(screen.getByText("采样地形")).toBeVisible();});
 it("has two explicit modes and a mic in Chat",()=>{render(<CopilotWidget {...props()}/>);expect(screen.getByRole("tab",{name:"Chat"})).toHaveAttribute("aria-selected","true");expect(screen.getByRole("tab",{name:"Operate"})).toBeVisible();expect(screen.getByRole("button",{name:"开始语音输入"})).toBeVisible();expect(screen.queryByText("进入时自动聆听")).not.toBeInTheDocument();});
 it("keeps the same mic in Operate while hiding attachments",()=>{render(<CopilotWidget {...props()} assistantTab="interaction"/>);expect(screen.getByRole("button",{name:"开始语音输入"})).toBeVisible();expect(screen.queryByRole("button",{name:"添加图片"})).not.toBeInTheDocument();});
 it("awaits mode-switch barrier instead of changing selected mode itself",async()=>{const p=props();let resolve!:()=>void;p.onTabChange=vi.fn(()=>new Promise<void>(r=>{resolve=r;}));render(<CopilotWidget {...p}/>);fireEvent.click(screen.getByRole("tab",{name:"Operate"}));expect(screen.getByRole("tab",{name:"Chat"})).toHaveAttribute("aria-selected","true");expect(screen.getByRole("tab",{name:"Operate"})).toBeDisabled();resolve();await waitFor(()=>expect(screen.getByRole("tab",{name:"Operate"})).not.toBeDisabled());});
 it("only switches modes in the header and uses the mascot",()=>{render(<CopilotWidget {...props()} chatLog={[{role:"user",text:"放大地图",timestamp:"now"}]}/>);expect(screen.queryByText("GeoBot")).not.toBeInTheDocument();expect(screen.getByRole("img",{name:"智能助教吉祥物"})).toBeVisible();expect(screen.queryByRole("button",{name:/转到/})).not.toBeInTheDocument();});
 it("expands without leaving the map",()=>{render(<CopilotWidget {...props()}/>);fireEvent.click(screen.getByRole("button",{name:"展开面板"}));expect(screen.getByLabelText("智能助教")).toHaveClass("is-expanded");});
 it("provides an accessible continuous-call action",()=>{render(<CopilotWidget {...props()} voiceStreamAvailable/>);fireEvent.click(screen.getByRole("button",{name:"语音选项"}));expect(screen.getByRole("button",{name:"开始长时通话"})).toBeEnabled();});
 it("shows actual generated image rather than speculative output",()=>{render(<CopilotWidget {...props()} chatLog={[{role:"assistant",text:"已生成",timestamp:"now",actions_executed:[{action:{tool_name:"generate_image",tool_params:{}},result:{generated_artifact:{title:"示意图",metadata:{public_url:"/files/image.png"}}}}]}]}/>);expect(screen.getByRole("img",{name:"示意图"})).toHaveAttribute("src","http://localhost:3000/files/image.png");});
 it("renders source URLs safely",()=>{render(<CopilotWidget {...props()} chatLog={[{role:"assistant",text:"**知识回答**",timestamp:"now",citations:[{title:"不可信链接",url:"javascript:alert(1)"}]}]}/>);expect(screen.queryByRole("link")).not.toBeInTheDocument();expect(screen.getByText("知识回答")).toBeInTheDocument();});
});

function confirmationJob(): NonNullable<ComponentProps<typeof CopilotWidget>["currentJob"]> {
 return {job_id:"pending",project_id:"p",job_type:"assistant",title:"删除图层",workflow_type:"assistant",status:"completed",updated_at:"now",steps:[],stages:{},
  result:{requires_confirmation:true,confirmation_id:"confirm-1",assistant_message:"将删除 2 个图层：人口密度、地形。新增图层不在本次范围内。"}};
}
describe("confirmation controls",()=>{
 it("shows frozen targets and blocks duplicate clicks during submission",async()=>{
  const p=props();let finish!:()=>void;p.onConfirm=vi.fn(()=>new Promise<void>(resolve=>{finish=resolve;}));
  render(<CopilotWidget {...p} currentJob={confirmationJob()}/>);
  expect(screen.getByText(/将删除 2 个图层/)).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"确认",exact:true}));
  fireEvent.click(screen.getByRole("button",{name:"正在提交确认"}));
  expect(p.onConfirm).toHaveBeenCalledTimes(1);expect(p.onConfirm).toHaveBeenCalledWith("confirm-1","approve");
  expect(screen.getByRole("button",{name:"取消",exact:true})).toBeDisabled();
  finish();await waitFor(()=>expect(screen.getByRole("button",{name:"确认",exact:true})).toBeEnabled());
 });
 it("reports API rejection and leaves a usable confirmation",async()=>{
  const p=props();p.onConfirm=vi.fn(async()=>{throw new Error("确认已过期");});
  render(<CopilotWidget {...p} currentJob={confirmationJob()}/>);fireEvent.click(screen.getByRole("button",{name:"确认",exact:true}));
  await waitFor(()=>expect(p.onVoiceNotice).toHaveBeenCalledWith("error","确认操作失败","确认已过期"));
  expect(screen.getByRole("button",{name:"确认",exact:true})).toBeEnabled();
 });
 it("disables approval and rejection while the accepted job runs",()=>{
  render(<CopilotWidget {...props()} busy currentJob={confirmationJob()}/>);
  expect(screen.getByRole("button",{name:"确认",exact:true})).toBeDisabled();
  expect(screen.getByRole("button",{name:"取消",exact:true})).toBeDisabled();
 });
});
