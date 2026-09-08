import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react";
import type { BrushOverlayHandle, BrushSettings } from "./BrushOverlay";
import { anchorPaths, eraseInk, shapePaths, type InkPoint, type MapInkProjection, type MapInkStroke } from "../lib/mapInk";

type Props = { active: boolean; settings: BrushSettings; projection: MapInkProjection; scope: string;
  onWheelZoom?: (event: WheelEvent) => void; onContentChange?: (value: boolean) => void };

export const MapBrushOverlay = forwardRef<BrushOverlayHandle, Props>(function MapBrushOverlay(
  { active, settings, projection, scope, onWheelZoom, onContentChange }, ref
) {
  const canvasRef=useRef<HTMLCanvasElement>(null);
  const strokes=useRef<MapInkStroke[]>([]), history=useRef<MapInkStroke[][]>([]);
  const draft=useRef<MapInkStroke|null>(null);
  const gesture=useRef<{ start:InkPoint; last:InkPoint; settings:BrushSettings; pointer:number }|null>(null);
  const latest=useRef({projection,onContentChange});
  latest.current={projection,onContentChange};
  const notify=useCallback(() => latest.current.onContentChange?.(strokes.current.length>0),[]);
  const snapshot=useCallback(() => { history.current.push(strokes.current); if(history.current.length>30) history.current.shift(); },[]);
  const renderInk=useCallback(() => {
    const canvas=canvasRef.current, ctx=canvas?.getContext("2d");
    if(!canvas || !ctx) return;
    const rect=canvas.getBoundingClientRect();
    const width=canvas.clientWidth || rect.width, height=canvas.clientHeight || rect.height;
    const dpr=window.devicePixelRatio||1;
    if(canvas.width!==Math.round(width*dpr) || canvas.height!==Math.round(height*dpr)) {
      canvas.width=Math.round(width*dpr); canvas.height=Math.round(height*dpr);
    }
    ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,width,height);
    const scaleX=rect.width ? width/rect.width : 1, scaleY=rect.height ? height/rect.height : 1;
    for(const stroke of [...strokes.current,...(draft.current?[draft.current]:[])]) {
      ctx.strokeStyle=stroke.color; ctx.lineWidth=stroke.lineWidth; ctx.lineCap="round"; ctx.lineJoin="round";
      ctx.beginPath();
      for(const path of stroke.paths) {
        let previous:InkPoint|null=null;
        for(const world of path) {
          const client=latest.current.projection.toClient(world);
          if(!client || !client.every(Number.isFinite)) { previous=null; continue; }
          const p:InkPoint=[(client[0]-rect.left)*scaleX,(client[1]-rect.top)*scaleY];
          // Split at a wrapped-world seam rather than drawing across the map.
          if(!previous || Math.abs(p[0]-previous[0])>width/2) ctx.moveTo(...p);
          else ctx.lineTo(...p);
          if(path.length===1) ctx.lineTo(p[0]+0.01,p[1]);
          previous=p;
        }
      }
      ctx.stroke();
    }
  },[]);
  const finish=useCallback(() => {
    if(draft.current?.paths.length) strokes.current=[...strokes.current,draft.current];
    draft.current=null; gesture.current=null; notify(); renderInk();
  },[notify,renderInk]);
  useImperativeHandle(ref,() => ({
    clear:() => { finish(); snapshot(); strokes.current=[]; notify(); renderInk(); },
    undo:() => { draft.current=null; gesture.current=null; strokes.current=history.current.pop()||strokes.current; notify(); renderInk(); },
    exportImage:() => { renderInk(); return strokes.current.length ? canvasRef.current?.toDataURL("image/png")||null : null; },
    // Raster imports have no geographic reference. Only PPT uses loadImage.
    loadImage:() => { throw new Error("地图笔迹需要地理坐标，不能从无定位的图片恢复。"); }
  }),[finish,snapshot,notify,renderInk]);
  useLayoutEffect(() => { strokes.current=[]; history.current=[]; draft.current=null; gesture.current=null; notify(); renderInk(); },[scope,notify,renderInk]);
  useLayoutEffect(() => {
    finish();
    let unsubscribe:(() => void)|undefined, frame=0;
    const connect=() => { renderInk(); unsubscribe=projection.subscribe(renderInk); if(!unsubscribe) frame=requestAnimationFrame(connect); };
    connect();
    const observer=new ResizeObserver(renderInk); if(canvasRef.current) observer.observe(canvasRef.current);
    return () => { cancelAnimationFrame(frame); unsubscribe?.(); observer.disconnect(); };
  },[projection,finish,renderInk]);
  useEffect(() => { if(!active) finish(); },[active,finish]);
  useEffect(() => {
    const canvas=canvasRef.current; if(!canvas) return;
    const wheel=(event:WheelEvent) => { if(active) { finish(); onWheelZoom?.(event); } };
    canvas.addEventListener("wheel",wheel,{passive:false}); return () => canvas.removeEventListener("wheel",wheel);
  },[active,finish,onWheelZoom]);
  return <canvas ref={canvasRef} className={`brush-overlay ${active?"brush-overlay--active":""}`}
    aria-label="地理定位的课堂笔迹" data-testid="map-brush-overlay"
    style={{width:"100%",height:"100%",touchAction:"none",cursor:settings.tool==="eraser"?"cell":"crosshair"}}
    onPointerDown={event => {
      if(!active || event.button!==0) return;
      const point:InkPoint=[event.clientX,event.clientY];
      if(!projection.toWorld(point)) return;
      event.preventDefault(); snapshot();
      canvasRef.current?.setPointerCapture?.(event.pointerId);
      gesture.current={start:point,last:point,settings:{...settings},pointer:event.pointerId};
      if(settings.tool==="eraser") strokes.current=eraseInk(strokes.current,point,Math.max(6,settings.lineWidth*2),projection.toClient);
      else draft.current={color:settings.color,lineWidth:settings.lineWidth,paths:anchorPaths([[point]],projection.toWorld)};
      renderInk();
    }}
    onPointerMove={event => {
      const g=gesture.current; if(!active || !g || g.pointer!==event.pointerId) return;
      event.preventDefault(); const point:InkPoint=[event.clientX,event.clientY];
      if(g.settings.tool==="eraser") {
        const steps=Math.max(1,Math.ceil(Math.hypot(point[0]-g.last[0],point[1]-g.last[1])/4));
        for(let i=1;i<=steps;i++) strokes.current=eraseInk(strokes.current,[g.last[0]+(point[0]-g.last[0])*i/steps,g.last[1]+(point[1]-g.last[1])*i/steps],Math.max(6,g.settings.lineWidth*2),projection.toClient);
      } else if(g.settings.tool==="freehand") {
        const segment=anchorPaths([[g.last,point]],projection.toWorld);
        draft.current={color:g.settings.color,lineWidth:g.settings.lineWidth,paths:[...(draft.current?.paths||[]),...segment]};
      } else draft.current={color:g.settings.color,lineWidth:g.settings.lineWidth,paths:anchorPaths(shapePaths(g.start,point,g.settings),projection.toWorld)};
      g.last=point; renderInk();
    }}
    onPointerUp={finish} onPointerCancel={finish} onLostPointerCapture={finish}
  />;
});
