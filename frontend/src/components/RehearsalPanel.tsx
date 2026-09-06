import { useEffect, useRef, useState } from "react";
import {
  applyRehearsalStageScene,
  cancelLessonRehearsal,
  completeLessonRehearsal,
  createLessonRehearsal,
  fetchLessonRehearsalReport,
  searchQuestionBanks,
  updateLessonRehearsal,
  uploadImageLibraryAsset
} from "../api";
import type {
  LessonGlobeScene,
  LessonPlanProfile,
  LessonQuestion,
  LessonRecord,
  LessonRehearsalRecord,
  LessonRehearsalReport,
  LessonStage,
  QuestionBankQuestion,
  SceneSnapshot
} from "../types";

type Props = {
  projectId: string;
  lesson: LessonRecord;
  /** 读取当前地图状态（底图/视图/图层/模板/3D），存为工作副本环节场景。 */
  getSceneSnapshot: () => SceneSnapshot;
  onApplyGlobeScene: (globe: LessonGlobeScene) => void;
  onRefresh: () => void | Promise<void>;
  /** 完成发布后回传新版课时（工作台刷新课程卡片）。 */
  onLessonCommitted: (lesson: LessonRecord) => void;
  onClose: () => void;
};

// 试讲检查清单：模拟测试中教师逐项自测；结果只留在模拟测试记录里。
const TEST_ITEMS: Array<{ key: string; label: string; hint: string }> = [
  { key: "map_test", label: "地图与图层", hint: "各环节场景能正确切换、图层显示符合预期" },
  { key: "screenshot_test", label: "截图存证", hint: "地图截图可作为课堂证据保存" },
  { key: "assistant_test", label: "教学助教", hint: "预设追问能把助教带回教学主线" },
  { key: "question_preview_test", label: "题面预览", hint: "题面、题图与选项在模拟测试面板中清晰可读" }
];

function questionLabel(question: LessonQuestion): string {
  const tags: string[] = [];
  if (question.source === "question_bank") tags.push(`题库 ${question.number || ""}`.trim());
  else if (question.source === "teacher_manual") tags.push("手动");
  if (question.year) tags.push(question.year);
  if (question.answer_complete === false) tags.push("答案缺失");
  const prefix = tags.length ? `（${tags.join(" · ")}）` : "";
  return `${prefix}${question.text || question.task_text || ""}`;
}

function readImageSize(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const image = new window.Image();
    image.onload = () => {
      resolve({ width: image.naturalWidth || 0, height: image.naturalHeight || 0 });
      URL.revokeObjectURL(url);
    };
    image.onerror = () => {
      resolve({ width: 0, height: 0 });
      URL.revokeObjectURL(url);
    };
    image.src = url;
  });
}

