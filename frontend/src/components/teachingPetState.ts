export type TeachingPetPose =
  | "idle"
  | "wave"
  | "plan"
  | "map"
  | "inspect"
  | "execute"
  | "rest"
  | "success"
  | "think"
  | "alert"
  | "idea"
  | "study"
  | "back"
  | "sad"
  | "celebrate";

export type TeachingPetStage = { status: string };

export type TeachingPetStateInput = {
  busy: boolean;
  requiresConfirmation: boolean;
  stages?: Record<string, TeachingPetStage>;
  welcoming?: boolean;
};

export const TEACHING_PET_POSES: Record<TeachingPetPose, { column: number; row: number; label: string }> = {
  idle: { column: 0, row: 0, label: "待命" },
  wave: { column: 1, row: 0, label: "欢迎" },
  plan: { column: 2, row: 0, label: "整理教学步骤" },
  map: { column: 3, row: 0, label: "查看地图证据" },
  inspect: { column: 4, row: 0, label: "核查细节" },
  execute: { column: 0, row: 1, label: "执行教学操作" },
  rest: { column: 1, row: 1, label: "休息" },
  success: { column: 2, row: 1, label: "完成" },
  think: { column: 3, row: 1, label: "思考" },
  alert: { column: 4, row: 1, label: "等待教师确认" },
  idea: { column: 0, row: 2, label: "形成教学提示" },
  study: { column: 1, row: 2, label: "查阅教学资料" },
  back: { column: 2, row: 2, label: "暂不打扰" },
  sad: { column: 3, row: 2, label: "需要更多信息" },
  celebrate: { column: 4, row: 2, label: "鼓励" }
};

const STAGE_POSES: Record<string, TeachingPetPose> = {
  routing: "think",
  analysis: "think",
  retrieval: "study",
  grounding: "study",
  artifacts: "study",
  planning: "plan",
  confirmation: "alert",
  execution: "execute",
  actions: "execute",
  map: "map"
};

/** Maps the existing teaching workflow state to a small, legible pet pose. */
export function resolveTeachingPetPose({ busy, requiresConfirmation, stages = {}, welcoming = false }: TeachingPetStateInput): TeachingPetPose {
  if (requiresConfirmation) return "alert";
  if (busy) {
    const runningStage = Object.entries(stages).find(([, stage]) => stage.status === "running")?.[0];
    return (runningStage && STAGE_POSES[runningStage]) || "think";
  }
  return welcoming ? "wave" : "idle";
}
