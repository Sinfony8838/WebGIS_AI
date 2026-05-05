import { useCallback, useEffect, useMemo, useState } from "react";
import {
  buildQgisPreviewUrl,
  executeQgisTool,
  fetchLlmStatus,
  fetchQgisLayers,
  fetchQgisStatus,
  focusQgis
} from "../api";
import type {
  AssistantMode,
  AssistantTarget,
  ChatMessage,
  JobRecord,
  LlmStatusResponse,
  QgisStatusResponse
} from "../types";

type QgisLayerItem = {
  id: string;
  name: string;
  visible: boolean;
  kind: string;
};

type Props = {
  projectId: string;
  assistantMode: AssistantMode;
  chatLog: ChatMessage[];
  currentJob: JobRecord | null;
  assistantInput: string;
  onAssistantInputChange: (value: string) => void;
  onAssistantModeChange: (mode: AssistantMode) => void;
  onSubmitAssistant: (message: string, target: AssistantTarget) => void;
  onConfirm: (confirmationId: string, decision?: "approve" | "reject") => void;
  onBackToClassroom: () => void;
  busy: boolean;
};

const DEFAULT_EXPORT_PATH = "C:\\Users\\Public\\qgis_export_map.png";

function toText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (value === null || value === undefined) {
    return "";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function parseLayers(payload: unknown): QgisLayerItem[] {
  let collection: unknown[] = [];
  if (Array.isArray(payload)) {
    collection = payload;
  } else if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    if (Array.isArray(record.layers)) {
      collection = record.layers;
    } else if (Array.isArray(record.data)) {
      collection = record.data;
    } else if (record.data && typeof record.data === "object") {
      const dataRecord = record.data as Record<string, unknown>;
      if (Array.isArray(dataRecord.layers)) {
        collection = dataRecord.layers;
      }
    }
  }

  return collection
    .map((item, index) => {
      if (!item || typeof item !== "object") {
        return null;
      }
      const record = item as Record<string, unknown>;
      const id = String(record.layer_id || record.id || record.name || `layer_${index}`);
      const name = String(record.name || record.layer_name || id);
      const visibleRaw = record.visible;
      const visible =
        typeof visibleRaw === "boolean"
          ? visibleRaw
          : String(visibleRaw ?? "true").trim().toLowerCase() !== "false";
      const kind = String(record.kind || record.type || "layer");
      return { id, name, visible, kind };
    })
    .filter((item): item is QgisLayerItem => Boolean(item));
}

