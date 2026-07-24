import { useEffect, useRef, useState, type CSSProperties } from "react";
import { resolveTeachingPetPose, TEACHING_PET_POSES, type TeachingPetStage } from "./teachingPetState";

const PET_SPRITE_URL = new URL("../assets/teaching-pet/cloud-teacher-sprite.png", import.meta.url).href;
const WELCOME_DURATION_MS = 1400;

type Props = {
  busy: boolean;
  requiresConfirmation: boolean;
  stages?: Record<string, TeachingPetStage>;
  welcomeToken?: number;
  variant: "orb" | "header";
};

/** Renders a user-supplied cloud-teacher pose from the sprite sheet. */
export function TeachingPet({ busy, requiresConfirmation, stages, welcomeToken = 0, variant }: Props) {
  const observedWelcomeToken = useRef(welcomeToken);
  const [welcoming, setWelcoming] = useState(() => welcomeToken > 0 && !busy && !requiresConfirmation);

  useEffect(() => {
    if (welcomeToken === observedWelcomeToken.current) return;
    observedWelcomeToken.current = welcomeToken;
    if (busy || requiresConfirmation) {
      setWelcoming(false);
      return;
    }
    setWelcoming(true);
    const timeout = window.setTimeout(() => setWelcoming(false), WELCOME_DURATION_MS);
    return () => window.clearTimeout(timeout);
  }, [busy, requiresConfirmation, welcomeToken]);

  const poseId = resolveTeachingPetPose({ busy, requiresConfirmation, stages, welcoming });
  const pose = TEACHING_PET_POSES[poseId];
  const style = {
    backgroundImage: `url("${PET_SPRITE_URL}")`,
    "--pet-column": pose.column,
    "--pet-row": pose.row
  } as CSSProperties;

  return (
    <span
      aria-hidden="true"
      className={`teaching-pet teaching-pet--${variant}${busy ? " is-busy" : ""}`}
      data-pose={poseId}
      data-testid="teaching-pet"
      style={style}
      title={pose.label}
    />
  );
}
