import { useState } from "react";
import type { ClassSessionRecord } from "../types";
import "./ChinaInquiryGuide.css";

export type InquiryStep = { title: string; task: string; hint: string; teacher: string; material?: string };
export type ChinaInquiryContent = { china_inquiry: InquiryStep[]; china_explain: InquiryStep[]; conclusion: string };
type Props = {
  content: ChinaInquiryContent; session: ClassSessionRecord; stageId: "china_inquiry" | "china_explain";
  busy: boolean; onEnterStage: (id: string) => void;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
};

/** Progress is a teacher navigation event; it never counts as a student response. */
export function ChinaInquiryGuide({ content, session, stageId, busy, onEnterStage, onSave }: Props) {
  const steps = content[stageId];
  const previous = [...session.events].reverse().find(e => e.type === "note" && e.stage_id === stageId && e.payload?.kind === "inquiry_navigation")?.payload;
  const [index, setIndex] = useState(() => Math.min(steps.length - 1, Math.max(0, Number(previous?.step) || 0)));
  const [paused, setPaused] = useState(previous?.paused === true);
  const [hint, setHint] = useState(false);
  const [teacher, setTeacher] = useState(false);
  const [note, setNote] = useState("");
  const [recordSource, setRecordSource] = useState("teacher_transcribed");
  const [conclusion, setConclusion] = useState(content.conclusion);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [recordOpen, setRecordOpen] = useState(false);
  const step = steps[index];
  const notes = session.events.filter(e => e.type === "note" && e.payload?.kind === "population_inquiry_record");
  const summary = stageId === "china_explain" && index === steps.length - 1;
  const locked = busy || saving;

  async function save(payload: Record<string, unknown>, done: () => void) {
    setSaving(true); setError("");
    try { await onSave(payload); done(); }
    catch (exc) { setError(exc instanceof Error ? exc.message : "保存失败，请重试；文字仍保留在输入框。"); }
    finally { setSaving(false); }
  }
  function navigate(next: number, isPaused = false) {
    void save({ kind: "inquiry_navigation", step: next, paused: isPaused, source: "teacher_navigation" }, () => {
      setIndex(next); setPaused(isPaused); setHint(false); setTeacher(false);
    });
  }
  function record(kind: "initial" | "revision" | "conclusion", text: string) {
    if (!text.trim()) return;
    void save({ kind: "population_inquiry_record", record_kind: kind, text: text.trim(),
      source: kind === "conclusion" ? "teacher_confirmed" : recordSource,
      evidence: ["builtin_population_regions", ...(stageId === "china_explain" ? ["generated_hu_line"] : [])],
    }, () => { setNote(""); setRecordOpen(true); });
  }

  return <section className="china-inquiry-guide" aria-label="中国人口探究">
    <div className="inquiry-heading"><strong>{stageId === "china_inquiry" ? index + 1 : index + 4}/6 · {step.title}</strong>
      <button className="toolbar-button compact" disabled={locked} onClick={() => navigate(index, !paused)}>{paused ? "继续本步" : "暂停讨论"}</button></div>
    {paused ? <p>讨论暂停，地图和已有成果保留。由教师决定何时继续。</p> : <>
      <p className="inquiry-task" data-testid="inquiry-student-task">{step.task}</p>
      {step.material && <details className="inquiry-material"><summary>按需查看材料</summary><p>{step.material}</p></details>}
      <div className="inquiry-actions">
        <button className="toolbar-button compact" onClick={() => setHint(!hint)}>{hint ? "收起提示" : "给一条提示"}</button>
        <button className="toolbar-button compact" onClick={() => setTeacher(!teacher)}>{teacher ? "收起教师参考" : "教师参考"}</button>
      </div>
      {hint && <p className="inquiry-hint">{step.hint}</p>}
      {teacher && <div className="inquiry-teacher"><small>教师参考 · 请按课堂需要展示</small><p>{step.teacher}</p>
        {summary && <><label>归纳草稿<textarea aria-label="教师归纳草稿" value={conclusion} onChange={e => setConclusion(e.target.value)} /></label>
          <button className="toolbar-button compact" disabled={locked || !conclusion.trim()} onClick={() => record("conclusion", conclusion)}>确认并保留归纳</button></>}
      </div>}
      <div className="inquiry-actions">
        <button className="toolbar-button compact" disabled={locked} onClick={() => index > 0 ? navigate(index - 1) : onEnterStage(stageId === "china_inquiry" ? "shanghai_verify" : "china_inquiry")}>返回上一步</button>
        <button className="toolbar-button compact primary" disabled={locked} onClick={() => index < steps.length - 1 ? navigate(index + 1) : onEnterStage(stageId === "china_inquiry" ? "china_explain" : "world_inquiry")}>
          {index < steps.length - 1 ? "下一步" : stageId === "china_inquiry" ? "揭示参考线并比较" : "进入世界迁移"}
        </button>
      </div>
    </>}
    <details open={recordOpen} onToggle={e => setRecordOpen(e.currentTarget.open)} className="inquiry-records">
      <summary>观点与归纳 · {notes.length ? `${notes.length} 条记录` : "未采集"}</summary>
      <small>口头、纸笔均可；教师只代录实际听到的观点，可留空继续。</small>
      <label>记录来源 <select aria-label="观点记录来源" value={recordSource} onChange={e => setRecordSource(e.target.value)}><option value="teacher_transcribed">教师代录实际观点</option><option value="preset_example">预设示例（非学生参与）</option></select></label>
      <label>代表性观点<textarea aria-label="代表性观点" placeholder="记录学生原话或修改后的认识" value={note} onChange={e => setNote(e.target.value)} /></label>
      <button className="toolbar-button compact" disabled={locked || !note.trim()} onClick={() => record(stageId === "china_inquiry" ? "initial" : "revision", note)}>
        {stageId === "china_inquiry" ? "保存初始观点" : "保存修正观点"}</button>
      {notes.map((event, n) => <div className="inquiry-saved" key={String(event.event_id || n)}><small>{event.payload.record_kind === "conclusion" ? "教师确认归纳" : `${event.payload.record_kind === "revision" ? "修正观点" : "初始观点"} · ${event.payload.source === "preset_example" ? "预设示例，非学生参与" : "教师代录"}`}</small><p>{String(event.payload.text || "")}</p></div>)}
    </details>
    {error && <p role="alert">{error}</p>}
    <small>计时仅作提醒；提示与主线操作无需 AI。</small>
  </section>;
}
