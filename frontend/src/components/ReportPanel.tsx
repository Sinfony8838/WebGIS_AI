import { useEffect, useRef, useState } from "react";
import { buildAuthenticatedUrl, exportSessionPractice, fetchClassSessions, fetchJob, generateSessionReport } from "../api";
import type { ClassSessionRecord, SessionPracticeExportResult, SessionReportResult, SessionReportStatistics } from "../types";

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

export function ReportPanel(props: Props) {
  // A project change owns a fresh selection and cannot inherit another project's results.
  return <ProjectReportPanel key={props.projectId} {...props} />;
}

function ProjectReportPanel({ projectId, onClose }: Props) {
  const [sessions, setSessions] = useState<ClassSessionRecord[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [report, setReport] = useState<SessionReportResult | null>(null);
  const [generating, setGenerating] = useState(false);
  const [practiceExport, setPracticeExport] = useState<SessionPracticeExportResult | null>(null);
  const [exportingPractice, setExportingPractice] = useState(false);
  const [error, setError] = useState("");

  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const scope = useRef(0);
  const reportRequest = useRef(0);
  const exportRequest = useRef(0);

  useEffect(() => () => { scope.current += 1; }, []);
  useEffect(() => {
    let cancelled = false;
    setLoadState("loading");
    void fetchClassSessions({ projectId }).then(payload => {
      if (cancelled) return;
      setSessions(payload.items);
      setSelectedSessionId(payload.items[0]?.session_id || "");
      setLoadState("ready");
    }).catch(() => { if (!cancelled) setLoadState("error"); });
    return () => { cancelled = true; };
  }, [projectId, loadAttempt]);

  function selectSession(sessionId: string) {
    scope.current += 1;
    setSelectedSessionId(sessionId);
    setReport(null);
    setPracticeExport(null);
    setGenerating(false);
    setExportingPractice(false);
    setError("");
  }

  async function generate() {
    if (!selectedSessionId) {
      return;
    }
    const sessionId = selectedSessionId;
    const requestScope = scope.current;
    const requestId = ++reportRequest.current;
    const current = () => scope.current === requestScope && reportRequest.current === requestId;
    setGenerating(true);
    setError("");
    setReport(null);
    try {
      const { job_id } = await generateSessionReport(sessionId);
      if (!current()) return;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        if (!current()) return;
        const job = await fetchJob(job_id);
        if (!current()) return;
        if (job.status === "completed") {
          const result = job.result as unknown as SessionReportResult & { status: string };
          if (result.statistics?.session_id !== sessionId) throw new Error("报告与所选课堂不一致，请重新生成。");
          setReport({
            statistics: result.statistics,
            diagnosis: result.diagnosis,
            practice_recommendations: result.practice_recommendations || [],
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
      if (!current()) return;
      setError(exc instanceof Error ? exc.message : String(exc));
      setGenerating(false);
    }
  }

  const statistics: SessionReportStatistics | null = report?.statistics || null;
  const practiceRecommendations = report?.practice_recommendations || [];

  async function exportPractice() {
    if (!selectedSessionId) {
      return;
    }
    const sessionId = selectedSessionId;
    const requestScope = scope.current;
    const requestId = ++exportRequest.current;
    const current = () => scope.current === requestScope && exportRequest.current === requestId;
    setExportingPractice(true);
    setError("");
    setPracticeExport(null);
    try {
      const result = await exportSessionPractice(sessionId);
      if (!current()) return;
      if (result.session_id !== sessionId) throw new Error("练习卷与所选课堂不一致，请重新导出。");
      setPracticeExport(result);
    } catch (exc) {
      if (!current()) return;
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      if (current()) setExportingPractice(false);
    }
  }

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
        <select aria-label="选择课堂记录" disabled={loadState !== "ready" || !sessions.length}
          value={selectedSessionId} onChange={(event) => selectSession(event.target.value)}>
          <option value="" disabled>
            选择课堂会话…
          </option>
          {sessions.map((session) => (
            <option key={session.session_id} value={session.session_id}>
              {formatTime(session.started_at)} · {String(session.metadata?.lesson_title || session.lesson_id)}
              {session.status === "running" ? "（进行中）" : ""}
            </option>
          ))}
        </select>
        <div className="report-toolbar-actions">
        <button
          type="button"
          className="toolbar-button compact primary"
          disabled={!selectedSessionId || generating}
          onClick={() => void generate()}
          data-testid="generate-report"
        >
          {generating ? "生成中…" : "生成课堂报告"}
        </button>
        <button
          type="button"
          className="toolbar-button compact"
          disabled={!selectedSessionId || exportingPractice}
          onClick={() => void exportPractice()}
          data-testid="export-practice"
        >
          {exportingPractice ? "导出中…" : "导出练习卷"}
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
      </div>

      {practiceExport ? (
        <div className="report-practice-export" data-testid="practice-export-result">
          <p className="report-note">
            选题来源：
            {practiceExport.selection_summary
              .filter((entry) => entry.count > 0)
              .map((entry) => `${entry.label} ×${entry.count}`)
              .join(" · ") || "无可选题内容"}
          </p>
          {practiceExport.notes.map((note, noteIndex) => (
            <p key={noteIndex} className="report-note">
              {note}
            </p>
          ))}
          <div className="report-practice-links">
            <a
              className="toolbar-button compact primary"
              href={buildAuthenticatedUrl(practiceExport.student_artifact.metadata?.public_url || "")}
              target="_blank"
              rel="noreferrer"
              data-testid="practice-student-link"
            >
              下载学生卷（无答案）
            </a>
            <a
              className="toolbar-button compact"
              href={buildAuthenticatedUrl(practiceExport.teacher_artifact.metadata?.public_url || "")}
              target="_blank"
              rel="noreferrer"
              data-testid="practice-teacher-link"
            >
              下载教师卷（含答案与课堂实测）
            </a>
          </div>
        </div>
      ) : null}

      {error ? <p className="report-error" role="alert">{error}</p> : null}
      {loadState === "loading" ? <p className="report-note" role="status">正在加载课堂记录…</p> : null}
      {loadState === "error" ? <div className="report-load-error" role="alert">
        <p>课堂记录加载失败，请重试。</p>
        <button type="button" className="toolbar-button compact" onClick={() => setLoadAttempt(value => value + 1)}>重新加载课堂记录</button>
      </div> : null}
      {loadState === "ready" && !sessions.length ? <p className="lesson-empty">该项目还没有课堂记录。可先在「课堂模式」开始一节课。</p> : null}

      {statistics ? (
        <div className="report-body">
          <div className="report-summary-row">
            <div className="report-stat">
              <strong>{statistics.duration_minutes ?? "—"}</strong>
              <span>课堂时长(分)</span>
            </div>
            <div className="report-stat">
              <strong>{statistics.response_data_collected ? statistics.participant_count : "未采集"}</strong>
              <span>课堂作答</span>
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
                  : question.response_count === 0 ? "本题未采集作答数据" : `${question.response_count} 人作答${question.correct_rate !== null ? ` · 正确率 ${(question.correct_rate * 100).toFixed(0)}%` : ""}`}
                ）
              </p>
              {question.collection_mode !== "teacher_observation" && question.response_count > 0 ? question.options.map((option, optionIndex) => {
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
              {report?.diagnosis.generator === "minimax" ? "（AI 生成）" : "（规则生成 · 证据保护）"}
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

          <h3>
            课后推荐练习巩固
            <em className="diagnosis-source">（课堂结束后 · 不计入课堂教学用时）</em>
          </h3>
          <div className="report-practice-list" data-testid="report-practice-list">
            {practiceRecommendations.map((item) => (
              <article key={item.practice_id} className="report-question">
                <p className="report-question-text">
                  [{item.level}] {item.title}{item.suggested_minutes ? ` · 建议 ${item.suggested_minutes} 分钟` : ""}
                </p>
                <p>{item.prompt}</p>
                <p className="report-note">{item.answer_points.length ? `参考要点：${item.answer_points.join("；")}` : "开放任务或未附参考答案，请结合原题材料评阅。"}</p>
                <p className="report-note">推荐依据：{item.evidence_basis}</p>
              </article>
            ))}
            {!practiceRecommendations.length ? (
              <p className="lesson-empty">当前课堂记录尚未生成推荐练习。</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
