import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {AssistantHistory} from "../components/AssistantHistory";
import * as api from "../api";
const state=vi.hoisted(()=>({items:[] as any[],folders:[] as any[]}));
vi.mock("../api",()=>({
 fetchAssistantConversations:vi.fn(async(_p,_m,deleted=false)=>JSON.parse(JSON.stringify({items:state.items.filter(i=>Boolean(i.deleted)===deleted),folders:state.folders}))),
 updateAssistantConversation:vi.fn(async(id,patch)=>{Object.assign(state.items.find(i=>i.conversation_id===id),patch);}),
 createAssistantFolder:vi.fn(async(_p,name)=>{state.folders.push({folder_id:"f1",name,pinned:false});}),
 updateAssistantFolder:vi.fn(async(_p,id,patch)=>{Object.assign(state.folders.find(f=>f.folder_id===id),patch);}),
 removeAssistantFolder:vi.fn(async()=>{})
}));
const props=()=>({projectId:"p1",mode:"operate" as const,conversationId:"c1",messageCount:2,busy:false,onNavigate:vi.fn(async()=>true)});
beforeEach(()=>{vi.clearAllMocks();state.items=[{conversation_id:"c1",title:"Test conversation",pinned:false,folder_id:""}];state.folders=[];});
afterEach(cleanup);
describe("assistant history management",()=>{
 it("creates a folder, moves and pins a conversation, permanently deletes it without a trash entry",async()=>{
  const p=props();render(<AssistantHistory {...p}/>);
  await screen.findByRole("button",{name:"Test conversation",exact:true});
  fireEvent.click(screen.getByRole("button",{name:"＋ 新建项目"}));
  fireEvent.change(screen.getByLabelText("项目文件夹名称"),{target:{value:"Geography"}});
  fireEvent.click(screen.getByRole("button",{name:"保存"}));
  await screen.findByRole("button",{name:"管理项目 Geography"});
  fireEvent.click(screen.getByRole("button",{name:"管理项目 Geography"}));
  fireEvent.click(screen.getByRole("button",{name:"置顶项目"}));
  await waitFor(()=>expect(api.updateAssistantFolder).toHaveBeenCalledWith("p1","f1",{pinned:true}));
  await screen.findByRole("button",{name:"管理会话 Test conversation"});
  fireEvent.click(screen.getByRole("button",{name:"管理会话 Test conversation"}));
  fireEvent.change(screen.getByLabelText("移动会话 Test conversation"),{target:{value:"f1"}});
  await waitFor(()=>expect(api.updateAssistantConversation).toHaveBeenCalledWith("c1",{folder_id:"f1"}));
  await screen.findByRole("button",{name:"管理会话 Test conversation"});
  fireEvent.click(screen.getByRole("button",{name:"管理会话 Test conversation"}));
  fireEvent.click(screen.getByRole("button",{name:"置顶会话"}));
  await screen.findByRole("region",{name:"置顶会话"});
  fireEvent.click(screen.getByRole("button",{name:"管理会话 Test conversation"}));
  fireEvent.click(screen.getByRole("button",{name:"删除会话"}));
  await waitFor(()=>expect(api.updateAssistantConversation).toHaveBeenCalledWith("c1",{deleted:true}));
  expect(p.onNavigate).toHaveBeenCalledWith(undefined,true);
  await waitFor(()=>expect(screen.queryByRole("button",{name:"Test conversation",exact:true})).not.toBeInTheDocument());
  expect(screen.queryByRole("button",{name:"已删除",exact:true})).not.toBeInTheDocument();
  expect(screen.queryByText("恢复 Test conversation")).not.toBeInTheDocument();
 });
 it("does not delete when the active task could not be left",async()=>{
  render(<AssistantHistory {...props()} onNavigate={vi.fn(async()=>false)}/>);
  fireEvent.click(await screen.findByRole("button",{name:"管理会话 Test conversation"}));
  fireEvent.click(screen.getByRole("button",{name:"删除会话"}));
  await screen.findByRole("status");
  expect(api.updateAssistantConversation).not.toHaveBeenCalled();
 });
});
