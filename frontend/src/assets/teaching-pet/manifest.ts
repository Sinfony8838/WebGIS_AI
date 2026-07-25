/**
 * Teaching pet asset manifest.
 *
 * This file maps state IDs to cells in the user-supplied PNG sprite sheet.
 * The artwork itself is never reconstructed or synthesized by the UI.
 */

export type PetPoseId =
  | "idle"
  | "wave"
  | "tablet"
  | "map"
  | "search"
  | "laptop"
  | "sleep"
  | "success"
  | "think"
  | "confirm"
  | "idea"
  | "explain"
  | "turn"
  | "error"
  | "celebrate";

export type PetPose = {
  id: PetPoseId;
  column: number;
  row: number;
  alt: string;
};

export const PET_POSES: PetPose[] = [
  { id: "idle", column: 0, row: 0, alt: "平静待命" },
  { id: "wave", column: 1, row: 0, alt: "挥手" },
  { id: "tablet", column: 2, row: 0, alt: "平板规划" },
  { id: "map", column: 3, row: 0, alt: "看地图" },
  { id: "search", column: 4, row: 0, alt: "检索" },
  { id: "laptop", column: 0, row: 1, alt: "使用电脑" },
  { id: "sleep", column: 1, row: 1, alt: "睡眠" },
  { id: "success", column: 2, row: 1, alt: "完成" },
  { id: "think", column: 3, row: 1, alt: "思考" },
  { id: "confirm", column: 4, row: 1, alt: "待确认" },
  { id: "idea", column: 0, row: 2, alt: "灵感" },
  { id: "explain", column: 1, row: 2, alt: "讲解" },
  { id: "turn", column: 2, row: 2, alt: "转身" },
  { id: "error", column: 3, row: 2, alt: "沮丧" },
  { id: "celebrate", column: 4, row: 2, alt: "庆祝" }
];

const POSE_BY_ID: Record<PetPoseId, PetPose> = Object.fromEntries(
  PET_POSES.map((pose) => [pose.id, pose])
) as Record<PetPoseId, PetPose>;

export function getPoseById(id: PetPoseId): PetPose {
  return POSE_BY_ID[id];
}
