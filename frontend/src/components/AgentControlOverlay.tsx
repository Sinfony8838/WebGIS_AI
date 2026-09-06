import { useEffect, useState } from "react";
import "../agentControlOverlay.css";

/**
 * 全屏「智能交互中」光晕层（模仿 Codex 电脑操控观感）。
 *
 * 交互模式执行操控期间：屏幕四周蓝色呼吸辉光 + 顶部居中胶囊徽标。
 * 三态徽标：listening（常开聆听中，含实时转写灰字）→ captured（已捕获
 * 指令，短暂显示剥离唤醒词后的指令）→ working（执行中，副文案取当前
 * 阶段 summary）。ui_action 到达瞬间叠加一次短促脉冲高亮。
 *
 * 纯展示组件：pointer-events:none，不拦截任何交互；淡出由父组件控制
 * （active=false 后保留 ~1s 的 fade-out）。
 */
export type AgentOverlayState = "idle" | "listening" | "captured" | "working";

export type AgentControlOverlayProps = {
  /** 交互模式的 job 正在执行（busy）时为 true。 */
  active: boolean;
  /** 常开聆听开启且麦克风连接正常时为 true（显示聆听态徽标）。 */
  listening: boolean;
  /** 实时 partial 转写（来自本地 ASR 流）。 */
  partialTranscript: string;
  /** 已通过门控的指令文本，显示 ~1.2s。 */
  capturedCommand: string;
  /** 执行中阶段的当前动作（SSE stages 的 running summary）。 */
  workingDetail: string;
  /** 收到 ui_action 时短暂置 true，触发一次脉冲高亮。 */
  pulseSignal: number;
};

const STATE_LABEL: Record<AgentOverlayState, string> = {
  idle: "",
  listening: "聆听中",
  captured: "已捕获指令",
  working: "智能交互中",
};

export function AgentControlOverlay({
  active,
  listening,
  partialTranscript,
  capturedCommand,
  workingDetail,
  pulseSignal,
}: AgentControlOverlayProps) {
  const [visible, setVisible] = useState(false);
  const [pulse, setPulse] = useState(false);

  // 淡出：active/listening 变 false 后再挂 ~1s 的渐隐。
  useEffect(() => {
    if (active || listening) {
      setVisible(true);
      return;
    }
    if (!visible) {
      return;
    }
    const timer = window.setTimeout(() => setVisible(false), 1000);
    return () => window.clearTimeout(timer);
  }, [active, listening, visible]);

  // ui_action 脉冲：signal 每次自增触发一次 0.6s 高亮。
  useEffect(() => {
    if (pulseSignal <= 0) {
      return;
    }
    setPulse(true);
    const timer = window.setTimeout(() => setPulse(false), 600);
    return () => window.clearTimeout(timer);
  }, [pulseSignal]);

  if (!visible) {
    return null;
  }

  const state: AgentOverlayState = active ? "working" : listening ? (capturedCommand ? "captured" : "listening") : "idle";
  const badgeText = STATE_LABEL[state] || "智能交互中";
  const detail = active
    ? workingDetail || "正在执行指令…"
    : state === "captured"
      ? `“${capturedCommand}”`
      : state === "listening"
        ? partialTranscript || "说出“小智 + 指令”"
        : "";

  return (
    <div
      className={`agent-control-overlay${active ? " working" : ""}${listening && !active ? " listening" : ""}${pulse ? " pulse" : ""}`}
      data-testid="agent-control-overlay"
      aria-hidden="true"
    >
      <div className="agent-control-glow" />
      <div className="agent-control-badge" data-state={state}>
        <span className="agent-control-dot" />
        <span className="agent-control-badge-text">{badgeText}</span>
        {detail ? <span className="agent-control-detail">{detail}</span> : null}
      </div>
    </div>
  );
}

export default AgentControlOverlay;
