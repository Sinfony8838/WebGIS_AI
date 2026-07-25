import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { TeachingPet } from "../components/TeachingPet";
import type { JobRecord } from "../types";

function makeJob(overrides: Partial<JobRecord> = {}): JobRecord {
  return {
    job_id: "job_1",
    project_id: "project_1",
    job_type: "assistant",
    title: "测试任务",
    workflow_type: "assistant_message",
    status: "running",
    updated_at: "1",
    steps: [],
    stages: {},
    ...overrides
  };
}

describe("TeachingPet", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  function renderPet(
    props: Partial<React.ComponentProps<typeof TeachingPet>> = {},
    size: "header" | "orb" = "header"
  ) {
    return render(
      <TeachingPet
        busy={false}
        currentJob={null}
        minimized={false}
        isListening={false}
        size={size}
        hasWelcomed={true}
        {...props}
      />
    );
  }

  it("renders the header and orb variants", () => {
    const { rerender } = renderPet({}, "header");
    const headerPet = screen.getByTestId("teaching-pet-header");
    expect(headerPet).toBeInTheDocument();
    expect(headerPet.tagName).toBe("SPAN");
    expect(headerPet).not.toHaveAttribute("src");
    expect(headerPet.style.backgroundImage).toContain("cloud-teacher-sprite.png");

    rerender(
      <TeachingPet
        busy={false}
        currentJob={null}
        minimized={false}
        isListening={false}
        size="orb"
        hasWelcomed={true}
      />
    );
    expect(screen.getByTestId("teaching-pet-orb")).toBeInTheDocument();
  });

  it("maps routing / planning / execution / confirmation / error stages to poses", () => {
    const stages: Array<[string, string]> = [
      ["routing", "search"],
      ["planning", "tablet"],
      ["grounding", "explain"],
      ["confirmation", "confirm"]
    ];

    for (const [stage, expectedPose] of stages) {
      const { unmount } = renderPet({
        busy: true,
        currentJob: makeJob({
          stages: { [stage]: { status: "running", summary: "", detail: "" } }
        })
      });
      vi.advanceTimersByTime(500);
      expect(screen.getByTestId("teaching-pet-header")).toHaveAttribute("data-pose", expectedPose);
      unmount();
    }
  });

  it("prefers map pose when execution stage involves map context", () => {
    renderPet({
      busy: true,
      currentJob: makeJob({
        stages: { execution: { status: "running", summary: "", detail: "" } },
        result: {
          actions_planned: [
            {
              name: "fly_to",
              target: "map",
              category: "map",
              risk_level: "low",
              reversible: true,
              requires_confirmation: false,
              requires_map_context: true,
              tool_params: {}
            }
          ]
        }
      })
    });

    vi.advanceTimersByTime(500);
    expect(screen.getByTestId("teaching-pet-header")).toHaveAttribute("data-pose", "map");
  });

  it("falls back to laptop pose for general execution", () => {
    renderPet({
      busy: true,
      currentJob: makeJob({
        stages: { execution: { status: "running", summary: "", detail: "" } },
        result: {
          actions_planned: [
            {
              name: "answer",
              target: "chat",
              category: "knowledge",
              risk_level: "low",
              reversible: true,
              requires_confirmation: false,
              requires_map_context: false,
              tool_params: {}
            }
          ]
        }
      })
    });

    vi.advanceTimersByTime(500);
    expect(screen.getByTestId("teaching-pet-header")).toHaveAttribute("data-pose", "laptop");
  });

  it("gives confirmation higher priority than busy execution", () => {
    renderPet({
      busy: true,
      currentJob: makeJob({
        stages: { execution: { status: "running", summary: "", detail: "" } },
        result: {
          requires_confirmation: true,
          confirmation_id: "confirm_1",
          actions_planned: [
            {
              name: "fly_to",
              target: "map",
              category: "map",
              risk_level: "high",
              reversible: true,
              requires_confirmation: true,
              requires_map_context: true,
              tool_params: {}
            }
          ]
        }
      })
    });

    vi.advanceTimersByTime(500);

    expect(screen.getByTestId("teaching-pet-header")).toHaveAttribute("data-pose", "confirm");
  });

  it("shows success feedback after busy finishes and clears after a timeout", async () => {
    const { rerender } = renderPet({
      busy: true,
      currentJob: makeJob({
        stages: { retrieval: { status: "running", summary: "", detail: "" } }
      })
    });

    rerender(
      <TeachingPet
        busy={false}
        currentJob={makeJob({ status: "completed", stages: {} })}
        minimized={false}
        isListening={false}
        size="header"
        hasWelcomed={true}
      />
    );

    expect(screen.getByTestId("teaching-pet-header")).toHaveAttribute("data-pose", "success");

    vi.advanceTimersByTime(2000);

    await waitFor(() => {
      expect(screen.getByTestId("teaching-pet-header")).toHaveAttribute("data-pose", "idle");
    });
  });

  it("shows error feedback when currentJob.error appears and holds longer than success", async () => {
    renderPet({
      busy: false,
      currentJob: makeJob({ status: "failed", error: "something went wrong", stages: {} })
    });

    expect(screen.getByTestId("teaching-pet-header")).toHaveAttribute("data-pose", "error");

    vi.advanceTimersByTime(2000);
    // Error hold is 3s, so it should still be error at 2s.
    expect(screen.getByTestId("teaching-pet-header")).toHaveAttribute("data-pose", "error");

    // After the 3s error hold it falls back to idle immediately.
    vi.advanceTimersByTime(1500);

    await waitFor(() => {
      expect(screen.getByTestId("teaching-pet-header")).toHaveAttribute("data-pose", "idle");
    });
  });

  it("enters sleep only when minimized and idle for 75 seconds", async () => {
    const { rerender } = renderPet({ minimized: true }, "orb");

    expect(screen.getByTestId("teaching-pet-orb")).toHaveAttribute("data-pose", "idle");

    vi.advanceTimersByTime(76000);

    await waitFor(() => {
      expect(screen.getByTestId("teaching-pet-orb")).toHaveAttribute("data-pose", "sleep");
    });

    // Wakes up when activity resumes.
    rerender(
      <TeachingPet
        busy={false}
        currentJob={null}
        minimized={false}
        isListening={false}
        size="orb"
        hasWelcomed={true}
      />
    );

    expect(screen.getByTestId("teaching-pet-orb")).toHaveAttribute("data-pose", "idle");
  });

  it("shows a welcome wave on first expansion", () => {
    renderPet({ minimized: false, hasWelcomed: false });
    expect(screen.getByTestId("teaching-pet-header")).toHaveAttribute("data-pose", "wave");
  });

  it("does not add looping animation classes when reduced motion is preferred", () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn()
    })) as unknown as typeof window.matchMedia;

    renderPet();

    const img = screen.getByTestId("teaching-pet-header");
    expect(img.classList.contains("reduced")).toBe(true);
    expect(img.classList.contains("animated")).toBe(false);
  });

  it("marks the image as decorative and non-draggable", () => {
    renderPet();
    const img = screen.getByTestId("teaching-pet-header");
    expect(img).toHaveAttribute("aria-hidden", "true");
    expect(img).toHaveAttribute("draggable", "false");
  });
});
