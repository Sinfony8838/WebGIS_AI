import type { WorkflowError, WorkflowStatus, WorkflowStepRecord } from "../types";

const STATUS_LABELS: Record<string, string> = {
  pending: "等待执行",
  running: "执行中",
  success: "已完成",
  error: "失败",
  skipped: "已跳过"
};

const STATUS_ICONS: Record<string, string> = {
  pending: "⏳",
  running: "🔄",
  success: "✅",
  error: "❌",
  skipped: "⤵️"
};

export type WorkflowPanelProps = {
  workflowId: string;
  status: WorkflowStatus | "idle";
  intent: string;
  steps: WorkflowStepRecord[];
  error: WorkflowError | null;
  onClear?: () => void;
};

export function WorkflowPanel(props: WorkflowPanelProps): JSX.Element | null {
  const { workflowId, status, intent, steps, error, onClear } = props;

  if (!workflowId) {
    return null;
  }

  return (
    <section className="workflow-panel" data-testid="workflow-panel">
      <header className="workflow-panel__header">
        <div>
          <h3 className="workflow-panel__title">{intent || "GIS 分析工作流"}</h3>
          <p className="workflow-panel__meta">
            <span className={`workflow-panel__status workflow-panel__status--${status}`}>
              {STATUS_ICONS[status] || "ℹ️"} {STATUS_LABELS[status] || status}
            </span>
            <span className="workflow-panel__id">ID: {workflowId}</span>
          </p>
        </div>
        {onClear ? (
          <button type="button" className="workflow-panel__clear" onClick={onClear}>
            清除
          </button>
        ) : null}
      </header>

      <ul className="workflow-panel__steps">
        {steps.map((step) => (
          <li
            key={step.id}
            className={`workflow-panel__step workflow-panel__step--${step.status}`}
          >
            <span className="workflow-panel__step-icon">{STATUS_ICONS[step.status] || "•"}</span>
            <div className="workflow-panel__step-body">
              <div className="workflow-panel__step-headline">
                <strong>{step.id}</strong>
                <span className="workflow-panel__step-op">{step.op}</span>
                <span className="workflow-panel__step-status">
                  {STATUS_LABELS[step.status] || step.status}
                </span>
              </div>
              {step.error ? (
                <p className="workflow-panel__step-error">
                  <span className="workflow-panel__error-code">[{step.error.code}]</span>
                  {step.error.user_friendly || step.error.message}
                </p>
              ) : null}
            </div>
          </li>
        ))}
        {steps.length === 0 ? (
          <li className="workflow-panel__step workflow-panel__step--placeholder">
            等待后台 GIS Worker 调度…
          </li>
        ) : null}
      </ul>

      {error ? (
        <div className="workflow-panel__global-error" role="alert">
          <strong>[{error.code}]</strong> {error.user_friendly || error.message}
        </div>
      ) : null}
    </section>
  );
}
