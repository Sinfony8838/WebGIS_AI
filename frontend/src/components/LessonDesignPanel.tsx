import { useEffect, useMemo, useState } from "react";
import { createLessonDesign, exportLessonDocx, finalizeLessonDesign, resolveLessonDesignSection, turnLessonDesign } from "../api";
import type { LessonDesignSession, LessonPlanProfile, LessonRecord, LessonStage } from "../types";

type Props = { projectId: string; activeLesson: LessonRecord | null; onFinalized: (lesson: LessonRecord) => void; onClose: () => void };
const STEPS = [["requirements", "教学需求"], ["analysis", "课标与学情"], ["objectives", "目标与重难点"], ["process", "教学过程"], ["capabilities", "GIS/AI能力"], ["rehearsal", "预演检查"], ["confirmation", "确认保存"]] as const;
const EDITABLE_STEPS = ["requirements", "analysis", "objectives", "process", "capabilities"];
const splitItems = (value: string) => value.split(/[；;、\n]/).map((item) => item.trim()).filter(Boolean);

function draftSummary(draft: LessonPlanProfile): string {
  return `${draft.title || draft.topic || "未命名课时"} · ${draft.grade || "年级待定"} · ${draft.objectives?.length || 0} 个目标 · ${draft.stages?.length || 0} 个环节`;
}
function lineValue(text: string, label: string): string {
  const line = text.split(/\r?\n/).find((item) => item.trim().startsWith(label));
  return line ? line.slice(line.indexOf("：") + 1).trim() : "";
}
function formatStep(step: string, draft: LessonPlanProfile, bindings: LessonDesignSession["capability_bindings"]): string {
  if (step === "requirements") return String((draft.requirements?.raw as string | undefined) || "");
  if (step === "analysis") return [`课标解读：${draft.curriculum_interpretation || ""}`, `学情分析：${draft.student_analysis || ""}`, `教材分析：${draft.textbook_analysis || ""}`].join("\n");
  if (step === "objectives") return [`教学目标：${(draft.objectives || []).join("；")}`, `教学重点：${(draft.key_difficulties?.key || []).join("；")}`, `教学难点：${(draft.key_difficulties?.difficult || []).join("；")}`, `教学方法：${(draft.methods || []).join("；")}`, `知识结构：${(draft.knowledge_structure || []).join(" → ")}`].join("\n");
  if (step === "process") return (draft.stages || []).map((stage, index) => [`环节${index + 1}｜${stage.title}｜${stage.minutes}分钟`, `知识单元：${stage.knowledge_unit || ""}`, `知识点：${stage.knowledge_point || ""}`, `具体内容：${stage.content || ""}`, `教学活动：${(stage.activities || []).join("；")}`, `系统步骤：${(stage.system_steps || []).join("；")}`, `设计意图：${stage.design_intent || ""}`].join("\n")).join("\n\n");
  if (step === "capabilities") return bindings.map((item) => `${item.id}｜${item.reason || item.label || ""}`).join("\n");
  return "";
}
function parseStep(step: string, text: string, draft: LessonPlanProfile): Record<string, unknown> {
  if (step === "requirements") return { requirements: { ...(draft.requirements || {}), raw: text.trim() } };
  if (step === "analysis") return { curriculum_interpretation: lineValue(text, "课标解读：") || text.trim(), student_analysis: lineValue(text, "学情分析："), textbook_analysis: lineValue(text, "教材分析：") };
  if (step === "objectives") return { objectives: splitItems(lineValue(text, "教学目标：")), key_difficulties: { key: splitItems(lineValue(text, "教学重点：")), difficult: splitItems(lineValue(text, "教学难点：")) }, methods: splitItems(lineValue(text, "教学方法：")), knowledge_structure: lineValue(text, "知识结构：").split(/→|->/).map((item) => item.trim()).filter(Boolean) };
  if (step === "process") {
    const previous = draft.stages || [];
    const stages = text.split(/\r?\n\s*\r?\n/).map((block, index) => {
      const header = block.split(/\r?\n/)[0]?.split("｜") || [];
      const old = previous[index] || ({} as LessonStage);
      const minutes = Number.parseInt(String(header[2] || old.minutes || 0), 10);
      return { ...old, stage_id: old.stage_id || `s${index + 1}`, title: header[1]?.trim() || old.title || `环节${index + 1}`, minutes: Number.isFinite(minutes) ? minutes : old.minutes || 0, knowledge_unit: lineValue(block, "知识单元："), knowledge_point: lineValue(block, "知识点："), content: lineValue(block, "具体内容："), activities: splitItems(lineValue(block, "教学活动：")), system_steps: splitItems(lineValue(block, "系统步骤：")), design_intent: lineValue(block, "设计意图：") };
    }).filter((stage) => stage.title);
    return { stages };
  }
  if (step === "capabilities") return { capabilities: text.split(/\r?\n/).map((line) => { const [id, reason] = line.split("｜"); return { id: id?.trim(), reason: reason?.trim() || "教师直接配置" }; }).filter((item) => item.id) };
  return {};
}