function extractExportPath(result: unknown, fallbackPath: string): string {
  if (!result || typeof result !== "object") {
    return fallbackPath;
  }
  const record = result as Record<string, unknown>;
  const candidates = [
    record.file_path,
    record.path,
    record.output_path,
    record.export_path,
    (record.data as Record<string, unknown> | undefined)?.file_path
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return fallbackPath;
}

export function QgisProfessionalPage({
  projectId,
  assistantMode = "tool",
  chatLog,
  currentJob,
  assistantInput,
  onAssistantInputChange,
  onAssistantModeChange = () => undefined,
  onSubmitAssistant,
  onConfirm = () => undefined,
  onBackToClassroom,
  busy
}: Props) {
  const [llmStatus, setLlmStatus] = useState<LlmStatusResponse | null>(null);
  const [qgisStatus, setQgisStatus] = useState<QgisStatusResponse | null>(null);
  const [layers, setLayers] = useState<QgisLayerItem[]>([]);
  const [selectedLayerId, setSelectedLayerId] = useState("");
  const [exportPath, setExportPath] = useState(DEFAULT_EXPORT_PATH);
  const [projectedPath, setProjectedPath] = useState(DEFAULT_EXPORT_PATH);
  const [previewError, setPreviewError] = useState("");
  const [previewStamp, setPreviewStamp] = useState(() => Date.now());
  const [consoleText, setConsoleText] = useState("准备就绪。");

  const selectedLayer = useMemo(() => layers.find((item) => item.id === selectedLayerId) || null, [layers, selectedLayerId]);
  const qgisConnected = Boolean(qgisStatus?.reachable);
  const llmEnabled = Boolean(llmStatus?.enabled || llmStatus?.configured);
  const llmStatusLabel = llmStatus?.status === "error" ? "状态异常" : llmEnabled ? "已启用" : "未启用";
  const toolDisabledByConnection = !qgisConnected;
  const toolDisabledByLayer = !qgisConnected || !selectedLayer;
  const previewUrl = useMemo(() => buildQgisPreviewUrl(projectedPath, previewStamp), [projectedPath, previewStamp]);
  const citations = currentJob?.result?.citations || currentJob?.result?.knowledge?.citations || [];
  const confirmationId = String(currentJob?.result?.confirmation_id || "");
  const requiresConfirmation = Boolean(currentJob?.result?.requires_confirmation && confirmationId);

  const refreshStatus = useCallback(async () => {
    const [llm, qgis] = await Promise.allSettled([fetchLlmStatus(), fetchQgisStatus()]);
    if (llm.status === "fulfilled") {
      setLlmStatus(llm.value);
    } else {
      setLlmStatus({
        status: "error",
        enabled: false,
        provider: "minimax",
        model: "MiniMax-M2.5",
        error: llm.reason instanceof Error ? llm.reason.message : "LLM status request failed"
      });
    }
    if (qgis.status === "fulfilled") {
      setQgisStatus(qgis.value);
    } else {
      setQgisStatus({
        status: "error",
        enabled: true,
        host: "127.0.0.1",
        port: 5555,
        reachable: false,
        error: qgis.reason instanceof Error ? qgis.reason.message : "QGIS status request failed"
      });
    }
  }, []);

  const refreshLayers = useCallback(async () => {
    try {
      const response = await fetchQgisLayers();
      const parsed = parseLayers(response.result);
      setLayers(parsed);
      if (!selectedLayerId && parsed.length) {
        setSelectedLayerId(parsed[0].id);
      } else if (selectedLayerId && !parsed.some((item) => item.id === selectedLayerId)) {
        setSelectedLayerId(parsed[0]?.id || "");
      }
      setConsoleText(`已读取 QGIS 图层：${parsed.length} 个。`);
    } catch (error) {
      setLayers([]);
      setConsoleText(error instanceof Error ? error.message : "读取 QGIS 图层失败。");
    }
  }, [selectedLayerId]);

  const runTool = useCallback(
    async (toolName: string, toolParams: Record<string, unknown>) => {
      if (!qgisConnected) {
        setConsoleText("QGIS 未连接，请先检测连接。");
        return;
      }
      try {
        const response = await executeQgisTool(toolName, toolParams);
        setConsoleText(toText(response.result || response.message || response));
        if (
          [
            "set_layer_visibility",
            "set_active_layer",
            "set_layer_z_order",
            "add_layer_from_path",
            "export_layer_to_file",
            "create_heatmap",
            "create_flow_arrows"
          ].includes(toolName)
        ) {
          await refreshLayers();
        }
        if (toolName === "export_map") {
          const path = extractExportPath(response.result, exportPath.trim());
          setProjectedPath(path);
          setPreviewStamp(Date.now());
        }
      } catch (error) {
        setConsoleText(error instanceof Error ? error.message : "QGIS 工具执行失败。");
      }
    },
    [exportPath, qgisConnected, refreshLayers]
  );

  useEffect(() => {
    void refreshStatus();
    void refreshLayers();
  }, [refreshLayers, refreshStatus]);

  useEffect(() => {
    if (!currentJob || currentJob.status !== "completed") {
      return;
    }
    const executed = currentJob.result?.actions_executed || [];
    const exportAction = executed.find((item) => item.action?.tool_name === "export_map");
    if (exportAction?.result && typeof exportAction.result === "object") {
      const actionResult = exportAction.result as Record<string, unknown>;
      const qgisResponse =
        actionResult.qgis_response && typeof actionResult.qgis_response === "object"
          ? (actionResult.qgis_response as Record<string, unknown>)
          : undefined;
      const resolvedPath = extractExportPath(qgisResponse || actionResult, projectedPath);
      if (resolvedPath) {
        setProjectedPath(resolvedPath);
      }
    }
    setPreviewStamp(Date.now());
    void refreshLayers();
  }, [currentJob, projectedPath, refreshLayers]);

  return (
    <section className="qgis-page">
      <header className="qgis-page-header qgis-card">
        <div className="qgis-header-main">
          <div className="qgis-header-title">
            <h2>QGIS专业制图</h2>
          </div>
          <div className="qgis-header-status">
            <span className={`qgis-status-chip ${qgisConnected ? "ok" : "warn"}`}>
              QGIS：{qgisConnected ? "已连接" : "未连接"}
            </span>
            <span className="qgis-status-chip">地址：{qgisStatus?.host || "127.0.0.1"}:{qgisStatus?.port || 5555}</span>
            <span className={`qgis-status-chip ${llmEnabled ? "ok" : "dim"}`}>MiniMax：{llmStatusLabel}</span>
          </div>
        </div>
        <div className="qgis-header-actions">
          <button type="button" className="toolbar-button" onClick={onBackToClassroom}>
            返回课堂模式
          </button>
          <button type="button" className="toolbar-button" onClick={() => void refreshStatus()}>
            检测连接
          </button>
          <button type="button" className="toolbar-button" onClick={() => void refreshLayers()} disabled={toolDisabledByConnection}>
            刷新图层
          </button>
          <button
            type="button"
            className="toolbar-button"
            disabled={toolDisabledByConnection}
            onClick={async () => {
              try {
                const response = await focusQgis();
                setConsoleText(toText(response.message || response));
              } catch (error) {
                setConsoleText(error instanceof Error ? error.message : "QGIS 置前失败。");
              }
            }}
          >
            置前 QGIS
          </button>
        </div>
      </header>

      <div className="qgis-grid">
        <section className="qgis-panel qgis-card qgis-panel-tools">
          <h3>核心工具</h3>
          <div className="qgis-tool-grid">
            <button
              type="button"
              className="toolbar-button compact"
              disabled={toolDisabledByConnection}
              onClick={() => void runTool("get_layers", {})}
            >
              读取图层
            </button>
            <button
              type="button"
              className="toolbar-button compact"
              disabled={toolDisabledByLayer}
              onClick={() =>
                selectedLayer &&
                void runTool("set_layer_visibility", {
                  layer_id: selectedLayer.id,
                  layer_name: selectedLayer.name,
                  visible: true
                })
              }
            >
              显示图层
            </button>
            <button
              type="button"
              className="toolbar-button compact"
              disabled={toolDisabledByLayer}
              onClick={() =>
                selectedLayer &&
                void runTool("set_layer_visibility", {
                  layer_id: selectedLayer.id,
                  layer_name: selectedLayer.name,
                  visible: false
                })
              }
            >
              隐藏图层
            </button>
            <button
              type="button"
              className="toolbar-button compact"
              disabled={toolDisabledByLayer}
              onClick={() =>
                selectedLayer &&
                void runTool("set_active_layer", {
                  layer_id: selectedLayer.id,
                  layer_name: selectedLayer.name
                })
              }
            >
              激活图层
            </button>
            <button
              type="button"
              className="toolbar-button compact"
              disabled={toolDisabledByLayer}
              onClick={() =>
                selectedLayer &&
                void runTool("zoom_to_layer", {
                  layer_id: selectedLayer.id,
                  layer_name: selectedLayer.name
                })
              }
            >
              缩放到图层
            </button>
            <button
              type="button"
              className="toolbar-button compact"
              disabled={toolDisabledByLayer}
              onClick={() =>
                selectedLayer &&
                void runTool("create_heatmap", {
                  layer_id: selectedLayer.id,
                  layer_name: selectedLayer.name
                })
              }
            >
              热力图
            </button>
            <button
              type="button"
              className="toolbar-button compact"
              disabled={toolDisabledByLayer}
              onClick={() =>
                selectedLayer &&
                void runTool("create_flow_arrows", {
                  layer_id: selectedLayer.id,
                  layer_name: selectedLayer.name
                })
              }
            >
              流线图
            </button>
            <div className="qgis-export-row">
              <input
                value={exportPath}
                onChange={(event) => setExportPath(event.target.value)}
                placeholder="导出路径（PNG）"
              />
              <button
                type="button"
                className="toolbar-button compact"
                disabled={toolDisabledByConnection || !exportPath.trim()}
                onClick={() => void runTool("export_map", { file_path: exportPath.trim() })}
              >
                导出地图
              </button>
            </div>
          </div>
        </section>

        <section className="qgis-panel qgis-card qgis-panel-center">
          <h3>操作中心投射</h3>
          <div className="qgis-center-stage">
            <img
              src={previewUrl}
              alt="QGIS 操作中心投射图"
              onLoad={() => setPreviewError("")}
              onError={() => setPreviewError("当前未读取到可投射图像，请先执行导出地图。")}
            />
            {previewError ? <p className="qgis-center-hint">{previewError}</p> : null}
          </div>
        </section>

        <section className="qgis-panel qgis-card qgis-panel-layers">
          <h3>QGIS 图层</h3>
          <div className="qgis-layer-list compact">
            {layers.map((layer) => (
              <button
                key={layer.id}
                type="button"
                className={`qgis-layer-item compact ${layer.id === selectedLayerId ? "active" : ""}`}
                onClick={() => setSelectedLayerId(layer.id)}
              >
                <span>{layer.visible ? "显" : "隐"}</span>
                <span>{layer.name}</span>
              </button>
            ))}
            {!layers.length ? <p className="qgis-empty">暂无图层。</p> : null}
          </div>
        </section>

        <section className="qgis-panel qgis-card qgis-panel-assistant">
          <h3>专业助教（目标：QGIS）</h3>
          <div className="assistant-mode-switch qgis-mode-switch" role="tablist" aria-label="assistant mode">
            <button
              type="button"
              className={`toolbar-button compact ${assistantMode === "knowledge" ? "active" : ""}`}
              onClick={() => onAssistantModeChange("knowledge")}
            >
              知识助手
            </button>
            <button
              type="button"
              className={`toolbar-button compact ${assistantMode === "tool" ? "active" : ""}`}
              onClick={() => onAssistantModeChange("tool")}
            >
              工具助手
            </button>
          </div>
          {requiresConfirmation ? (
            <div className="copilot-confirm-card">
              <strong>高风险操作待确认</strong>
              <span>该 QGIS 计划未确认前不会执行。</span>
              <div className="copilot-confirm-actions">
                <button type="button" onClick={() => onConfirm(confirmationId, "approve")} disabled={busy}>
                  确认执行
                </button>
                <button type="button" className="secondary" onClick={() => onConfirm(confirmationId, "reject")} disabled={busy}>
                  拒绝计划
                </button>
              </div>
            </div>
          ) : null}
          <div className="qgis-chat-log">
            {chatLog.slice(-8).map((message) => (
              <article key={`${message.timestamp}_${message.role}`} className={`qgis-chat-item ${message.role}`}>
                <strong>{message.role === "assistant" ? "助教" : message.role === "user" ? "教师" : "系统"}</strong>
                <p>{message.text}</p>
              </article>
            ))}
          </div>
          <div className="qgis-chat-form">
            <textarea
              value={assistantInput}
              onChange={(event) => onAssistantInputChange(event.target.value)}
              placeholder="例如：读取当前图层并隐藏底图，飞到人口迁移图层后导出地图。"
            />
            <button
              type="button"
              disabled={busy || !assistantInput.trim() || !projectId}
              onClick={() => {
                const text = assistantInput.trim();
                if (!text) {
                  return;
                }
                onSubmitAssistant(text, assistantMode === "tool" ? "qgis" : "auto");
              }}
            >
              发送到 QGIS 助教
            </button>
          </div>
          {citations.length ? (
            <div className="copilot-citation-list">
              <strong>引用</strong>
              {citations.map((item) => (
                <a key={`${item.title}_${item.url}`} href={item.url} target="_blank" rel="noreferrer">
                  {item.title}
                </a>
              ))}
            </div>
          ) : null}
          {currentJob ? (
            <p className="qgis-job-hint">
              当前任务：{currentJob.title} / {currentJob.status}
            </p>
          ) : null}
        </section>

        <section className="qgis-panel qgis-card qgis-panel-log">
          <h3>执行日志</h3>
          <pre className="qgis-console">{consoleText}</pre>
        </section>
      </div>
    </section>
  );
}
