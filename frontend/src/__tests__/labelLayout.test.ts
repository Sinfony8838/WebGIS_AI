import { expect, it } from "vitest";
import { selectVisibleLabels } from "../lib/labelLayout";
it("keeps higher-priority labels without overlaps or clipped viewport text", () => {
  const box = {left:20,top:20,width:120,height:30};
  expect([...selectVisibleLabels([
    {id:"high",...box}, {id:"overlap",...box,left:100}, {id:"clear",...box,top:70},
    {id:"outside",...box,left:280}, {id:"behind",...box,left:NaN},
  ],320,200)]).toEqual(["high","clear"]);
});
it("reveals labels when their projected positions separate", () => {
  const boxes = [{id:"a",left:20,top:20,width:100,height:30}, {id:"b",left:20,top:80,width:100,height:30}];
  expect(selectVisibleLabels(boxes,320,200).size).toBe(2);
  expect(selectVisibleLabels(boxes,100,100).size).toBe(0);
});