export function LessonDesignPanel({ projectId, activeLesson, onFinalized, onClose }: Props) {
  const [design, setDesign] = useState<LessonDesignSession | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Array<{ role: "assistant" | "teacher"; text: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastReport, setLastReport] = useState<Record<string, unknown> | null>(null);
  const [titleDraft, setTitleDraft] = useState("");
  const [sectionDraft, setSectionDraft] = useState("");

  useEffect(() => {
    let cancelled = false;
    setBusy(true); setError("");
    createLessonDesign(projectId, activeLesson?.lesson_id || "", { topic: activeLesson?.title || "", grade: activeLesson?.grade || "" })
      .then((payload) => {
        if (cancelled) return;
        setDesign(payload); setTitleDraft(payload.draft?.title || payload.draft?.topic || "");
        setSectionDraft(formatStep(payload.current_step, payload.draft || {}, payload.capability_bindings || []));
        const history = (payload.turns || []).flatMap((turn) => [{ role: "teacher" as const, text: turn.message }, { role: "assistant" as const, text: turn.reply }]);
        setMessages(history.length ? history : [{ role: "assistant", text: "我们开始共创这节课。先告诉我年级、课题、课时和学生情况；我每轮只推进一个关键问题。" }]);
      }).catch((exc) => setError(exc instanceof Error ? exc.message : String(exc))).finally(() => setBusy(false));
    return () => { cancelled = true; };
  }, [activeLesson?.grade, activeLesson?.lesson_id, activeLesson?.title, projectId]);

  const currentStep = design?.current_step || "requirements";
  const currentLabel = STEPS.find(([key]) => key === currentStep)?.[1] || "教学需求";
  const draft = design?.draft || {};
  const confirmedCount = useMemo(() => Object.values(design?.section_status || {}).filter((status) => status === "confirmed").length, [design?.section_status]);
  function applyDesign(next: LessonDesignSession) { setDesign(next); setTitleDraft(next.draft?.title || next.draft?.topic || ""); setSectionDraft(formatStep(next.current_step, next.draft || {}, next.capability_bindings || [])); }

  async function sendText(value: string) {
    if (!design || !value.trim() || busy) return;
    const text = value.trim(); setMessages((previous) => [...previous, { role: "teacher", text }]); setBusy(true); setError("");
    try {
      const result = await turnLessonDesign(design.design_id, text, design.revision, design.current_step);
      const next = { ...design, draft: result.draft, section_status: result.section_status, source_refs: result.source_refs, capability_bindings: result.capability_bindings, current_step: result.next_step, revision: result.revision, diff_summary: result.diff_summary || design.diff_summary };
      applyDesign(next); setMessages((previous) => [...previous, { role: "assistant", text: result.assistant_message }]);
      if (result.rehearsal_report) setLastReport(result.rehearsal_report); setInput("");
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); } finally { setBusy(false); }
  }
  async function resolve(decision: "accept" | "revise") {
    if (!design) return;
    if (decision === "revise") { await sendText(`修改要求：${input.trim() || "请换一种更适合当前教学需求的设计"}`); return; }
    setBusy(true); setError("");
    try { const result = await resolveLessonDesignSection(design.design_id, design.current_step, "accept", "", design.revision); applyDesign(result.design); setMessages((previous) => [...previous, { role: "assistant", text: result.design.current_step === "rehearsal" ? "前面章节已确认，现在运行一次完整预演检查。" : "这一部分已确认，我们继续下一步。" }]); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); } finally { setBusy(false); }
  }
  async function directEdit(sectionId: string, value: unknown) {
    if (!design) return; setBusy(true); setError("");
    try { const result = await resolveLessonDesignSection(design.design_id, sectionId, "edit", "", design.revision, value); applyDesign(result.design); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); } finally { setBusy(false); }
  }
  async function finalize() {
    if (!design) return; setBusy(true); setError("");
    try { const result = await finalizeLessonDesign(design.design_id, design.revision); onFinalized(result.lesson); applyDesign(result.design); setLastReport(result.capability_report); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); } finally { setBusy(false); }
  }
  async function exportDocx() {
    if (!design?.final_lesson_id) return; setBusy(true); setError("");
    try { const result = await exportLessonDocx(design.final_lesson_id, projectId, design.design_id); const url = result.artifact.metadata?.public_url; if (typeof url === "string") window.open(url, "_blank", "noopener,noreferrer"); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); } finally { setBusy(false); }
  }

  return <section className="lesson-design-panel glass-panel" data-testid="lesson-design-panel">
    <header className="lesson-design-header"><div><p className="panel-tag">Lesson Co-creation</p><h2>教案共创助手</h2><p>{draftSummary(draft)} · 已确认 {confirmedCount} 项</p></div><button type="button" className="mini-control" onClick={onClose} aria-label="关闭教案共创">×</button></header>
    <nav className="lesson-design-steps" aria-label="教案共创步骤">{STEPS.map(([key, label], index) => <div key={key} className={`lesson-design-step ${key === currentStep ? "current " : ""}`}><span>{index + 1}</span><em>{label}</em></div>)}</nav>
    <div className="lesson-design-draft"><div className="lesson-design-draft-title">当前讨论：{currentLabel}</div>
      <label>课题<span className="lesson-design-inline-edit"><input value={titleDraft} onChange={(event) => setTitleDraft(event.target.value)} aria-label="当前课题" /><button type="button" className="toolbar-button compact" disabled={busy || !titleDraft.trim() || !design} onClick={() => void directEdit("title", titleDraft.trim())}>直接保存</button></span></label>
      <label>年级<input value={draft.grade || ""} onChange={(event) => setDesign((previous) => previous ? { ...previous, draft: { ...previous.draft, grade: event.target.value } } : previous)} onBlur={(event) => { if (event.target.value.trim()) void directEdit("grade", event.target.value.trim()); }} aria-label="当前年级" /></label>
      {EDITABLE_STEPS.includes(currentStep) ? <label className="lesson-design-section-editor">直接编辑当前部分<textarea value={sectionDraft} onChange={(event) => setSectionDraft(event.target.value)} aria-label="直接编辑当前部分" /><button type="button" className="toolbar-button compact" disabled={busy || !sectionDraft.trim()} onClick={() => void directEdit(currentStep, parseStep(currentStep, sectionDraft, draft))}>保存本节编辑</button></label> : null}
      {design?.diff_summary?.length ? <div><strong>相对原课时的变化</strong><p>{design.diff_summary.map((item) => item.label).join("、")}</p></div> : null}
      {design?.capability_bindings?.length ? <div><strong>已匹配能力</strong><p>{design.capability_bindings.map((item) => item.label || item.id).join("、")}</p></div> : null}
      {design?.source_refs?.length ? <div><strong>实际引用资料</strong><p>{design.source_refs.map((item) => String(item.title || item.id || "资料")).join("、")}</p></div> : null}
    </div>
    <div className="lesson-design-chat" aria-live="polite">{messages.map((message, index) => <div key={`${message.role}-${index}`} className={`lesson-design-message ${message.role}`}><span>{message.role === "assistant" ? "助手" : "教师"}</span><p>{message.text}</p></div>)}</div>
    {lastReport ? <div className="lesson-design-report"><strong>预演结果</strong><span>{String(lastReport.ready ? "结构已通过" : "仍需补充")}</span>{Array.isArray(lastReport.errors) && lastReport.errors.length ? <small>{lastReport.errors.join("；")}</small> : null}{Array.isArray(lastReport.warnings) && lastReport.warnings.length ? <small>{lastReport.warnings.join("；")}</small> : null}</div> : null}
    {error ? <p className="lesson-design-error">{error}</p> : null}
    <div className="lesson-design-composer"><textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void sendText(input); } }} placeholder="告诉我你的修改想法；Ctrl/⌘ + Enter 发送" disabled={busy} /><div className="lesson-design-actions">
      <button type="button" className="toolbar-button compact" disabled={busy || !design} onClick={() => void sendText("返回上一步，重新讨论上一部分")}>返回上一步</button><button type="button" className="toolbar-button compact" disabled={busy || !design} onClick={() => void sendText("请换一种设计，并说明调整理由")}>换一种设计</button><button type="button" className="toolbar-button compact" disabled={busy || !design} onClick={() => void resolve("revise")}>按要求修改</button><button type="button" className="toolbar-button compact" disabled={busy || !design || !EDITABLE_STEPS.includes(currentStep)} onClick={() => void resolve("accept")}>接受本节</button><button type="button" className="toolbar-button compact primary" disabled={busy || !input.trim()} onClick={() => void sendText(input)}>发送</button>
      {currentStep === "rehearsal" ? <button type="button" className="toolbar-button compact primary" disabled={busy} onClick={() => void sendText("请运行完整预演检查")}>运行预演</button> : null}{currentStep === "confirmation" ? <button type="button" className="toolbar-button compact primary" disabled={busy || !design} onClick={() => void finalize()}>确认保存</button> : null}{design?.final_lesson_id ? <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => void exportDocx()}>导出 Word</button> : null}
    </div></div>
  </section>;
}
