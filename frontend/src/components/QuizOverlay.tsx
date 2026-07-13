import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { fetchSessionLive } from "../api";
import type { QuestionTally, SessionLiveState } from "../types";

type Props = {
  sessionId: string;
  joinUrl: string;
  onCloseQuestion: () => void;
  onDismiss: () => void;
};

export function QuizOverlay({ sessionId, joinUrl, onCloseQuestion, onDismiss }: Props) {
  const [live, setLive] = useState<SessionLiveState | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [revealed, setRevealed] = useState(false);
  const closedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    QRCode.toDataURL(joinUrl, { width: 220, margin: 1 })
      .then((url) => {
        if (!cancelled) {
          setQrDataUrl(url);
        }
      })
      .catch(() => setQrDataUrl(""));
    return () => {
      cancelled = true;
    };
  }, [joinUrl]);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const payload = await fetchSessionLive(sessionId);
        if (!cancelled) {
          setLive(payload);
        }
      } catch {
        // 保持轮询
      }
      if (!cancelled && !closedRef.current) {
        window.setTimeout(poll, 2000);
      }
    }
    void poll();
    return () => {
      cancelled = true;
      closedRef.current = true;
    };
  }, [sessionId]);

  const question = (live?.active_question || {}) as {
    question_id?: string;
    text?: string;
    type?: string;
    options?: string[];
    answer_index?: number | null;
  };
  const tally: QuestionTally | null = live?.tally || null;
  const options = question.options || [];
  const total = Math.max(tally?.total || 0, 1);

  return (
    <div className="quiz-overlay" data-testid="quiz-overlay">
      <div className="quiz-panel glass-panel">
        <header className="quiz-header">
          <div>
            <p className="panel-tag">Live Quiz</p>
            <h2>{question.text || "等待题目…"}</h2>
          </div>
          <button type="button" className="mini-control" onClick={onDismiss} aria-label="收起投票面板">
            ×
          </button>
        </header>

        <div className="quiz-body">
          <div className="quiz-join">
            {qrDataUrl ? <img src={qrDataUrl} alt="学生扫码作答" /> : <div className="quiz-qr-placeholder">二维码生成中…</div>}
            <p className="quiz-join-url">{joinUrl}</p>
            <p className="quiz-join-count" data-testid="joined-count">
              在线 {live?.joined_count ?? 0} 人 · 已作答 {tally?.total ?? 0} 人
            </p>
          </div>

          <div className="quiz-tally" data-testid="quiz-tally">
            {question.type === "choice" && options.length ? (
              options.map((option, index) => {
                const count = tally?.option_counts?.[index] ?? 0;
                const ratio = count / total;
                const isAnswer = revealed && tally?.answer_index === index;
                return (
                  <div key={index} className={`tally-row ${isAnswer ? "answer" : ""}`}>
                    <span className="tally-label">
                      {String.fromCharCode(65 + index)}. {option}
                      {isAnswer ? " ✅" : ""}
                    </span>
                    <span className="tally-bar-track">
                      <span className="tally-bar" style={{ width: `${Math.max(ratio * 100, 2)}%` }} />
                    </span>
                    <span className="tally-count">{count}</span>
                  </div>
                );
              })
            ) : (
              <div className="tally-texts">
                {(tally?.texts || []).length ? (
                  (tally?.texts || []).map((item, index) => (
                    <p key={index}>
                      <strong>{item.nickname}</strong>：{item.text}
                    </p>
                  ))
                ) : (
                  <p className="tally-empty">等待学生提交回答…</p>
                )}
              </div>
            )}
            {revealed && tally?.correct_rate !== null && tally?.correct_rate !== undefined ? (
              <p className="tally-correct-rate">正确率 {(tally.correct_rate * 100).toFixed(0)}%</p>
            ) : null}
          </div>
        </div>

        <footer className="quiz-actions">
          {question.type === "choice" ? (
            <button type="button" className="toolbar-button compact" onClick={() => setRevealed(true)} disabled={revealed}>
              揭晓答案
            </button>
          ) : null}
          <button
            type="button"
            className="toolbar-button compact primary"
            onClick={() => {
              closedRef.current = true;
              onCloseQuestion();
            }}
          >
            结束提问
          </button>
        </footer>
      </div>
    </div>
  );
}