export function RehearsalPanel({
  projectId,
  lesson,
  getSceneSnapshot,
  onApplyGlobeScene,
  onRefresh,
  onLessonCommitted,
  onClose
}: Props) {
  const [rehearsal, setRehearsal] = useState<LessonRehearsalRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [expandedStageId, setExpandedStageId] = useState("");
  const [editStageId, setEditStageId] = useState("");
  const [editMinutes, setEditMinutes] = useState(5);
  const [captureHint, setCaptureHint] = useState("");
  const [swapTarget, setSwapTarget] = useState<{ stageId: string; position: number; questionId: string } | null>(null);
  const [swapSearch, setSwapSearch] = useState("");
  const [swapResults, setSwapResults] = useState<QuestionBankQuestion[]>([]);
  const [manualStageId, setManualStageId] = useState("");
  const [manualForm, setManualForm] = useState({ text: "", answer: "", explanation: "" });
  const [report, setReport] = useState<LessonRehearsalReport | null>(null);
  const [completedLesson, setCompletedLesson] = useState<LessonRecord | null>(null);
  const [completedExportUrl, setCompletedExportUrl] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const uploadTargetRef = useRef<{ stageId: string; questionId: string } | null>(null);

  // 开启（或续用）本课时的模拟测试：同一课时同时只有一个进行中的模拟测试。
  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError("");
    createLessonRehearsal(projectId, lesson.lesson_id)
      .then((payload) => {
        if (cancelled) return;
        setRehearsal(payload.rehearsal);
        if (payload.resumed) {
          setError("");
        }
      })
      .catch((exc) => {
        if (!cancelled) setError(exc instanceof Error ? exc.message : String(exc));
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
    // lesson 变化即切换模拟对象，重新开启。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, lesson.lesson_id]);

  const workingCopy: LessonPlanProfile | null = rehearsal?.working_copy || null;
  const stages: LessonStage[] = (workingCopy?.stages || []) as LessonStage[];
  const totalMinutes = stages.reduce((sum, stage) => sum + (stage.minutes || 0), 0);
  const durationMinutes = Number(workingCopy?.duration_minutes || lesson.stages.reduce((sum, stage) => sum + (stage.minutes || 0), 0) || 40);
  const active = rehearsal?.status === "active";

  async function run<T>(operation: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setError("");
    try {
      return await operation();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function applyUpdate(payload: Parameters<typeof updateLessonRehearsal>[1]) {
    if (!rehearsal) return null;
    const result = await run(() =>
      updateLessonRehearsal(rehearsal.rehearsal_id, { ...payload, expected_revision: rehearsal.revision })
    );
    if (result) {
      setRehearsal(result.rehearsal);
      setReport(null);
    }
    return result;
  }

  async function saveStageMinutes(stage: LessonStage) {
    if (!rehearsal) return;
    const minutes = Math.max(1, Math.round(editMinutes || stage.minutes));
    const nextStages = stages.map((item) => (item.stage_id === stage.stage_id ? { ...item, minutes } : item));
    const result = await applyUpdate({ patch: { stages: nextStages } });
    if (result) setEditStageId("");
  }

  async function removeQuestion(stageId: string, questionId: string) {
    await applyUpdate({ question_remove: { stage_id: stageId, question_id: questionId } });
  }

  async function bindManual(stageId: string) {
    if (!manualForm.text.trim()) return;
    const result = await applyUpdate({
      question_bind: {
        stage_id: stageId,
        manual: {
          text: manualForm.text.trim(),
          type: "open",
          answer: manualForm.answer.trim(),
          explanation: manualForm.explanation.trim()
        }
      }
    });
    if (result) {
      setManualForm({ text: "", answer: "", explanation: "" });
      setManualStageId("");
    }
  }

  async function runSwapSearch() {
    if (!swapSearch.trim()) return;
    const result = await run(() =>
      searchQuestionBanks({ project_id: projectId, topic: swapSearch.trim(), limit: 8 })
    );
    setSwapResults(result?.items || []);
  }

  async function swapIn(questionId: string) {
    if (!swapTarget) return;
    const result = await applyUpdate({
      question_bind: { stage_id: swapTarget.stageId, question_id: questionId, position: swapTarget.position }
    });
    if (result) {
      setSwapTarget(null);
      setSwapResults([]);
      setSwapSearch("");
    }
  }

  async function previewScene(stageId: string) {
    if (!rehearsal) return;
    const result = await run(() => applyRehearsalStageScene(rehearsal.rehearsal_id, stageId));
    if (result) {
      onApplyGlobeScene(result.globe || {});
      await onRefresh();
    }
  }

  async function captureScene(stageId: string) {
    setCaptureHint("");
    const result = await applyUpdate({
      scene_capture: { stage_id: stageId, snapshot: getSceneSnapshot() }
    });
    if (result) {
      setCaptureHint(stageId);
      window.setTimeout(() => setCaptureHint(""), 2500);
    }
  }

  async function recordTest(key: string, passed: boolean) {
    await applyUpdate({ test_result: { key, passed, note: passed ? "通过" : "未通过" } });
  }

  async function pickImage(stageId: string, questionId: string) {
    uploadTargetRef.current = { stageId, questionId };
    fileInputRef.current?.click();
  }

  async function onImageFile(file: File | null) {
    const target = uploadTargetRef.current;
    uploadTargetRef.current = null;
    if (!file || !target) return;
    const { width, height } = await readImageSize(file);
    const uploaded = await run(() => uploadImageLibraryAsset(projectId, file, "模拟测试题图"));
    if (!uploaded) return;
    const url = String(uploaded.artifact.metadata?.public_url || "");
    if (!url) {
      setError("题图上传成功但未返回可访问地址，请稍后重试。");
      return;
    }
    await applyUpdate({
      image_bind: {
        stage_id: target.stageId,
        question_id: target.questionId,
        image: { url, width, height, order: 1 }
      }
    });
  }

  async function runReport() {
    if (!rehearsal) return;
    const result = await run(() => fetchLessonRehearsalReport(rehearsal.rehearsal_id));
    if (result) setReport(result.report);
  }

  async function complete() {
    if (!rehearsal) return;
    const result = await run(() => completeLessonRehearsal(rehearsal.rehearsal_id, rehearsal.revision));
    if (!result) return;
    setRehearsal(result.rehearsal);
    setCompletedLesson(result.lesson);
    const url = result.export?.artifact?.metadata?.public_url;
    setCompletedExportUrl(typeof url === "string" ? url : "");
    onLessonCommitted(result.lesson);
    await onRefresh();
  }

  async function cancelRehearsal() {
    if (!rehearsal) return;
    if (!window.confirm("取消后本次模拟测试的修改将被丢弃（记录保留），确定取消？")) return;
    const result = await run(() => cancelLessonRehearsal(rehearsal.rehearsal_id));
    if (result) onClose();
  }

  if (completedLesson) {
    const meta = completedLesson.metadata || {};
    return (
      <section className="lesson-panel glass-panel rehearsal-panel" data-testid="rehearsal-panel">
        <header className="lesson-panel-header">
          <div>
            <p className="panel-tag">Lesson Rehearsal</p>
            <h2>模拟测试完成</h2>
          </div>
          <button type="button" className="mini-control" onClick={onClose} aria-label="关闭模拟测试">
            ×
          </button>
        </header>
        <div className="rehearsal-complete" data-testid="rehearsal-complete">
          <p>
            已发布新版本 <strong>v{String(meta.lesson_version || 1)}</strong>：{completedLesson.title}
          </p>
          <p className="ldw-hint">课时已标记「可开真实课堂」，真实课堂将使用当前版本快照。</p>
          <div className="ldw-actions">
            {completedExportUrl ? (
              <a className="toolbar-button compact" href={completedExportUrl} target="_blank" rel="noopener noreferrer">
                下载新版教案 Word
              </a>
            ) : null}
            <button type="button" className="toolbar-button compact primary" onClick={onClose}>
              返回备课工作台
            </button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="lesson-panel glass-panel rehearsal-panel" data-testid="rehearsal-panel">
      <header className="lesson-panel-header">
        <div>
          <p className="panel-tag">Lesson Rehearsal</p>
          <h2>模拟测试工作台</h2>
        </div>
        <button type="button" className="mini-control" onClick={onClose} aria-label="关闭模拟测试">
          ×
        </button>
      </header>
      <div className="rehearsal-banner">
        <span className="rehearsal-chip" data-testid="rehearsal-marker">模拟测试</span>
        <span>试讲数据不进入真实班课与课后报告；完成发布才会写入课时新版本。</span>
      </div>

      {error ? <p className="lesson-design-error" data-testid="rehearsal-error">{error}</p> : null}
      {!rehearsal && !error ? <p className="lesson-empty">正在开启模拟测试…</p> : null}

      {rehearsal ? (
        <>
          <div className="lesson-meta">
            <strong>{workingCopy?.title || lesson.title}</strong>
            <span>
              基于版本 v{rehearsal.base_version} · {stages.length} 个环节 · 共 {totalMinutes} 分钟
              （课时 {durationMinutes} 分钟{totalMinutes === durationMinutes ? " ✓" : " ✗ 不一致"}）
            </span>
          </div>

          <ol className="lesson-stage-list">
            {stages.map((stage, index) => {
              const expanded = expandedStageId === stage.stage_id;
              const editing = editStageId === stage.stage_id;
              const isSwapStage = swapTarget?.stageId === stage.stage_id;              return (
                <li key={stage.stage_id} className={`lesson-stage ${expanded ? "expanded" : ""}`}>
                  <div className="lesson-stage-row" onClick={() => setExpandedStageId(expanded ? "" : stage.stage_id)}>
                    <span className="lesson-stage-index">{index + 1}</span>
                    <span className="lesson-stage-title">
                      <strong>{stage.title}</strong>
                      <em>
                        {editing ? (
                          <span className="lesson-stage-edit" onClick={(event) => event.stopPropagation()}>
                            <input
                              type="number"
                              min={1}
                              max={60}
                              value={editMinutes}
                              onChange={(event) => setEditMinutes(Number(event.target.value) || 1)}
                              aria-label="环节分钟数"
                              data-testid={`rehearsal-minutes-${stage.stage_id}`}
                            />
                            <button
                              type="button"
                              className="toolbar-button compact primary"
                              disabled={busy || !active}
                              onClick={() => void saveStageMinutes(stage)}
                              data-testid={`rehearsal-minutes-save-${stage.stage_id}`}
                            >
                              保存
                            </button>
                          </span>
                        ) : (
                          <>
                            {stage.minutes} 分钟 · 提问 {stage.questions?.length || 0} 题 ·{" "}
                            <button
                              type="button"
                              className="link-button"
                              onClick={(event) => {
                                event.stopPropagation();
                                setEditStageId(stage.stage_id);
                                setEditMinutes(stage.minutes);
                              }}
                            >
                              调整时长
                            </button>
                          </>
                        )}
                      </em>
                    </span>
                  </div>

                  {expanded ? (
                    <div className="lesson-stage-detail">
                      <div className="lesson-stage-block">
                        <span className="lesson-block-label">课中题目</span>
                        {(stage.questions || []).map((question, position) => (
                          <div key={`${question.question_id}-${position}`} className="rehearsal-question">
                            <p>{questionLabel(question)}</p>
                            {question.answer_complete === false ? (
                              <em className="rehearsal-warn">答案或解析缺失：不能进入真实课堂。</em>
                            ) : null}
                            {question.images?.length ? (
                              <small>题图 {question.images.length} 张</small>
                            ) : null}
                            {active ? (
                              <div className="rehearsal-question-actions">
                                <button
                                  type="button"
                                  className="toolbar-button compact"
                                  disabled={busy}
                                  onClick={() => {
                                    setSwapTarget({ stageId: stage.stage_id, position, questionId: question.question_id });
                                    setSwapResults([]);
                                  }}
                                  data-testid={`rehearsal-swap-${stage.stage_id}-${position}`}
                                >
                                  换题
                                </button>
                                <button
                                  type="button"
                                  className="toolbar-button compact"
                                  disabled={busy}
                                  onClick={() => void removeQuestion(stage.stage_id, question.question_id)}
                                >
                                  移除
                                </button>
                                <button
                                  type="button"
                                  className="toolbar-button compact"
                                  disabled={busy}
                                  onClick={() => void pickImage(stage.stage_id, question.question_id)}
                                >
                                  上传题图
                                </button>
                              </div>
                            ) : null}
                          </div>
                        ))}
                        {!stage.questions?.length ? <p className="ldw-hint">本环节暂无课中题目。</p> : null}
                      </div>

                      {isSwapStage ? (
                        <div className="rehearsal-swap" data-testid={`rehearsal-swap-box-${stage.stage_id}`}>
                          <span className="lesson-block-label">换入题库题目（替换第 {(swapTarget?.position ?? 0) + 1} 题）</span>
                          <div className="ldw-search-row">
                            <input
                              value={swapSearch}
                              onChange={(event) => setSwapSearch(event.target.value)}
                              placeholder="考点 / 知识点关键词，例如：人口分布 自然因素"
                              aria-label="换题检索关键词"
                              data-testid="rehearsal-swap-input"
                            />
                            <button
                              type="button"
                              className="toolbar-button compact"
                              disabled={busy || !swapSearch.trim()}
                              onClick={() => void runSwapSearch()}
                              data-testid="rehearsal-swap-search"
                            >
                              检索
                            </button>
                          </div>
                          {swapResults.length ? (
                            <ul className="ldw-candidate-list" data-testid="rehearsal-swap-results">
                              {swapResults.map((item) => (
                                <li key={item.question_id}>
                                  <div className="ldw-candidate-main">
                                    <strong>
                                      {item.number || ""} {item.stem || item.task_text || ""}
                                    </strong>
                                    <small>
                                      {[item.year, item.region].filter(Boolean).join(" · ")}
                                      {item.answer_complete ? " · 答案完备" : " · 答案缺失"}
                                    </small>
                                  </div>
                                  <button
                                    type="button"
                                    className="toolbar-button compact"
                                    disabled={busy || !item.answer_complete}
                                    onClick={() => void swapIn(item.question_id)}
                                    data-testid={`rehearsal-swap-in-${item.question_id}`}
                                  >
                                    换入
                                  </button>
                                </li>
                              ))}
                            </ul>
                          ) : null}
                          <button type="button" className="link-button" onClick={() => setSwapTarget(null)}>
                            收起换题
                          </button>
                        </div>
                      ) : null}

                      {manualStageId === stage.stage_id ? (
                        <div className="rehearsal-manual" data-testid={`rehearsal-manual-${stage.stage_id}`}>
                          <span className="lesson-block-label">手动录入题目（进真实课堂需答案 + 解析）</span>
                          <textarea
                            value={manualForm.text}
                            onChange={(event) => setManualForm((prev) => ({ ...prev, text: event.target.value }))}
                            placeholder="题干"
                            aria-label="手动题目题干"
                          />
                          <textarea
                            value={manualForm.answer}
                            onChange={(event) => setManualForm((prev) => ({ ...prev, answer: event.target.value }))}
                            placeholder="参考答案"
                            aria-label="手动题目参考答案"
                          />
                          <textarea
                            value={manualForm.explanation}
                            onChange={(event) => setManualForm((prev) => ({ ...prev, explanation: event.target.value }))}
                            placeholder="解析"
                            aria-label="手动题目解析"
                          />
                          <div className="lesson-stage-actions">
                            <button
                              type="button"
                              className="toolbar-button compact primary"
                              disabled={busy || !manualForm.text.trim()}
                              onClick={() => void bindManual(stage.stage_id)}
                              data-testid={`rehearsal-manual-bind-${stage.stage_id}`}
                            >
                              加入环节
                            </button>
                            <button type="button" className="toolbar-button compact" onClick={() => setManualStageId("")}>
                              收起
                            </button>
                          </div>
                        </div>
                      ) : null}

                      <div className="lesson-stage-actions">
                        <button
                          type="button"
                          className="toolbar-button compact primary"
                          disabled={busy}
                          onClick={() => void previewScene(stage.stage_id)}
                          data-testid={`rehearsal-preview-${stage.stage_id}`}
                        >
                          预览场景
                        </button>
                        <button
                          type="button"
                          className="toolbar-button compact"
                          disabled={busy || !active}
                          onClick={() => void captureScene(stage.stage_id)}
                        >
                          {captureHint === stage.stage_id ? "✓ 已保存" : "存当前地图为场景"}
                        </button>
                        {active ? (
                          <button
                            type="button"
                            className="toolbar-button compact"
                            disabled={busy}
                            onClick={() => setManualStageId(stage.stage_id)}
                          >
                            手动加题
                          </button>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>

          <div className="rehearsal-checklist" data-testid="rehearsal-checklist">
            <div className="ldw-card-head">
              <strong>试讲检查清单</strong>
              <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => void runReport()} data-testid="rehearsal-report-button">
                运行校验
              </button>
            </div>
            {TEST_ITEMS.map((item) => {
              const entry = rehearsal.test_results?.[item.key];
              return (
                <div key={item.key} className="rehearsal-check-item">
                  <div>
                    <strong>{item.label}</strong>
                    <small>{item.hint}</small>
                  </div>
                  <span className={`rehearsal-check-state ${entry ? (entry.passed ? "ok" : "bad") : ""}`}>
                    {entry ? (entry.passed ? "通过" : "未通过") : "未测"}
                  </span>
                  {active ? (
                    <span className="rehearsal-check-actions">
                      <button
                        type="button"
                        className="toolbar-button compact"
                        disabled={busy}
                        onClick={() => void recordTest(item.key, true)}
                        data-testid={`rehearsal-test-pass-${item.key}`}
                      >
                        通过
                      </button>
                      <button
                        type="button"
                        className="toolbar-button compact"
                        disabled={busy}
                        onClick={() => void recordTest(item.key, false)}
                      >
                        未通过
                      </button>
                    </span>
                  ) : null}
                </div>
              );
            })}
            {report ? (
              <div className={`ldw-report ${report.ready ? "ok" : "bad"}`} data-testid="rehearsal-report">
                <strong>
                  {report.ready
                    ? `校验通过（环节合计 ${report.total_minutes} / 课时 ${report.duration_minutes} 分钟）`
                    : "仍有必须处理的问题"}
                </strong>
                {report.errors?.length ? <small className="ldw-report-errors">必须处理：{report.errors.join("；")}</small> : null}
                {report.warnings?.length ? <small>建议关注：{report.warnings.join("；")}</small> : null}
              </div>
            ) : null}
          </div>

          <div className="rehearsal-footer">
            <button type="button" className="toolbar-button compact" disabled={busy || !active} onClick={() => void cancelRehearsal()} data-testid="rehearsal-cancel">
              取消模拟测试
            </button>
            <button
              type="button"
              className="toolbar-button compact primary"
              disabled={busy || !active}
              onClick={() => void complete()}
              data-testid="rehearsal-complete-button"
            >
              完成并发布
            </button>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            style={{ display: "none" }}
            onChange={(event) => {
              void onImageFile(event.target.files?.[0] || null);
              event.target.value = "";
            }}
            aria-label="上传题图"
          />
        </>
      ) : null}
    </section>
  );
}
