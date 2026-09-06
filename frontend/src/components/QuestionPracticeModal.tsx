import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { buildAuthenticatedUrl } from "../api";
import type { LessonQuestion, ObservationVerdict } from "../types";

type Props = {
  /** 来自班课 active_question 的完整题目快照（含服务端计时状态 timer）。 */
  question: LessonQuestion;
  busy: boolean;
  onTimerAction: (action: "start" | "pause" | "resume" | "reset") => void;
  onReveal: () => void;
  /** 收题并关闭；未揭示时由服务端记录「未揭示答案」事实。 */
  onClose: () => void;
  onObservation: (verdict: ObservationVerdict, tag: string, note: string) => void;
};

const OPTION_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H"];

const SOURCE_LABELS: Record<string, string> = {
  question_bank: "题库题",
  teacher_manual: "教师手录",
  adhoc: "临时题",
  lesson: "课时题目"
};

function formatClock(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  return `${minutes}:${String(safe % 60).padStart(2, "0")}`;
}

export function QuestionPracticeModal({
  question,
  busy,
  onTimerAction,
  onReveal,
  onClose,
  onObservation
}: Props) {
  const timer = question.timer;
  const [nowTick, setNowTick] = useState(() => Date.now());
  // 服务端每次响应带回实时计算好的 elapsed_seconds；以收到时刻为锚点本地递增，
  // 不依赖浏览器与服务端的时钟一致。
  const [anchor, setAnchor] = useState<{ elapsed: number; at: number }>({ elapsed: 0, at: Date.now() });
  const [note, setNote] = useState("");
  const [noteTag, setNoteTag] = useState("");
  const [noteVerdict, setNoteVerdict] = useState<ObservationVerdict | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    const interval = window.setInterval(() => setNowTick(Date.now()), 500);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (timer) {
      setAnchor({ elapsed: timer.elapsed_seconds, at: Date.now() });
    }
  }, [timer]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const running = timer?.status === "running";
  const elapsedSeconds = timer
    ? running
      ? anchor.elapsed + Math.max(0, Math.floor((nowTick - anchor.at) / 1000))
      : timer.elapsed_seconds
    : 0;
  const suggested = timer?.suggested_seconds || question.suggested_seconds || 120;
  const remaining = suggested - elapsedSeconds;
  const overtime = remaining < 0;
  const revealed = Boolean(timer?.revealed);

  function submitNote(verdict: ObservationVerdict) {
    if (verdict !== "misconception") {
      onObservation(verdict, "", note.trim());
      resetNote();
      flashSaved();
      return;
    }
    setNoteVerdict("misconception");
  }

  function confirmMisconception() {
    onObservation("misconception", noteTag.trim(), note.trim());
    resetNote();
    flashSaved();
  }

  function resetNote() {
    setNoteVerdict(null);
    setNoteTag("");
    setNote("");
  }

  function flashSaved() {
    setSavedFlash(true);
    window.setTimeout(() => setSavedFlash(false), 1800);
  }

  const images = question.images || [];

  return createPortal(
    <div className="qpm-backdrop" data-testid="question-practice-modal">
      <section className="qpm-shell" role="dialog" aria-label="题目投屏">
        <header className="qpm-header">
          <div className="qpm-heading">
            <span className="qpm-kicker">
              题目投屏 · {SOURCE_LABELS[timer?.question_source || ""] || "题目"}
            </span>
            <strong>{question.type === "choice" ? "选择" : question.type === "composite" ? "复合题" : "问答题"}</strong>
            {question.knowledge_points?.length ? (
              <span className="qpm-meta">{question.knowledge_points.join(" · ")}</span>
            ) : null}
          </div>
          <button
            type="button"
            className="mini-control"
            onClick={onClose}
            aria-label="收题并关闭投屏"
            data-testid="qpm-close"
          >
            ×
          </button>
        </header>

        {revealed ? (
          <div className="qpm-timer revealed" data-testid="qpm-revealed-timer">
            <span>实际用时 {formatClock(timer?.actual_seconds ?? elapsedSeconds)}</span>
            {(timer?.overtime_seconds || 0) > 0 ? (
              <em className="qpm-overtime">超时 {formatClock(timer?.overtime_seconds || 0)}</em>
            ) : (
              <em className="qpm-ontime">未超时</em>
            )}
          </div>
        ) : (
          <div className={`qpm-timer ${overtime ? "overtime" : ""} ${timer?.status || "idle"}`}>
            <div className="qpm-timer-clock" data-testid="qpm-clock">
              {overtime ? `已超时 ${formatClock(-remaining)}` : formatClock(remaining)}
            </div>
            <div className="qpm-timer-sub">
              建议用时 {formatClock(suggested)} · 已用 {formatClock(elapsedSeconds)}
            </div>
            <div className="qpm-timer-actions">
              {timer?.status === "idle" ? (
                <button
                  type="button"
                  className="toolbar-button compact primary"
                  disabled={busy}
                  onClick={() => onTimerAction("start")}
                  data-testid="qpm-start"
                >
                  开始计时
                </button>
              ) : null}
              {running ? (
                <button
                  type="button"
                  className="toolbar-button compact"
                  disabled={busy}
                  onClick={() => onTimerAction("pause")}
                  data-testid="qpm-pause"
                >
                  暂停
                </button>
              ) : null}
              {timer?.status === "paused" ? (
                <button
                  type="button"
                  className="toolbar-button compact primary"
                  disabled={busy}
                  onClick={() => onTimerAction("resume")}
                  data-testid="qpm-resume"
                >
                  继续
                </button>
              ) : null}
              {timer && (running || timer.status === "paused") ? (
                <button
                  type="button"
                  className="toolbar-button compact"
                  disabled={busy}
                  onClick={() => onTimerAction("reset")}
                  data-testid="qpm-reset"
                >
                  重置
                </button>
              ) : null}
              <button
                type="button"
                className="toolbar-button compact danger"
                disabled={busy}
                onClick={onReveal}
                data-testid="qpm-reveal"
              >
                提前查看答案
              </button>
            </div>
          </div>
        )}

        <div className="qpm-body">
          {question.task_text ? (
            <p className="qpm-task" data-testid="qpm-task">
              {question.task_text}
            </p>
          ) : null}
          {question.material ? (
            <div className="qpm-material" data-testid="qpm-material">
              <span className="qpm-section-label">材料</span>
              <p>{question.material}</p>
            </div>
          ) : null}
          {images.length ? (
            <div className="qpm-images" data-testid="qpm-images">
              {images.map((image, index) => (
                <img key={`${image.url}_${index}`} src={buildAuthenticatedUrl(image.url)} alt={`题图 ${index + 1}`} />
              ))}
            </div>
          ) : null}
          <div className="qpm-stem" data-testid="qpm-stem">
            {question.text}
          </div>
          {question.options.length ? (
            <ol className="qpm-options" data-testid="qpm-options">
              {question.options.map((option, index) => (
                <li key={index} className={revealed && question.answer_index === index ? "correct" : ""}>
                  <span className="option-label">{OPTION_LABELS[index] || index + 1}</span>
                  <span>{option}</span>
                </li>
              ))}
            </ol>
          ) : null}
          {question.sub_questions?.length ? (
            <div className="qpm-subs" data-testid="qpm-subs">
              {question.sub_questions.map((sub) => (
                <div key={sub.index} className="qpm-sub">
                  <p className="qpm-sub-stem">
                    {sub.index}. {sub.text}
                  </p>
                  {sub.options.length ? (
                    <ol className="qpm-options">
                      {sub.options.map((option, index) => (
                        <li key={index} className={revealed && sub.answer_index === index ? "correct" : ""}>
                          <span className="option-label">{OPTION_LABELS[index] || index + 1}</span>
                          <span>{option}</span>
                        </li>
                      ))}
                    </ol>
                  ) : null}
                  {revealed ? (
                    <div className="qpm-sub-answer">
                      <strong>答案：{sub.answer || "（未提供）"}</strong>
                      {sub.explanation ? <p>{sub.explanation}</p> : null}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}

          {revealed ? (
            <div className="qpm-answer" data-testid="qpm-answer">
              <span className="qpm-section-label">官方答案</span>
              <p className="qpm-answer-main">
                {question.answer
                  ? `${question.answer_letter ? `${question.answer_letter}. ` : ""}${question.answer}`
                  : question.answer_index !== null && question.answer_index !== undefined && question.options.length
                    ? `正确选项：${OPTION_LABELS[question.answer_index] || question.answer_index + 1}. ${question.options[question.answer_index]}`
                    : "（本题未提供官方答案）"}
              </p>
              {question.explanation ? (
                <div className="qpm-explanation">
                  <span className="qpm-section-label">官方解析</span>
                  <p>{question.explanation}</p>
                </div>
              ) : null}
              {question.knowledge_points?.length ? (
                <div className="qpm-knowledge">
                  {question.knowledge_points.map((point) => (
                    <span key={point} className="qpm-knowledge-chip">
                      {point}
                    </span>
                  ))}
                </div>
              ) : null}
              {timer?.ai_explanation ? (
                <div className="qpm-ai" data-testid="qpm-ai">
                  <span className="qpm-section-label">
                    AI 讲解{timer.ai_explanation.generator === "minimax" ? "" : "（规则生成）"}
                  </span>
                  <p>{timer.ai_explanation.text}</p>
                </div>
              ) : null}
              <div className="qpm-notes" data-testid="qpm-notes">
                <span className="qpm-section-label">
                  学情速记{savedFlash ? <em className="record-saved"> ✓ 已记录</em> : null}
                </span>
                <div className="qpm-note-row">
                  <input
                    value={note}
                    placeholder="一句话描述学生表现（可留空）"
                    onChange={(event) => setNote(event.target.value)}
                  />
                </div>
                <div className="qpm-note-actions">
                  <button
                    type="button"
                    className="record-button correct"
                    onClick={() => submitNote("correct")}
                    data-testid="qpm-note-correct"
                  >
                    答对
                  </button>
                  <button
                    type="button"
                    className="record-button partial"
                    onClick={() => submitNote("partial")}
                    data-testid="qpm-note-partial"
                  >
                    部分
                  </button>
                  <button
                    type="button"
                    className={`record-button misconception ${noteVerdict === "misconception" ? "active" : ""}`}
                    onClick={() => submitNote("misconception")}
                    data-testid="qpm-note-misconception"
                  >
                    误区
                  </button>
                </div>
                {noteVerdict === "misconception" ? (
                  <div className="qpm-misconception" data-testid="qpm-misconception">
                    <input
                      value={noteTag}
                      placeholder="输入误区标签"
                      onChange={(event) => setNoteTag(event.target.value)}
                    />
                    <button
                      type="button"
                      className="toolbar-button compact primary"
                      onClick={confirmMisconception}
                      data-testid="qpm-note-confirm"
                    >
                      记录误区
                    </button>
                    <button type="button" className="toolbar-button compact" onClick={resetNote}>
                      取消
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>

        <footer className="qpm-footer">
          <span className="qpm-footer-hint">学生端已同步本题，可在其设备作答；答案揭示前学生端不可见。</span>
          <button
            type="button"
            className="toolbar-button compact"
            onClick={onClose}
            disabled={busy}
            data-testid="qpm-close-footer"
          >
            {revealed ? "收题并关闭" : "收题（未揭示答案）"}
          </button>
        </footer>
      </section>
    </div>,
    document.body
  );
}
