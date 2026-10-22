import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {AssistantVoice,type AssistantVoiceSnapshot} from "../assistantVoice";
import {createVoiceStream,type VoiceStreamEvents} from "../voiceStream";
import {cancelSpeech, isSpeaking} from "../speechSynthesis";
import type {JobRecord} from "../types";
vi.mock("../voiceStream",()=>({createVoiceStream:vi.fn()}));
vi.mock("../speechSynthesis",()=>({cancelSpeech:vi.fn(),isSpeaking:vi.fn(()=>false)}));
let events:VoiceStreamEvents;
const stop=vi.fn(),abort=vi.fn();
let controllers:AssistantVoice[]=[];
function setup(mode:"chat"|"operate"="operate") {
 const submit=vi.fn().mockResolvedValue(true),notice=vi.fn(),draft=vi.fn(),cancelTask=vi.fn(),reply=vi.fn();
 let snapshot:AssistantVoiceSnapshot;
 const voice=new AssistantVoice({apiBase:()=>"",mode:()=>mode,submit,notice,draft,cancelTask,reply,snapshot:s=>{snapshot=s;}});
 controllers.push(voice);return {voice,submit,notice,draft,cancelTask,reply,get state(){return snapshot;}};
}
const job=(id:string,status="running",outcome="completed")=>({job_id:id,status,result:{outcome,assistant_message:"操作结果"}} as JobRecord);
beforeEach(()=>{vi.useFakeTimers();vi.clearAllMocks();vi.mocked(isSpeaking).mockReturnValue(false);stop.mockResolvedValue("");vi.mocked(createVoiceStream).mockImplementation(async(_base,e)=>{events=e;e.onOpen?.();return {stop,abort,state:()=>"open"};});});
afterEach(()=>{controllers.forEach(v=>v.dispose());controllers=[];vi.useRealTimers();});
describe("shared voice input",()=>{
 it("does not capture until explicitly clicked",()=>{setup();expect(createVoiceStream).not.toHaveBeenCalled();});
 it("accumulates all single-recording segments and sends once on stop",async()=>{const t=setup();t.voice.tap();await vi.advanceTimersByTimeAsync(701);events.onFinal?.("不要改原图");events.onFinal?.("另做一张对比图");expect(t.submit).not.toHaveBeenCalled();t.voice.tap();await vi.advanceTimersByTimeAsync(1);expect(t.submit).toHaveBeenCalledTimes(1);expect(t.submit).toHaveBeenCalledWith("不要改原图，另做一张对比图");});
 it("triple tap promotes capture without sending or creating another mic",async()=>{const t=setup();t.voice.tap(0);t.voice.tap(200);t.voice.tap(400);await vi.advanceTimersByTimeAsync(800);expect(t.state.capture).toBe("continuous");expect(createVoiceStream).toHaveBeenCalledTimes(1);expect(stop).not.toHaveBeenCalled();expect(t.submit).not.toHaveBeenCalled();});
 it("double tap waits through gesture window and does not send silence",async()=>{const t=setup();t.voice.tap(0);t.voice.tap(300);await vi.advanceTimersByTimeAsync(701);expect(stop).toHaveBeenCalledOnce();expect(t.submit).not.toHaveBeenCalled();});
 it("flush timeout preserves draft instead of auto-submitting",async()=>{const t=setup();t.voice.tap();await vi.advanceTimersByTimeAsync(701);events.onPartial?.("北京上海");stop.mockResolvedValue(null);t.voice.tap();await vi.advanceTimersByTimeAsync(1);expect(t.draft).toHaveBeenCalledWith("北京上海");expect(t.submit).not.toHaveBeenCalled();});
 it("chat accepts questions without operation keywords",async()=>{const t=setup("chat");t.voice.startContinuous();await vi.advanceTimersByTimeAsync(1);events.onFinal?.("什么是等高线");expect(t.submit).toHaveBeenCalledWith("什么是等高线");});
 it("internal ASR segments are not independently executed",async()=>{const t=setup();t.voice.startContinuous();await vi.advanceTimersByTimeAsync(1);events.onFinal?.("连接北京上海",{segment_id:"1",end_reason:"segment"});expect(t.submit).not.toHaveBeenCalled();events.onFinal?.("再叠加地形曲线",{segment_id:"2",end_reason:"silence"});expect(t.submit).toHaveBeenCalledWith("连接北京上海，再叠加地形曲线");});
 it("deduplicates segment ids, but not legitimate repeated commands",async()=>{const t=setup();t.voice.startContinuous();await vi.advanceTimersByTimeAsync(1);events.onFinal?.("放大",{segment_id:"1",end_reason:"silence"});events.onFinal?.("放大",{segment_id:"1",end_reason:"silence"});expect(t.submit).toHaveBeenCalledTimes(1);t.voice.setJob(job("a"));t.voice.setBusy(true);events.onFinal?.("放大",{segment_id:"2",end_reason:"silence"});expect(t.state.queue).toHaveLength(1);});
 it("queues busy requests and only drains after completion",async()=>{const t=setup();t.voice.startContinuous();await vi.advanceTimersByTimeAsync(1);t.voice.setBusy(true);t.voice.setJob(job("a"));events.onFinal?.("放大");events.onFinal?.("缩小");expect(t.submit).not.toHaveBeenCalled();expect(t.state.queue).toHaveLength(2);t.voice.setJob(job("a","completed"));t.voice.setBusy(false);await vi.advanceTimersByTimeAsync(1);expect(t.submit).toHaveBeenCalledTimes(1);expect(t.submit).toHaveBeenCalledWith("放大");});
 it("bounds queue to three and preserves overflow",async()=>{const t=setup();t.voice.startContinuous();await vi.advanceTimersByTimeAsync(1);t.voice.setBusy(true);for(let i=0;i<4;i++)events.onFinal?.("放大");expect(t.state.queue).toHaveLength(3);expect(t.draft).toHaveBeenCalledWith("放大");});
 it("hangup clears waiting requests but does not cancel the current task",async()=>{const t=setup();t.voice.startContinuous();await vi.advanceTimersByTimeAsync(1);t.voice.setBusy(true);events.onFinal?.("放大");t.voice.tap();expect(t.state.capture).toBe("off");expect(t.state.queue).toHaveLength(0);expect(t.cancelTask).not.toHaveBeenCalled();expect(abort).toHaveBeenCalled();});
 it("explicit stop cancels task and queue without a model request",async()=>{const t=setup();t.voice.startContinuous();await vi.advanceTimersByTimeAsync(1);t.voice.setBusy(true);events.onFinal?.("放大");events.onFinal?.("停止操作");expect(t.cancelTask).toHaveBeenCalledOnce();expect(t.submit).not.toHaveBeenCalled();expect(t.state.queue).toHaveLength(0);});
 it("reconnection cannot extend the call lifetime",async()=>{const t=setup();t.voice.startContinuous();await vi.advanceTimersByTimeAsync(800000);events.onClose?.({code:1006,reason:"network",wasClean:false});await vi.advanceTimersByTimeAsync(100001);expect(t.state.capture).toBe("off");expect(t.notice).toHaveBeenCalledWith("已达到本次通话时限，请重新开启麦克风。");});
 it("late callbacks cannot submit after disposal",async()=>{const t=setup();t.voice.startContinuous();await vi.advanceTimersByTimeAsync(1);t.voice.dispose();events.onFinal?.("放大");expect(t.submit).not.toHaveBeenCalled();});
 it("dependency failure keeps followup as draft",async()=>{const t=setup();t.voice.startContinuous();await vi.advanceTimersByTimeAsync(1);t.voice.setBusy(true);t.voice.setJob(job("a"));events.onFinal?.("把刚才结果做成地图");t.voice.setJob(job("a","failed"));t.voice.setBusy(false);await vi.advanceTimersByTimeAsync(1);expect(t.submit).not.toHaveBeenCalled();expect(t.draft).toHaveBeenCalledWith("把刚才结果做成地图");});
 it("confirmation suspends queue",async()=>{const t=setup();t.voice.startContinuous();await vi.advanceTimersByTimeAsync(1);t.voice.setBusy(true);events.onFinal?.("放大");t.voice.setJob({...job("a","completed"),result:{requires_confirmation:true}});t.voice.setBusy(false);await vi.advanceTimersByTimeAsync(1);expect(t.submit).not.toHaveBeenCalled();});
 it("echo does not become an operation",async()=>{const t=setup();t.voice.startContinuous();await vi.advanceTimersByTimeAsync(1);events.onFinal?.("切换到三维地球");t.voice.setJob(job("a"));t.voice.setJob({...job("a","completed"),result:{assistant_message:"已经切换到三维地球"}});vi.mocked(isSpeaking).mockReturnValue(true);events.onFinal?.("已经切换到三维地球");expect(t.submit).toHaveBeenCalledTimes(1);expect(cancelSpeech).toHaveBeenCalled();});
});
