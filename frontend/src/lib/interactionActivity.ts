import type { JobRecord } from "../types";

/** The same actual backend activity drives the panel and the map overlay. */
export function interactionActivityLabel(job: JobRecord | null): string {
  if (job?.activity?.label) return job.activity.label;
  const running = Object.entries(job?.stages || {}).find(([, stage]) => stage.status === "running");
  const labels: Record<string, string> = { routing: "正在理解请求", planning: "智能体思考中", execution: "正在执行操作", grounding: "正在核对结果", confirmation: "等待确认", retrieval: "正在检索资料", artifacts: "正在整理结果" };
  return running ? labels[running[0]] || "正在处理请求" : "正在处理请求";
}
