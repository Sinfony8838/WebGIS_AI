import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {TeacherLessonActions} from "../components/TeacherLessonActions";
import type {ClassSessionRecord,LessonRecord,LessonStage} from "../types";
const mocks=vi.hoisted(()=>({apply:vi.fn(),start:vi.fn(),job:vi.fn(),log:vi.fn(),workflow:vi.fn(),result:vi.fn(),cancel:vi.fn(),resources:vi.fn()}));
vi.mock("../api",()=>({applyTeacherLessonAction:mocks.apply,startPopulationZoneSummary:mocks.start,fetchJob:mocks.job,logSessionEvent:mocks.log,
  fetchWorkflow:mocks.workflow,applyTeacherWorkflowResult:mocks.result,cancelTeacherWorkflow:mocks.cancel,
  buildPublicFileUrl:(p:string)=>p,fetchTeacherResources:mocks.resources}));
const action={action_id:"stats",label:"圈内外人口统计",type:"statistics" as const};
const stage={stage_id:"world_intro",title:"世界",actions:[action,{action_id:"summary",label:"小结",type:"summary"}]} as LessonStage;
const lesson={lesson_id:"teacher"} as LessonRecord;
const session={session_id:"s",project_id:"p",events:[]} as unknown as ClassSessionRecord;
beforeEach(()=>{vi.clearAllMocks();mocks.resources.mockResolvedValue({maps:[],figures_available:false,population_available:false});mocks.apply.mockResolvedValue({action,materials:[],session});mocks.start.mockResolvedValue({job_id:"j"});mocks.log.mockResolvedValue({});});
afterEach(cleanup);
it("requests an image only for the teacher's explicit Finland review action",async()=>{
 const review={action_id:"finland_review",label:"手绘分界与协同审阅",type:"summary" as const};
 mocks.apply.mockResolvedValue({action:review,materials:[],session,prompt:"review"});const onAssistantPrompt=vi.fn();
 render(<TeacherLessonActions {...{lesson,session}} stage={{...stage,actions:[review]}} busy={false} onAssistantPrompt={onAssistantPrompt}/>);
 fireEvent.click(screen.getByText(review.label));await waitFor(()=>expect(onAssistantPrompt).toHaveBeenCalledWith("review",expect.any(String),true));
});
it("loads only a completed workflow and refreshes its real result",async()=>{
 const workflowAction={action_id:"finland_reproduce",label:"数据复现",type:"workflow" as const};
 const onRefresh=vi.fn();mocks.apply.mockResolvedValue({action:workflowAction,materials:[],session,workflow:{workflow_id:"wf"}});
 mocks.workflow.mockResolvedValue({status:"success"});mocks.result.mockResolvedValue({status:"success"});
 render(<TeacherLessonActions {...{lesson,session}} stage={{...stage,stage_id:"finland_application",actions:[workflowAction]}} busy={false} onRefresh={onRefresh}/>);
 fireEvent.click(screen.getByText("数据复现"));await screen.findByText("人口密度分析已完成，地图与图例已更新。");
 expect(mocks.result).toHaveBeenCalledWith("s","finland_application","wf");expect(onRefresh).toHaveBeenCalledTimes(2);
});
it("requires real polygon geometry and never substitutes brush strokes",async()=>{
 render(<TeacherLessonActions {...{lesson,stage,session}} busy={false}/>);
 fireEvent.click(screen.getByText("圈内外人口统计"));
 expect(await screen.findByRole("alert")).toHaveTextContent("绘区工具");expect(mocks.apply).not.toHaveBeenCalled();expect(mocks.start).not.toHaveBeenCalled();
});
it("shows no-data honestly instead of a zero-valued population pie",async()=>{
 mocks.job.mockResolvedValue({status:"completed",result:{status:"no_data",year:2015,note:"区域内没有有效人口像元",source:{url:"https://example.test"}}});
 render(<TeacherLessonActions {...{lesson,stage,session}} busy={false} geometry={{type:"Polygon",coordinates:[]}}/>);
 fireEvent.click(screen.getByText("圈内外人口统计"));await screen.findByText("区域内没有有效人口像元");
 expect(screen.queryByRole("img")).toBeNull();expect(mocks.log).toHaveBeenCalled();
});
it("requires teacher confirmation before exporting a revised summary",async()=>{
 const onExport=vi.fn().mockResolvedValue(undefined);
 render(<TeacherLessonActions {...{lesson,stage,session}} busy={false} onExport={onExport}/>);
 fireEvent.click(screen.getByText("审阅小结与保存成果"));const exportButton=screen.getByText("导出探究报告 PNG");expect(exportButton).toBeDisabled();
 fireEvent.change(screen.getByLabelText("教师审阅的小结"),{target:{value:"人口分布不均，资料为2015年估计。"}});
 fireEvent.click(screen.getByText("教师确认并保存"));await waitFor(()=>expect(exportButton).toBeEnabled());
 fireEvent.click(exportButton);expect(onExport).toHaveBeenCalledWith("世界","人口分布不均，资料为2015年估计。");
 fireEvent.change(screen.getByLabelText("教师审阅的小结"),{target:{value:"修订"}});expect(exportButton).toBeDisabled();
});

it("can inspect each original map, restore overlays and reset when changing cases",async()=>{
 const maps=[{id:"population",opacity:.5},{id:"climate",opacity:.5},{id:"terrain",opacity:.5}];
 const overlay={action_id:"overlay",label:"三图叠置实验",type:"scene" as const,scene:{teaching_maps:maps}};
 const population={action_id:"population",label:"案例3-1 人口",type:"scene" as const,scene:{teaching_maps:[maps[0]]}};
 mocks.resources.mockResolvedValue({maps:[{id:"population",name:"芬兰人口分布图"},{id:"climate",name:"芬兰降水气温图"},{id:"terrain",name:"芬兰地形图"}]});
 render(<TeacherLessonActions {...{lesson,session}} stage={{...stage,actions:[overlay,population]} as LessonStage} busy={false}/>);
 fireEvent.click(screen.getByText("三图叠置实验"));
 await screen.findByRole("button",{name:"单独查看芬兰降水气温图"});
 fireEvent.click(screen.getByRole("button",{name:"单独查看芬兰降水气温图"}));
 await waitFor(()=>expect(mocks.apply).toHaveBeenLastCalledWith("s","world_intro","overlay",{population:0,climate:1,terrain:0}));
 await waitFor(()=>expect(screen.getByLabelText("芬兰人口分布图不透明度")).toHaveValue("0"));
 fireEvent.click(screen.getByText("恢复叠置"));
 await waitFor(()=>expect(screen.getByLabelText("芬兰人口分布图不透明度")).toHaveValue("0.5"));
 fireEvent.click(screen.getByRole("button",{name:"单独查看芬兰地形图"}));
 await waitFor(()=>expect(screen.getByLabelText("芬兰人口分布图不透明度")).toHaveValue("0"));
 fireEvent.click(screen.getByText("案例3-1 人口"));
 await waitFor(()=>expect(mocks.apply).toHaveBeenLastCalledWith("s","world_intro","population",{}));
 await waitFor(()=>expect(screen.getByLabelText("芬兰人口分布图不透明度")).toHaveValue("0.5"));
});
