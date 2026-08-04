import { useCallback, useEffect, useState } from "react";
import { buildAuthenticatedUrl, fetchClassSessions, fetchJob, generateSessionReport } from "../api";
import type { ClassSessionRecord, SessionReportResult, SessionReportStatistics } from "../types";

type Props = {
  projectId: string;
  onClose: () => void;
};

const VERDICT_LABELS: Record<string, string> = {
  correct: "答对",
  partial: "部分",
  misconception: "误区"
};

function formatTime(value: string): string {
  if (!value) {
    return "—";
  }
  try {
    return new Date(value).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return value;
  }
}

export function ReportPanel({ projectId, onClose }: Props) {
  const [sessions, setSessions] = useState<ClassSessionRecord[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [report, setReport] = useState<SessionReportResult | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");

  const loadSessions = useCallback(async () => {
    try {
      const payload = await fetchClassSessions({ projectId });
      setSessions(payload.items);
      if (payload.items.length && !selectedSessionId) {
        setSelectedSessionId(payload.items[0].session_id);
      }
    } catch {
      setSessions([]);
    }
  }, [projectId, selectedSessionId]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  async function generate() {
    if (!selectedSessionId) {
      return;
    }
    setGenerating(true);
    setError("");
    setReport(null);
    try {
      const { job_id } = await generateSessionReport(selectedSessionId);
      for (let attempt = 0; attempt < 120; attempt += 1) {
        const job = await fetchJob(job_id);
        if (job.status === "completed") {
          const result = job.result as unknown as SessionReportResult & { status: string };
          setReport({
            statistics: result.statistics,
            diagnosis: result.diagnosis,
            report_url: result.report_url || ""
          });
          setGenerating(false);
          return;
        }
        if (job.status === "failed") {
          throw new Error(job.error || "报告生成失败");
        }
        await new Promise((resolve) => window.setTimeout(resolve, 500));
      }
      throw new Error("报告生成超时");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setGenerating(false);
    }
  }

  const statistics: SessionReportStatistics | null = report?.statistics || null;

  return (
    <section className="report-panel glass-panel" data-testid="report-panel">
      <header className="lesson-panel-header">
        <div>
          <p className="panel-tag">After-class Review</p>
          <h2>课后复盘</h2>
        </div>
        <button type="button" className="mini-control" onClick={onClose} aria-label="关闭复盘面板">
          ×
        </button>
      </header>

      <div className="report-toolbar">
        <select value={selectedSessionId} onChange={(event) => setSelectedSessionId(event.target.value)}>
          <option value="" disabled>
            选择课堂会话…
          </option>
          {sessions.map((session) => (
            <option key={session.session_id} value={session.session_id}>
              {String(session.metadata?.lesson_title || session.lesson_id)} · {formatTime(session.started_at)}
              {session.status === "running" ? "（进行中）" : ""}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="toolbar-button compact primary"
          disabled={!selectedSessionId || generating}
          onClick={() => void generate()}
          data-testid="generate-report"
        >
          {generating ? "生成中…" : "生成课堂报告"}
        </button>
        {report?.report_url ? (
          <a
            className="toolbar-button compact"
            href={buildAuthenticatedUrl(report.report_url)}
            target="_blank"
            rel="noreferrer"
          >
            下载 Markdown
          </a>
        ) : null}
      </div>

      {error ? <p className="report-error">{error}</p> : null}
      {!sessions.length ? <p className="lesson-empty">该项目还没有课堂会话记录。先在「上课」模式完成一次课堂吧。</p> : null}

      {statistics ? (
        <div className="report-body">
          <div className="report-summary-row">
            <div className="report-stat">
              <strong>{statistics.duration_minutes ?? "—"}</strong>
              <span>课堂时长(分)</span>
            </div>
            <div className="report-stat">
              <strong>{statistics.response_data_collected ? statistics.participant_count : "未采集"}</strong>
              <span>学生端作答</span>
            </div>
            <div className="report-stat">
              <strong>{statistics.questions.length}</strong>
              <span>系统提问</span>
            </div>
            <div className="report-stat">
              <strong>{statistics.observations.total}</strong>
              <span>教师速记</span>
            </div>
            <div className="report-stat">
              <strong>{statistics.snapshot_count}</strong>
              <span>课堂截图</span>
            </div>
          </div>

          <h3>环节用时</h3>
          <div className="report-stages">
            {statistics.stages.map((stage) => {
              const planned = stage.planned_minutes || 0;
              const actual = stage.actual_minutes || 0;
              const over = planned > 0 && actual > planned * 1.2;
              const scale = Math.max(planned, actual, 1);
              return (
                <div key={stage.stage_id + stage.entered_at} className="report-stage-row">
                  <span className="report-stage-title">{stage.title}</span>
                  <span className="report-stage-bars">
                    <span className="stage-bar planned" style={{ width: `${(planned / scale) * 100}%` }} />
                    <span className={`stage-bar actual ${over ? "over" : ""}`} style={{ width: `${(actual / scale) * 100}%` }} />
                  </span>
                  <span className="report-stage-minutes">
                    {actual || "—"} / {planned || "—"} 分
                  </span>
                </div>
              );
            })}
            {!statistics.stages.length ? <p className="lesson-empty">本次会话未记录环节切换。</p> : null}
          </div>

          <h3>教师提问与课堂证据</h3>
          {statistics.questions.map((question, index) => (
            <div key={question.question_id} className="report-question">
              <p className="report-question-text">
                Q{index + 1}. {question.text}（
                {question.collection_mode === "teacher_observation"
                  ? "教师口头呈现 · 表现见教师观察"
                  : `${question.response_count} 人作答${question.correct_rate !== null ? ` · 正确率 ${(question.correct_rate * 100).toFixed(0)}%` : ""}`}
                ）
              </p>
              {question.collection_mode !== "teacher_observation" ? question.options.map((option, optionIndex) => {
                const count = question.option_counts[optionIndex] || 0;
                const total = Math.max(question.response_count, 1);
                return (
                  <div key={optionIndex} className={`tally-row ${question.answer_index === optionIndex ? "answer" : ""}`}>
                    <span className="tally-label">
                      {String.fromCharCode(65 + optionIndex)}. {option}
                      {question.answer_index === optionIndex ? " ✅" : ""}
                    </span>
                    <span className="tally-bar-track">
                      <span className="tally-bar" style={{ width: `${Math.max((count / total) * 100, 2)}%` }} />
                    </span>
                    <span className="tally-count">{count}</span>
                  </div>
                );
              }) : question.options.length ? (
                <p className="report-question-options">
                  备选项：{question.options.map((option, optionIndex) => `${String.fromCharCode(65 + optionIndex)}. ${option}`).join("；")}
                </p>
              ) : null}
              {question.sample_texts.length ? (
                <div className="report-sample-texts">
                  {question.sample_texts.map((text, textIndex) => (
                    <em key={textIndex}>「{text}」</em>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
          {!statistics.questions.length ? <p className="lesson-empty">本节课未记录教师提问。</p> : null}

          <h3>教师课堂观察</h3>
          <div className="report-observations">
            <p>
              {Object.entries(statistics.observations.verdict_counts)
                .map(([verdict, count]) => `${VERDICT_LABELS[verdict] || verdict} ${count} 次`)
                .join(" · ")}
            </p>
            <div className="report-tags">
              {statistics.observations.misconception_tags.map(([tag, count]) => (
                <span key={tag} className="tag-chip static">
                  {tag} ×{count}
                </span>
              ))}
            </div>
            {statistics.observations.notes.map((note, noteIndex) => (
              <p key={noteIndex} className="report-note">
                [{VERDICT_LABELS[note.verdict] || note.verdict}
                {note.tag ? ` · ${note.tag}` : ""}] {note.note}
              </p>
            ))}
          </div>

          <h3>
            学情诊断与建议
            <em className="diagnosis-source">
              {report?.diagnosis.generator === "minimax" ? "（AI 生成）" : "（规则生成 · 离线兜底）"}
            </em>
          </h3>
          <div className="report-diagnosis" data-testid="report-diagnosis">
            {report?.diagnosis.text.split("\n").map((line, lineIndex) =>
              line.startsWith("###") ? (
                <h4 key={lineIndex}>{line.replace(/^#+\s*/, "")}</h4>
              ) : line.trim() ? (
                <p key={lineIndex}>{line}</p>
              ) : null
            )}
          </div>
        </div>
      ) : null}
    </section>
  );
}
