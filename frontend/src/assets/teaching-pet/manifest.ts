/**
 * Teaching pet asset manifest.
 *
 * This file is the single source of truth for pose IDs, asset paths and
 * accessibility labels. Business logic lives in `teachingPetState.ts`; the
 * component only reads from this manifest.
 *
 * NOTE: The current assets are SVG placeholders. Replace them with the
 * production WebP/PNG frames delivered by design without touching the code.
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
  src: string;
  alt: string;
};

function poseUrl(name: string): string {
  // Vite resolves `new URL(..., import.meta.url)` to the final asset URL.
  return new URL(`./${name}.svg`, import.meta.url).href;
}

export const PET_POSES: PetPose[] = [
  { id: "idle", src: poseUrl("idle"), alt: "平静待命" },
  { id: "wave", src: poseUrl("wave"), alt: "挥手" },
  { id: "tablet", src: poseUrl("tablet"), alt: "平板规划" },
  { id: "map", src: poseUrl("map"), alt: "看地图" },
  { id: "search", src: poseUrl("search"), alt: "检索" },
  { id: "laptop", src: poseUrl("laptop"), alt: "使用电脑" },
  { id: "sleep", src: poseUrl("sleep"), alt: "睡眠" },
  { id: "success", src: poseUrl("success"), alt: "完成" },
  { id: "think", src: poseUrl("think"), alt: "思考" },
  { id: "confirm", src: poseUrl("confirm"), alt: "待确认" },
  { id: "idea", src: poseUrl("idea"), alt: "灵感" },
  { id: "explain", src: poseUrl("explain"), alt: "讲解" },
  { id: "turn", src: poseUrl("turn"), alt: "转身" },
  { id: "error", src: poseUrl("error"), alt: "沮丧" },
  { id: "celebrate", src: poseUrl("celebrate"), alt: "庆祝" }
];

const POSE_BY_ID: Record<PetPoseId, PetPose> = Object.fromEntries(
  PET_POSES.map((pose) => [pose.id, pose])
) as Record<PetPoseId, PetPose>;

export function getPoseById(id: PetPoseId): PetPose {
  return POSE_BY_ID[id];
}
