import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QgisProfessionalPage } from "../components/QgisProfessionalPage";
import {
  buildQgisPreviewUrl,
  executeQgisTool,
  fetchLlmStatus,
  fetchQgisLayers,
  fetchQgisStatus,
  focusQgis
} from "../api";

vi.mock("../api", () => ({
  buildQgisPreviewUrl: vi.fn().mockReturnValue("http://preview.test/qgis_export_map.png"),
  fetchLlmStatus: vi.fn().mockResolvedValue({
    status: "success",
    enabled: false,
    configured: false,
    provider: "minimax",
    model: "MiniMax-M2.5"
  }),
  fetchQgisStatus: vi.fn().mockResolvedValue({
    status: "success",
    enabled: true,
    host: "127.0.0.1",
    port: 5555,
    reachable: false
  }),
  fetchQgisLayers: vi.fn().mockResolvedValue({
    status: "success",
    result: { data: [] }
  }),
  executeQgisTool: vi.fn().mockResolvedValue({
    status: "success",
    result: { status: "success" }
  }),
  focusQgis: vi.fn().mockResolvedValue({
    status: "success",
    ok: true,
    message: "focused"
  })
}));

describe("QgisProfessionalPage", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows compact header status and centered projection section", async () => {
    render(
      <QgisProfessionalPage
        projectId="p1"
        chatLog={[]}
        currentJob={null}
        assistantInput=""
        onAssistantInputChange={() => undefined}
        onSubmitAssistant={() => undefined}
        onBackToClassroom={() => undefined}
        busy={false}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("QGIS专业制图")).toBeInTheDocument();
    });
    expect(screen.getByText("QGIS：未连接")).toBeInTheDocument();
    expect(screen.getByText("MiniMax：未启用")).toBeInTheDocument();
    expect(screen.getByText("操作中心投射")).toBeInTheDocument();
  });

  it("disables core tool buttons when qgis is disconnected", async () => {
    render(
      <QgisProfessionalPage
        projectId="p1"
        chatLog={[]}
        currentJob={null}
        assistantInput=""
        onAssistantInputChange={() => undefined}
        onSubmitAssistant={() => undefined}
        onBackToClassroom={() => undefined}
        busy={false}
      />
    );

    await waitFor(() => {
      expect(fetchQgisStatus).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByRole("button", { name: "读取图层" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "显示图层" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "隐藏图层" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "导出地图" })).toBeDisabled();
  });

  it("does not render minimax long warning prompt", async () => {
    vi.mocked(fetchLlmStatus).mockResolvedValueOnce({
      status: "success",
      enabled: false,
      configured: false,
      provider: "minimax",
      model: "MiniMax-M2.5",
      error: "未检测到 MiniMax API Key，请设置 WEBGIS_AI_MINIMAX_API_KEY 并重启后端。"
    });

    render(
      <QgisProfessionalPage
        projectId="p1"
        chatLog={[]}
        currentJob={null}
        assistantInput=""
        onAssistantInputChange={() => undefined}
        onSubmitAssistant={() => undefined}
        onBackToClassroom={() => undefined}
        busy={false}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("MiniMax：未启用")).toBeInTheDocument();
    });
    expect(screen.queryByText(/WEBGIS_AI_MINIMAX_API_KEY/)).not.toBeInTheDocument();
  });

  it("sends assistant message with qgis target", async () => {
    const onSubmitAssistant = vi.fn();

    render(
      <QgisProfessionalPage
        projectId="p1"
        chatLog={[]}
        currentJob={null}
        assistantInput="读取图层并缩放到活动图层"
        onAssistantInputChange={() => undefined}
        onSubmitAssistant={onSubmitAssistant}
        onBackToClassroom={() => undefined}
        busy={false}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "发送到 QGIS 助教" }));
    expect(onSubmitAssistant).toHaveBeenCalledWith("读取图层并缩放到活动图层", "qgis");
  });

  it("keeps API contracts wired", async () => {
    render(
      <QgisProfessionalPage
        projectId="p1"
        chatLog={[]}
        currentJob={null}
        assistantInput=""
        onAssistantInputChange={() => undefined}
        onSubmitAssistant={() => undefined}
        onBackToClassroom={() => undefined}
        busy={false}
      />
    );

    await waitFor(() => {
      expect(fetchLlmStatus).toHaveBeenCalled();
      expect(fetchQgisStatus).toHaveBeenCalled();
      expect(fetchQgisLayers).toHaveBeenCalled();
    });

    expect(buildQgisPreviewUrl).toHaveBeenCalled();
    expect(executeQgisTool).toHaveBeenCalledTimes(0);
    expect(focusQgis).toHaveBeenCalledTimes(0);
  });
});
