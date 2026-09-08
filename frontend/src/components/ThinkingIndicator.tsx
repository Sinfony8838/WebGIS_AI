import { useEffect, useState } from "react";
import "./ThinkingIndicator.css";

type Props = { label?: string; testId?: string };

/** Visible operation status only; elapsed time never fabricates model progress. */
export function ThinkingIndicator({ label = "正在思考", testId = "assistant-thinking" }: Props) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const startedAt = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className="assistant-thinking" data-testid={testId}>
      <span className="assistant-thinking-orbit" aria-hidden="true"><i /><i /><i /></span>
      <div className="assistant-thinking-copy">
        <div className="assistant-thinking-row">
          <span className="assistant-thinking-label" role="status" aria-live="polite">{label}</span>
          <span className="assistant-thinking-time" aria-hidden="true">{elapsed} 秒</span>
        </div>
        <small>{elapsed >= 20 ? "本次处理时间较长，请稍候。结果返回后会显示在这里。" : "正在处理你的请求，完成后会显示结果。"}</small>
      </div>
    </div>
  );
}
