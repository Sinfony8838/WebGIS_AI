import { createRef } from "react";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MapBrushOverlay } from "../components/MapBrushOverlay";
import type { BrushOverlayHandle } from "../components/BrushOverlay";
import { anchorPaths, eraseInk, shapePaths, type MapInkProjection } from "../lib/mapInk";

const context={setTransform:vi.fn(),clearRect:vi.fn(),beginPath:vi.fn(),moveTo:vi.fn(),lineTo:vi.fn(),stroke:vi.fn()};
let renderMap:()=>void=()=>{}, scale=1, offset=0;
const projection:MapInkProjection={
  toWorld:([x,y])=>[(x-10-offset)/scale,(y-20)/scale],
  toClient:([x,y])=>[x*scale+10+offset,y*scale+20],
  subscribe:callback=>{renderMap=callback;return vi.fn();}
};
beforeEach(()=>{
  scale=1;offset=0;vi.clearAllMocks();
  vi.stubGlobal("ResizeObserver",class {observe(){} disconnect(){}});
  vi.stubGlobal("PointerEvent",MouseEvent);
  vi.spyOn(HTMLCanvasElement.prototype,"getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype,"getBoundingClientRect").mockReturnValue({left:10,top:20,width:400,height:300} as DOMRect);
  Object.defineProperty(window,"devicePixelRatio",{configurable:true,value:2});
  vi.spyOn(HTMLElement.prototype,"clientWidth","get").mockReturnValue(400);
  vi.spyOn(HTMLElement.prototype,"clientHeight","get").mockReturnValue(300);
});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});

it("reprojects a geographic line after pan, zoom, and return to the same scene",()=>{
  const {getByTestId}=render(<MapBrushOverlay active settings={{tool:"line",color:"red",lineWidth:4}} projection={projection} scope="project"/>);
  const canvas=getByTestId("map-brush-overlay");
  fireEvent.pointerDown(canvas,{clientX:110,clientY:120,button:0});
  fireEvent.pointerMove(canvas,{clientX:160,clientY:170});fireEvent.pointerUp(canvas);
  expect(context.lineTo).toHaveBeenLastCalledWith(150,150);
  scale=2;offset=-100;act(()=>renderMap());
  expect(context.moveTo).toHaveBeenLastCalledWith(100,200);
  expect(context.lineTo).toHaveBeenLastCalledWith(200,300);
  offset=-1000;act(()=>renderMap());
  expect(context.lineTo).toHaveBeenLastCalledWith(-700,300);
  scale=1;offset=0;act(()=>renderMap());
  expect(context.lineTo).toHaveBeenLastCalledWith(150,150);
  expect(context.setTransform).toHaveBeenCalledWith(2,0,0,2,0,0);
});

it("preserves geographic erasure after zoom and restores ink with undo",()=>{
  const ref=createRef<BrushOverlayHandle>(),changed=vi.fn();
  const props={active:true,projection,scope:"a",onContentChange:changed};
  const {getByTestId,rerender}=render(<MapBrushOverlay {...props} ref={ref} settings={{tool:"line",color:"red",lineWidth:4}}/>);
  const canvas=getByTestId("map-brush-overlay");
  fireEvent.pointerDown(canvas,{clientX:110,clientY:120,button:0});fireEvent.pointerMove(canvas,{clientX:210,clientY:120});fireEvent.pointerUp(canvas);
  rerender(<MapBrushOverlay {...props} ref={ref} settings={{tool:"eraser",color:"red",lineWidth:4}}/>);
  fireEvent.pointerDown(canvas,{clientX:160,clientY:120,button:0});fireEvent.pointerUp(canvas);
  scale=2;vi.clearAllMocks();act(()=>renderMap());
  expect(context.moveTo.mock.calls.length).toBe(2);
  act(()=>ref.current?.undo());
  vi.clearAllMocks();act(()=>renderMap());expect(context.moveTo.mock.calls.length).toBe(1);
  act(()=>ref.current?.clear());expect(changed).toHaveBeenLastCalledWith(false);
  act(()=>ref.current?.undo());expect(changed).toHaveBeenLastCalledWith(true);
  rerender(<MapBrushOverlay {...props} scope="another-project" ref={ref} settings={{tool:"line",color:"red",lineWidth:4}}/>);
  expect(changed).toHaveBeenLastCalledWith(false);
});

it("splits unprojectable gaps and ignores gestures that start in the sky",()=>{
  const surface=anchorPaths([[[0,0],[20,0]]],([x,y])=>x>=8&&x<=12?null:[x,y]);
  expect(surface).toHaveLength(2);
  expect(surface[0].at(-1)).toEqual([4,0]);expect(surface[1][0]).toEqual([16,0]);
  const hidden:MapInkProjection={...projection,toWorld:()=>null};
  const changed=vi.fn();
  const {getByTestId}=render(<MapBrushOverlay active settings={{tool:"line",color:"red",lineWidth:4}} projection={hidden} scope="a" onContentChange={changed}/>);
  const canvas=getByTestId("map-brush-overlay");
  fireEvent.pointerDown(canvas,{clientX:10,clientY:20,button:0});fireEvent.pointerMove(canvas,{clientX:50,clientY:60});fireEvent.pointerUp(canvas);
  expect(changed).toHaveBeenLastCalledWith(false);
});

it("anchors all shapes and never erases an occluded geographic segment",()=>{
  for(const tool of ["rectangle","ellipse","arrow"] as const) {
    const paths=anchorPaths(shapePaths([10,20],[100,80],{tool,color:"red",lineWidth:4}),p=>p);
    expect(paths.flat().length).toBeGreaterThan(10);
    const stroke={paths,color:"red",lineWidth:4};
    expect(eraseInk([stroke],[10,20],10,()=>null)).toEqual([stroke]);
  }
});
