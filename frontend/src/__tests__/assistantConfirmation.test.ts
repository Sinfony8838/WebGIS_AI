import {describe, expect, it, vi} from "vitest";
import {removedLayersApplied, submitAssistantConfirmation} from "../lib/assistantConfirmation";

function deferred<T>() {
  let resolve!: (value:T)=>void;
  let reject!: (reason:unknown)=>void;
  const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});
  return {promise,resolve,reject};
}
function harness() {
  const response=deferred<{job_id:string}>();
  let submitting=false;
  let current=true;
  const options={blocked:()=>submitting,setSubmitting:(value:boolean)=>{submitting=value;},
    request:vi.fn(()=>response.promise),isCurrent:()=>current,cancelStale:vi.fn(async()=>{}),accept:vi.fn()};
  return {options,response,isSubmitting:()=>submitting,invalidate:()=>{current=false;}};
}
describe("assistant confirmation submission",()=>{
  it("shares the lock so repeated approvals create one job",async()=>{
    const h=harness();const first=submitAssistantConfirmation(h.options);
    expect(h.isSubmitting()).toBe(true);
    expect(await submitAssistantConfirmation(h.options)).toBe(false);
    h.response.resolve({job_id:"confirmed"});expect(await first).toBe(true);
    expect(h.options.request).toHaveBeenCalledTimes(1);expect(h.options.accept).toHaveBeenCalledWith("confirmed");
    expect(h.isSubmitting()).toBe(false);
  });
  it.each(["project", "user", "mode", "conversation"])("cancels a late job after its %s scope changes",async()=>{
    const h=harness();const pending=submitAssistantConfirmation(h.options);h.invalidate();h.response.resolve({job_id:"old"});
    expect(await pending).toBe(false);expect(h.options.cancelStale).toHaveBeenCalledWith("old");
    expect(h.options.accept).not.toHaveBeenCalled();expect(h.isSubmitting()).toBe(false);
  });
  it("keeps cancellation errors visible and releases the barrier",async()=>{
    const h=harness();h.options.cancelStale.mockRejectedValueOnce(new Error("cancel unavailable"));
    const pending=submitAssistantConfirmation(h.options);h.invalidate();h.response.resolve({job_id:"old"});
    await expect(pending).rejects.toThrow("cancel unavailable");expect(h.isSubmitting()).toBe(false);
    expect(h.options.accept).not.toHaveBeenCalled();
  });
  it("releases the submission barrier on API failure and permits a retry",async()=>{
    const h=harness();const pending=submitAssistantConfirmation(h.options);h.response.reject(new Error("expired"));
    await expect(pending).rejects.toThrow("expired");expect(h.isSubmitting()).toBe(false);
    h.options.request.mockResolvedValueOnce({job_id:"retry"});expect(await submitAssistantConfirmation(h.options)).toBe(true);
  });
  it("registers an accepted confirmation job before releasing the cancellation barrier",async()=>{
    const h=harness();let active="";h.options.accept.mockImplementation(id=>{
      expect(h.isSubmitting()).toBe(true);active=id;
    });
    const pending=submitAssistantConfirmation(h.options);h.response.resolve({job_id:"delete"});await pending;
    expect(active).toBe("delete");expect(h.isSubmitting()).toBe(false);
  });
});

describe("layer removal evidence",()=>{
  const absent={removedIds:["one","two"],currentLayerIds:["keep"],hasPlaneLayer:()=>false,hasGlobeLayer:()=>false};
  it("requires absence from the current list and both map renderers",()=>{
    expect(removedLayersApplied(absent)).toBe(true);
    expect(removedLayersApplied({...absent,currentLayerIds:["two"]})).toBe(false);
    expect(removedLayersApplied({...absent,hasPlaneLayer:id=>id==="one"})).toBe(false);
    expect(removedLayersApplied({...absent,hasGlobeLayer:id=>id==="two"})).toBe(false);
  });
  it("does not confirm an uninitialized snapshot or globe renderer",()=>{
    expect(removedLayersApplied({...absent,currentLayerIds:undefined})).toBe(false);
    expect(removedLayersApplied({...absent,hasGlobeLayer:()=>undefined})).toBe(false);
  });
  it("preserves ordinary sync actions without a removal contract",()=>{
    expect(removedLayersApplied({...absent,removedIds:undefined,currentLayerIds:undefined})).toBe(true);
  });
});
