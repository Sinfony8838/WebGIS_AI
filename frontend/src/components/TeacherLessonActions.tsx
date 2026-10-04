import { useEffect, useRef, useState } from "react";
import { applyTeacherLessonAction, applyTeacherWorkflowResult, buildPublicFileUrl, fetchJob, fetchTeacherResources, fetchWorkflow, cancelTeacherWorkflow, logSessionEvent, startPopulationZoneSummary, type TeacherActionResponse } from "../api";
import type { ClassSessionRecord, LessonRecord, LessonStage, PopulationZoneSummary, TeacherLessonAction } from "../types";
import "./TeacherLessonActions.css";

type Props = {
  lesson: LessonRecord; stage: LessonStage; session: ClassSessionRecord; busy: boolean;
  geometry?: Record<string, unknown> | null; onRefresh?: () => void | Promise<void>;
  onSessionChange?: (session: ClassSessionRecord) => void;
  onAssistantPrompt?: (prompt: string, message?: string, captureMap?: boolean) => void;
  onExport?: (title: string, summary: string) => Promise<void>;
  assistantDraft?: string;
  assistantDraftJobId?: string;
};

export function TeacherLessonActions({ lesson, stage, session, busy, geometry, onRefresh, onSessionChange, onAssistantPrompt, onExport, assistantDraft, assistantDraftJobId }: Props) {
  const [selected, setSelected] = useState<TeacherLessonAction | null>(null);
  const [materials, setMaterials] = useState<TeacherActionResponse["materials"]>([]);
  const [error, setError] = useState(""); const [pending, setPending] = useState(false);
  const [summary, setSummary] = useState<PopulationZoneSummary | null>(null);
  const [draft, setDraft] = useState(""); const [confirmed, setConfirmed] = useState(false);
  const [opacities, setOpacities] = useState<Record<string, number>>({});
  const [resources, setResources] = useState<Awaited<ReturnType<typeof fetchTeacherResources>> | null>(null);
  const epoch = useRef(0);
  const waitingDraft = useRef<string | null>(null);
  const activeWorkflow = useRef<string | null>(null);
  const [workflowStatus,setWorkflowStatus] = useState("");
  useEffect(() => {
    if (waitingDraft.current !== null && assistantDraftJobId && assistantDraftJobId !== waitingDraft.current && assistantDraft) {
      setDraft(assistantDraft); setConfirmed(false); waitingDraft.current = null;
    }
  }, [assistantDraft, assistantDraftJobId]);
  useEffect(() => { let live = true; fetchTeacherResources(lesson.lesson_id).then(r => { if (live) setResources(r); }).catch(() => { if (live) setResources(null); }); return () => { live = false; }; }, [lesson.lesson_id]);
  useEffect(() => {
    epoch.current += 1; waitingDraft.current = null; setError(""); setPending(false); setMaterials([]); setSummary(null); setOpacities({});setWorkflowStatus("");
    const last = [...session.events].reverse().find(e => e.type === "lesson_action" && e.stage_id === stage.stage_id);
    setSelected(stage.actions?.find(a => a.action_id === last?.payload?.action_id) || null);
    setOpacities((last?.payload?.opacities || {}) as Record<string, number>);
    const count = [...session.events].reverse().find(e => e.type === "note" && e.stage_id === stage.stage_id && e.payload?.kind === "population_zonal_result");
    setSummary((count?.payload?.result as PopulationZoneSummary) || null);
    const saved = [...session.events].reverse().find(e => e.type === "note" && e.stage_id === stage.stage_id && e.payload?.kind === "teacher_confirmed_summary");
    setDraft(String(saved?.payload?.text || "")); setConfirmed(Boolean(saved));
    return () => { epoch.current += 1; if(activeWorkflow.current) {void cancelTeacherWorkflow(activeWorkflow.current).catch(()=>undefined);activeWorkflow.current=null;} };
  }, [stage.stage_id, session.session_id]);
  const locked = busy || pending;
  async function run(action: TeacherLessonAction, requestedOpacities?: Record<string, number>) {
    // Each material selection starts from its own preset; slider/view changes
    // remain local to that selection and cannot hide the next case's population map.
    const opacityPatch = requestedOpacities ?? (selected?.action_id === action.action_id ? opacities : {});
    const token = epoch.current; setPending(true); setError("");
    try {
      if (action.type === "statistics" && !geometry) throw new Error("请先使用地图右侧绘区工具圈定统计范围；画笔线条不能作为统计区域。");
      const response = await applyTeacherLessonAction(session.session_id, stage.stage_id, action.action_id, opacityPatch);
      if (token !== epoch.current) return;
      setSelected(action);
      setOpacities(Object.fromEntries((action.scene?.teaching_maps || []).map(item => [item.id, opacityPatch[item.id] ?? item.opacity])));
      setMaterials(response.materials); onSessionChange?.(response.session); await onRefresh?.();
      if (response.prompt) { waitingDraft.current = assistantDraftJobId || ""; onAssistantPrompt?.(response.prompt, action.label + "（教师审阅草稿）", action.action_id === "finland_review"); }
      if(response.workflow?.workflow_id) {
        activeWorkflow.current=response.workflow.workflow_id;setWorkflowStatus("人口密度分析正在运行…");
        let finished=false;
        for(let i=0;i<240 && token===epoch.current;i++) {
          const record=await fetchWorkflow(response.workflow.workflow_id);
          if(token!==epoch.current)return;
          if(record.status==="error" || record.status==="cancelled")throw new Error(record.error?.user_friendly || "人口密度分析未完成，请检查分析环境。");
          if(record.status==="success") {finished=true;break;}
          await new Promise(resolve=>window.setTimeout(resolve,500));
        }
        if(token!==epoch.current)return;
        if(!finished)throw new Error("分析仍在运行，请打开GIS分析面板查看进度。");
        await applyTeacherWorkflowResult(session.session_id,stage.stage_id,response.workflow.workflow_id);
        if(token!==epoch.current)return;
        activeWorkflow.current=null;setWorkflowStatus("人口密度分析已完成，地图与图例已更新。");await onRefresh?.();
      }
      if (action.type === "statistics" && geometry) {
        const job = await startPopulationZoneSummary(session.project_id, geometry);
        let result: PopulationZoneSummary | null = null;
        for (let i = 0; i < 240 && token === epoch.current; i++) {
          const state = await fetchJob(job.job_id);
          if (state.status === "failed") throw new Error(state.error || "统计失败。");
          if (state.status === "completed") { result = state.result as unknown as PopulationZoneSummary; break; }
          await new Promise(resolve => window.setTimeout(resolve, 500));
        }
        if (token !== epoch.current) return;
        if (!result) throw new Error("统计尚未完成，请稍后重试。");
        setSummary(result);
        await logSessionEvent(session.session_id, { event_type: "note", stage_id: stage.stage_id, payload: { kind: "population_zonal_result", source: "WorldPop2015", result } });
      }
    } catch (e) { if (token === epoch.current) setError(e instanceof Error ? e.message : "操作失败。"); }
    finally { if (token === epoch.current) setPending(false); }
  }
  async function confirmSummary() {
    const token = epoch.current;
    setError(""); setPending(true);
    try {
      await logSessionEvent(session.session_id, { event_type: "note", stage_id: stage.stage_id, payload: { kind: "teacher_confirmed_summary", source: "teacher_entered", text: draft.trim(), geometry: geometry || null } });
      if (token === epoch.current) setConfirmed(true);
    } catch (e) { if (token === epoch.current) setError(e instanceof Error ? e.message : "保存失败。"); }
    finally { if (token === epoch.current) setPending(false); }
  }
  return <section className="teacher-lesson-actions" aria-label="修订稿教学操作">
    <p className="teacher-source">张玥修订稿 · 教师自主掌握节奏</p>
    <div className="teacher-action-buttons">{stage.actions?.map(action => <button type="button" key={action.action_id} aria-pressed={selected?.action_id === action.action_id} disabled={locked} onClick={() => void run(action)}>{action.label}</button>)}</div>
    {pending && <p role="status">正在处理，请稍候…</p>}{error && <p role="alert">{error}</p>}
    {workflowStatus && <p role="status">{workflowStatus}</p>}
    {selected?.note && <p>{selected.note}</p>}
    {selected?.type === "video" && <a href={selected.url} target="_blank" rel="noreferrer">打开原视频播放 ↗</a>}
    {(selected?.scene?.teaching_maps?.length || 0) > 1 && <p className="teacher-overlay-note">多图叠置会混合颜色，不能用人口图例解读降水或地形。可单独查看各图，再恢复叠置进行比较。</p>}
    {selected?.scene?.teaching_maps?.map(item => {
      const name = resources?.maps.find(m => m.id === item.id)?.name || item.id;
      return <div className="teacher-map-control" key={item.id}>
        <label className="teacher-opacity">{name} · {Math.round((opacities[item.id] ?? item.opacity) * 100)}%<input aria-label={`${name}不透明度`} type="range" min="0" max="1" step="0.05" value={opacities[item.id] ?? item.opacity} disabled={locked} onChange={e => setOpacities(p => ({ ...p, [item.id]: Number(e.target.value) }))} onPointerUp={() => void run(selected)} onKeyUp={e => { if (["ArrowLeft","ArrowRight","Home","End"].includes(e.key)) void run(selected); }} /></label>
        {(selected.scene?.teaching_maps?.length || 0) > 1 && <button type="button" aria-label={`单独查看${name}`} disabled={locked} onClick={() => void run(selected, Object.fromEntries((selected.scene?.teaching_maps || []).map(map => [map.id, map.id === item.id ? 1 : 0])))}>单独查看</button>}
      </div>;
    })}
    {(selected?.scene?.teaching_maps?.length || 0) > 1 && <button type="button" disabled={locked} onClick={() => selected && void run(selected, {})}>恢复叠置</button>}
    {materials.length > 0 && <details><summary>教师原稿配图 {materials.length} 张</summary><div className="teacher-materials">{materials.map(m => <figure key={m.url}><img src={buildPublicFileUrl(m.url)} alt={`修订稿本环节配图 ${m.order}`} /><figcaption>{m.source}</figcaption></figure>)}</div></details>}
    {summary && <div className="teacher-zone-result"><strong>{summary.year}年人口估计</strong>{summary.status === "success" ? <><div className="teacher-pie" role="img" aria-label={`圈内${summary.inside_percent}%，圈外${summary.outside_percent}%`} style={{ background: `conic-gradient(#218e9b 0 ${summary.inside_percent}%, #d9e5ee ${summary.inside_percent}% 100%)` }} /><p>圈内 {summary.inside_population?.toLocaleString()} 人 · {summary.inside_percent}%<br/>圈外 {summary.outside_population?.toLocaleString()} 人 · {summary.outside_percent}%</p><p>{summary.method}</p></> : null}<p>{summary.note}</p><a href={summary.source.url} target="_blank" rel="noreferrer">数据来源与说明 ↗</a></div>}
    {stage.actions?.some(a => a.type === "summary") && <details className="teacher-summary"><summary>审阅小结与保存成果</summary><p>助教回答为草稿。将需要保留的内容填入下方，修改并确认后用于课堂讲义和成果导出。</p><textarea aria-label="教师审阅的小结" value={draft} onChange={e => { setDraft(e.target.value); setConfirmed(false); }} placeholder="填写或粘贴助教草稿，并核对本课材料和年份" /><button type="button" disabled={locked || !draft.trim() || confirmed} onClick={() => void confirmSummary()}>{confirmed ? "已确认并保存" : "教师确认并保存"}</button>{onExport && <button type="button" disabled={locked || !confirmed} onClick={() => { setError(""); void onExport(stage.title, draft).catch(e => setError(e instanceof Error ? e.message : "导出失败")); }}>导出探究报告 PNG</button>}</details>}
    <details className="teacher-resource-check"><summary>课前资料检查</summary>{resources ? <><p>原稿配图：{resources.figures_available ? "已准备" : "未准备"}；人口统计包：{resources.population_available ? "已准备" : "未准备"}</p>{resources.maps.map(m => <p key={m.id}>{m.available ? "✓" : "待准备"} {m.name}</p>)}</> : <p>资料状态尚未取得，请检查连接。</p>}</details>
  </section>;
}
