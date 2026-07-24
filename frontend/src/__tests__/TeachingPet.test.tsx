import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TeachingPet } from "../components/TeachingPet";
import { resolveTeachingPetPose } from "../components/teachingPetState";

describe("resolveTeachingPetPose", () => {
  it("maps live teaching stages to purposeful poses", () => {
    expect(resolveTeachingPetPose({ busy: true, requiresConfirmation: false, stages: { retrieval: { status: "running" } } })).toBe("study");
    expect(resolveTeachingPetPose({ busy: true, requiresConfirmation: false, stages: { execution: { status: "running" } } })).toBe("execute");
    expect(resolveTeachingPetPose({ busy: false, requiresConfirmation: true })).toBe("alert");
    expect(resolveTeachingPetPose({ busy: false, requiresConfirmation: false })).toBe("idle");
  });
});

describe("TeachingPet", () => {
  it("welcomes once after restoring the assistant and returns to idle", () => {
    vi.useFakeTimers();
    const { rerender } = render(<TeachingPet busy={false} requiresConfirmation={false} variant="orb" welcomeToken={0} />);
    expect(screen.getByTestId("teaching-pet")).toHaveAttribute("data-pose", "idle");
    rerender(<TeachingPet busy={false} requiresConfirmation={false} variant="orb" welcomeToken={1} />);
    expect(screen.getByTestId("teaching-pet")).toHaveAttribute("data-pose", "wave");
    act(() => vi.advanceTimersByTime(1400));
    expect(screen.getByTestId("teaching-pet")).toHaveAttribute("data-pose", "idle");
    vi.useRealTimers();
  });
});
