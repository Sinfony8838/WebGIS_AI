import type {AssistantExecution} from "../types";
import {ThinkingIndicator} from "./ThinkingIndicator";
import {interactionActivityLabel} from "../lib/interactionActivity";

/** Public execution events, not generated reasoning or a simulated timer sequence. */
export function AssistantActivity({job,busy}:{job:AssistantExecution|null;busy:boolean}) {
  if(!job && !busy)return null;
  const events=job?.activity?.timeline || [];
  const label=interactionActivityLabel(job as Parameters<typeof interactionActivityLabel>[0]);
  const terminal=job?.status==="failed" || job?.status==="completed";
  const running=busy && !terminal;
  if(!running && !events.length && !job?.usage)return null;
  const seconds=Math.max(0,Math.round((job?.usage?.elapsed_ms || 0)/1000));
  const elapsed=seconds>=60?`${Math.floor(seconds/60)}m ${seconds%60}s`:`${seconds}s`;
  return <section className="assistant-activity" aria-label="执行过程">
    <details key={job?.job_id || "pending"}>
      <summary>{running?<ThinkingIndicator label={label}/>:<span className="assistant-activity-finished">用时 {job?.usage?elapsed:"未知"}</span>}<span className="assistant-activity-chevron" aria-hidden="true">›</span></summary>
      <ol>{events.map((event,index)=><li key={index} data-phase={event.phase}>
        <span aria-hidden="true">{event.tool?"⌘":"·"}</span><div><span>{event.label}</span>
        {event.ended_ms!==undefined && <small>持续 {Math.max(0,(event.ended_ms-event.started_ms)/1000).toFixed(1)} 秒</small>}
        </div>
      </li>)}</ol>
      {job?.status==="failed" && <p>本次任务未完成；已停止等待。</p>}
    </details>
  </section>;
}
