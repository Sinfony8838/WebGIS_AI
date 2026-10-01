import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LessonProcessTable } from "../components/LessonProcessTable";
import type { LessonPlanProfile } from "../types";

vi.mock("../api", () => ({
  buildAuthenticatedUrl: (path: string) => path,
  uploadVideoAsset: vi.fn(),
  uploadImageLibraryAsset: vi.fn()
}));

const draft = {
  title: "人口分布",
  stages: [
    {
      stage_id: "s1",
      title: "情境导入",
      minutes: 5,
      kind: "presentation",
      scene: {},
      questions: [],
      knowledge_conclusion: "人口分布不均",
      student_activities: ["读图"]
    }
  ]
} as unknown as LessonPlanProfile;

function renderTable(overrides: Partial<Parameters<typeof LessonProcessTable>[0]> = {}) {
  const props = {
    draft,
    busy: false,
    projectId: "p1",
    libraryAssets: [],
    searchResults: [],
    searchText: "",
    onStageFieldChange: vi.fn(),
    onAddStage: vi.fn(),
    onRemoveStage: vi.fn(),
    onRemoveQuestion: vi.fn(),
    onBindSearchResult: vi.fn(),
    onBindManual: vi.fn(),
    onSearchText: vi.fn(),
    onRunSearch: vi.fn(),
    onStageAiEdit: vi.fn(),
    onCaptureScene: () => ({ basemap_id: "base_osm", view: { center: [121.4, 31.2], zoom: 9 } }),
    ...overrides
  };
  render(<LessonProcessTable {...props} />);
  return props;
}

afterEach(cleanup);

describe("LessonProcessTable 环节素材入口", () => {
  it("binds the current map scene into the stage via the material entry", () => {
    const props = renderTable();
    fireEvent.click(screen.getByTestId("lpt-bind-scene-0"));
    expect(props.onStageFieldChange).toHaveBeenCalledWith(0, "scene", {
      basemap_id: "base_osm",
      view: { center: [121.4, 31.2], zoom: 9 }
    });
    expect(screen.getByRole("status")).toHaveTextContent("已把当前地图场景绑定到本环节。");
  });

  it("opens the shared presentation layout editor and saves materials into the stage", () => {
    const props = renderTable();
    fireEvent.click(screen.getByText(/本环节素材/));
    expect(screen.getByTestId("ple-s1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "插入文字区块" }));
    fireEvent.click(screen.getByTestId("ple-save"));
    expect(props.onStageFieldChange).toHaveBeenCalledWith(0, "presentation", expect.objectContaining({ blocks: expect.any(Array) }));
  });

  it("reports when no scene can be captured", () => {
    renderTable({ onCaptureScene: () => null });
    fireEvent.click(screen.getByTestId("lpt-bind-scene-0"));
    expect(screen.getByRole("status")).toHaveTextContent("当前没有可绑定的地图场景。");
  });
});
