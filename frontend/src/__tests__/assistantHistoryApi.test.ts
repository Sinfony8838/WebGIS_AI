import {afterEach,expect,it,vi} from "vitest";
import {createAssistantFolder, updateAssistantFolder, updateAssistantConversation, setCsrfToken} from "../api";
afterEach(()=>{setCsrfToken("");vi.restoreAllMocks();});
it("sends history mutations as JSON with cookie and CSRF authentication",async()=>{
 const fetcher=vi.spyOn(globalThis,"fetch").mockImplementation(async()=>new Response("{}",{status:200,headers:{"Content-Type":"application/json"}}));
 setCsrfToken("fixture-csrf");
 await createAssistantFolder("p1","人口分布");
 await updateAssistantFolder("p1","f1",{pinned:true});
 await updateAssistantConversation("c1",{deleted:true});
 expect(fetcher).toHaveBeenCalledTimes(3);
 for(const [,init] of fetcher.mock.calls){
  expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  expect(new Headers(init?.headers).get("X-WebGIS-CSRF")).toBe("fixture-csrf");
  expect(init?.credentials).toBe("include");
 }
 expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({name:"人口分布"});
});
