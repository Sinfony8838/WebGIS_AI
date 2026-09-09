import { useEffect, useRef, useState } from "react";
import { buildAuthenticatedUrl, exportSessionPractice, fetchClassSessions, fetchJob, fetchSessionReviewHistory, generateSessionReport } from "../api";
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
  const [selectedPracticeIds, setSelectedPracticeIds] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [reportJobId, setReportJobId] = useState("");
  const [historyState, setHistoryState] = useState<"loading" | "ready" | "error">("loading");
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [historyMessage, setHistoryMessage] = useState("");
  const [practiceRecoveredAt, setPracticeRecoveredAt] = useState("");

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
    setSelectedPracticeIds([]);
    setPracticeExport(null);
    setGenerating(false);
    setExportingPractice(false);
    setError("");
    setReportJobId("");
    setHistoryMessage("");
    setHistoryState("loading");
  }

  function adoptReport(result: SessionReportResult, sessionId: string) {
    if (result.statistics?.session_id !== sessionId) throw new Error("报告与所选课堂不一致，请重新读取。");
    const visibleIds = (result.practice_selection?.item_ids || []).filter(id => result.practice_recommendations?.some(item => item.practice_id === id));
    setReport({ ...result, practice_recommendations: result.practice_recommendations || [], practice_selection_notes: result.practice_selection_notes || [],
      practice_selection: result.practice_selection ? { ...result.practice_selection, item_ids: visibleIds } : undefined });
    setSelectedPracticeIds(visibleIds);
    return visibleIds;
  }

  async function observeReport(jobId: string, sessionId: string, current: () => boolean) {
    setGenerating(true);
    setReportJobId(jobId);
    try {
      while (current()) {
        const job = await fetchJob(jobId);
        if (!current()) return;
        if (job.status === "completed") {
          adoptReport(job.result as unknown as SessionReportResult, sessionId);
          setReportJobId("");
          return;
        }
        if (job.status === "failed") {
          setReportJobId("");
          throw new Error(job.error || "报告生成失败");
        }
        await new Promise(resolve => window.setTimeout(resolve, 1500));
      }
    } catch (exc) {
      if (current()) setError(exc instanceof Error ? exc.message : String(exc));
    } finally { if (current()) setGenerating(false); }
  }

  useEffect(() => {
    if (!selectedSessionId) return;
    let cancelled = false;
    const requestScope = scope.current;
    const current = () => !cancelled && requestScope === scope.current;
    setHistoryState("loading");
    setError("");
    void fetchSessionReviewHistory(selectedSessionId).then(history => {
      if (!current()) return;
      if (history.session_id !== selectedSessionId) throw new Error("历史记录与所选课堂不一致。");
      setHistoryState("ready");
      if (history.report) {
        const previous = history.report;
        setHistoryMessage(`已读取上次报告任务：${formatTime(previous.updated_at)}。课堂记录变化后请重新生成。`);
        if (previous.status === "completed" && previous.result) adoptReport(previous.result, selectedSessionId);
        else if (["queued", "pending", "running"].includes(previous.status)) void observeReport(previous.job_id, selectedSessionId, current);
        else if (previous.status === "failed") setError(previous.error || "上次报告生成失败，可重新生成。");
      }
      const exported = history.practice?.result;
      if (exported && ["success", "completed"].includes(history.practice!.status)) {
        if (exported.session_id !== selectedSessionId) throw new Error("练习卷与所选课堂不一致。");
        setPracticeExport(exported);
        setPracticeRecoveredAt(formatTime(history.practice!.updated_at));
        const selection = history.report?.result?.practice_selection;
        if (selection?.token && exported.selection_token === selection.token && exported.selected_ids) {
          setSelectedPracticeIds(exported.selected_ids.filter(id => selection.item_ids.includes(id)
            && history.report?.result?.practice_recommendations?.some(item => item.practice_id === id)));
        }
      }
    }).catch(exc => {
      if (current()) { setHistoryState("error"); setError(exc instanceof Error ? exc.message : "复盘历史读取失败"); }
    });
    return () => { cancelled = true; };
  }, [selectedSessionId, historyAttempt]);

  async function generate() {
    if (!selectedSessionId) {
      return;
    }
    const sessionId = selectedSessionId;
    const requestScope = scope.current;
    const requestId = ++reportRequest.current;
    const current = () => scope.current === requestScope && reportRequest.current === requestId;
    setPracticeExport(null);
    setSelectedPracticeIds([]);
    setGenerating(true);
    setError("");
    setReport(null);
    setHistoryMessage("");
    try {
      const jobId = reportJobId || (await generateSessionReport(sessionId)).job_id;
      if (!current()) return;
      await observeReport(jobId, sessionId, current);
    } catch (exc) {
      if (!current()) return;
      setError(exc instanceof Error ? exc.message : String(exc));
      setGenerating(false);
      setHistoryState("error"); // Submission may have reached the server; re-read before resubmitting.
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
    setPracticeRecoveredAt("");
    setError("");
    setPracticeExport(null);
    try {
      const result = report?.practice_selection
        ? await exportSessionPractice(sessionId, { token: report.practice_selection.token, selected_ids: selectedPracticeIds })
        : await exportSessionPractice(sessionId);
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
          disabled={!selectedSessionId || generating || exportingPractice || historyState !== "ready"}
          onClick={() => void generate()}
          data-testid="generate-report"
        >
          {generating ? "正在读取生成进度…" : reportJobId ? "继续读取报告" : "生成课堂报告"}
        </button>
        <button
          type="button"
          className="toolbar-button compact"
          disabled={!selectedSessionId || exportingPractice || generating || historyState !== "ready" || (!!report?.practice_selection && !selectedPracticeIds.length)}
          onClick={() => void exportPractice()}
          data-testid="export-practice"
        >
          {exportingPractice ? "导出中…" : report?.practice_selection ? `导出所选 ${selectedPracticeIds.length} 项` : "导出练习卷"}
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

      {historyState === "loading" && selectedSessionId ? <p className="report-note" role="status">正在读取已有报告与练习卷…</p> : null}
      {historyState === "error" ? <button className="toolbar-button compact" onClick={() => setHistoryAttempt(value => value + 1)}>重新读取复盘历史</button> : null}
      {historyMessage ? <p className="report-note">{historyMessage}</p> : null}
      {practiceExport ? (
        <div className="report-practice-export" data-testid="practice-export-result">
          {practiceRecoveredAt ? <p className="report-note">上次导出：{practiceRecoveredAt}</p> : null}
          <p className="report-note">
            已生成的练习卷 · 选题来源：
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
                      {String.fromCharCode(65 + optionIndex)}. {option.replace(/^[A-H][．.、]\s*/, "")}
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

          <h3>课堂地图回看</h3>
          <p className="report-note">按截图时的环节回看地图。截图是展示记录，不能单独证明学生已经理解。</p>
          <div data-testid="report-snapshots">
            {(statistics.snapshots || []).map((snapshot, index) => (
              <details className="report-question" key={`${snapshot.artifact_id}-${index}`}>
                <summary>{snapshot.stage_title} · {formatTime(snapshot.timestamp)}</summary>
                <p>{snapshot.title}</p>
                {snapshot.available && snapshot.image_url.startsWith("/files/outputs/") ? (
                  <a href={buildAuthenticatedUrl(snapshot.image_url)} target="_blank" rel="noreferrer" aria-label={`查看地图原图：${snapshot.title}`}>
                    <img src={buildAuthenticatedUrl(snapshot.image_url)} alt={snapshot.title} loading="lazy" style={{display:"block",maxWidth:"100%",height:"auto"}} />
                    查看地图原图
                  </a>
                ) : <p className="report-note">截图文件不可用，保留原课堂记录。</p>}
              </details>
            ))}
            {!statistics.snapshots?.length ? <p className="report-note">{statistics.snapshot_count ? "这份报告未附截图引用，请重新生成报告。" : "本次课堂没有截图记录。"}</p> : null}
          </div>

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
            {report?.practice_selection_notes?.map((note, index) => <p className="report-note" key={index}>{note}</p>)}
            {report?.practice_selection ? <div className="report-selection-tools">
              <span>已选 {selectedPracticeIds.length} / {report.practice_selection.item_ids.length} 项</span>
              <button className="toolbar-button compact" disabled={exportingPractice} onClick={() => { setSelectedPracticeIds(report.practice_selection!.item_ids); setPracticeExport(null); }}>全选</button>
              <button className="toolbar-button compact" disabled={exportingPractice} onClick={() => { setSelectedPracticeIds([]); setPracticeExport(null); }}>清空选择</button>
            </div> : null}
            {practiceRecommendations.map((item) => (
              <article key={item.practice_id} className="report-question">
                {report?.practice_selection?.item_ids.includes(item.practice_id) ? <label className="report-practice-select">
                  <input type="checkbox" aria-label={`选入练习卷：${item.title}`} checked={selectedPracticeIds.includes(item.practice_id)} disabled={exportingPractice}
                    onChange={event => { setSelectedPracticeIds(ids => event.target.checked ? [...ids, item.practice_id] : ids.filter(id => id !== item.practice_id)); setPracticeExport(null); }} />
                  选入练习卷
                </label> : null}
                <p className="report-question-text">
                  [{item.level}] {item.title}{item.suggested_minutes ? ` · 建议 ${item.suggested_minutes} 分钟` : ""}
                </p>
                <details open={item.question ? undefined : true}>
                  <summary>{item.prompt}</summary>
                {item.question?.material ? <p className="report-practice-material">{item.question.material}</p> : null}
                {item.question?.images?.map((image, index) => (
                  <a key={index} href={buildAuthenticatedUrl(image.url)} target="_blank" rel="noreferrer" aria-label={`查看题图原图：${item.title} ${index + 1}`}>
                    <img className="report-practice-image" src={buildAuthenticatedUrl(image.url)} alt={`${item.title} 题图 ${index + 1}`} loading="lazy" />
                  </a>
                ))}
                {item.question?.task_text && item.question.task_text !== item.prompt ? <p>{item.question.task_text}</p> : null}
                {item.question?.options?.map((option, index) => <p key={index}>{String.fromCharCode(65 + index)}. {option.replace(/^[A-H][．.、]\s*/, "")}</p>)}
                {item.question?.sub_questions?.map((sub, index) => <div key={index}>
                  <p>（{sub.index}）{sub.text}</p>
                  {sub.options?.map((option, optionIndex) => <p key={optionIndex}>{String.fromCharCode(65 + optionIndex)}. {option.replace(/^[A-H][．.、]\s*/, "")}</p>)}
                </div>)}
                <p className="report-note">{item.answer_points.length ? `参考要点：${item.answer_points.join("；")}` : "开放任务或未附参考答案，请结合原题材料评阅。"}</p>
                </details>
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
