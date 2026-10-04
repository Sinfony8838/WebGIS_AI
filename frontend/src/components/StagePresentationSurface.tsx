import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import "./StagePresentationSurface.css";
import type { LessonStage, PresentationBlock } from "../types";
import { buildAuthenticatedUrl } from "../api";
import { defaultLayoutFromStage, makeBlock, isDirectVideo, isExternalUrl } from "../lib/presentationLayout";

type Props = {
  stage: LessonStage;
  /** 教师控制区决定是否揭示；学生画布不提供揭示操作。 */
  revealConclusions?: boolean;
  /** 课堂正文字号，由教师控制区调整。 */
  fontSize?: number;
  onProjectQuestion?: (questionId: string, stageId: string) => void;
  onPresentScene?: (target: "stage") => void;
};

const BLOCK_LABELS: Record<string, string> = {
  text: "文字",
  image: "图片",
  video: "视频",
  question: "问题",
  chart: "图表",
  map: "地图"
};

function SurfaceBlock({
  block,
  stage,
  onProjectQuestion,
  onPresentScene
}: {
  block: PresentationBlock;
  stage: LessonStage;
  onProjectQuestion?: (questionId: string, stageId: string) => void;
  onPresentScene?: (target: "stage") => void;
}) {
  const [broken, setBroken] = useState(false);
  const asset = block.asset || {};
  useEffect(() => setBroken(false), [asset.url]);
  if (block.type === "map") {
    return (
      <div className="sps-block sps-map">
        <button
          type="button"
          className="toolbar-button compact primary"
          data-testid="sps-map-button"
          onClick={() => onPresentScene?.("stage")}
        >
          {block.text || "打开展示地图"}
        </button>
      </div>
    );
  }
  if (block.type === "question") {
    const question = (stage.questions || []).find((item) => item.question_id === asset.question_id);
    const stem = block.text || question?.text || question?.task_text || "";
    return (
      <div className="sps-block sps-question" data-testid={`sps-question-${asset.question_id || block.id}`}>
        <p className="sps-question-stem">{stem || "未选题"}</p>
        {question?.options?.length ? <ul className="sps-options">{question.options.map((option, index) => <li key={index}>{option}</li>)}</ul> : null}
        {question && onProjectQuestion ? (
          <button type="button" className="toolbar-button compact" onClick={() => onProjectQuestion(question.question_id, stage.stage_id)}>
            投屏答题
          </button>
        ) : null}
        {/* 学生可见：仅题干与选项；答案由教师在投屏流程中主动揭示。 */}
      </div>
    );
  }
  if (block.type === "text") {
    return <div className="sps-block sps-text">{block.text}</div>;
  }
  if (broken || !asset.url) {
    return <div className="sps-block sps-broken">{BLOCK_LABELS[block.type]}素材不可用，请稍后重试</div>;
  }
  if (block.type === "video") {
    if (!isExternalUrl(asset.url) || isDirectVideo(asset.mime_type, asset.url)) {
      return (
        <video
          className="sps-media"
          src={buildAuthenticatedUrl(asset.url)}
          controls
          preload="metadata"
          onError={() => setBroken(true)}
        />
      );
    }
    return (
      <a className="sps-link" href={buildAuthenticatedUrl(asset.url)} target="_blank" rel="noopener noreferrer">
        <span>▶ 打开外部视频</span>
        <small>{asset.name || asset.url}</small>
      </a>
    );
  }
  return (
    <img
      className="sps-media"
      src={buildAuthenticatedUrl(asset.url)}
      alt={asset.name || BLOCK_LABELS[block.type]}
      onError={() => setBroken(true)}
    />
  );
}

// 课堂主区域的环节展示面：仅渲染学生可见区块；无布局时按环节内容生成默认展示。
export function StagePresentationSurface({ stage, revealConclusions = false, fontSize = 40, onProjectQuestion, onPresentScene }: Props) {
  const [reading, setReading] = useState<{ stageId: string; blockId: string } | null>(null);
  const readingRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLButtonElement | null>(null);
  const flow = !Array.isArray(stage.presentation?.blocks);
  const layout = useMemo(() => {
    if (Array.isArray(stage.presentation?.blocks)) return stage.presentation;
    const base = defaultLayoutFromStage({
      ...stage, questions: [],
      knowledge_point: stage.knowledge_point?.trim() === stage.title.trim() ? "" : stage.knowledge_point,
      student_activities: [...new Set(stage.student_activities || [])].filter(activity => activity.trim() !== stage.material?.trim())
    });
    const content = base.blocks.filter(block => !block.teacher_reveal);
    const conclusions = base.blocks.filter(block => block.teacher_reveal);
    const questions = (stage.questions || []).map(question => makeBlock("question", {
      text: question.text || question.task_text || "", asset: { question_id: question.question_id }
    }));
    return { blocks: [...content, ...questions, ...conclusions].map((block, order) => ({ ...block, order })) };
  }, [stage]);
  const blocks = [...layout.blocks].sort((a, b) => a.order - b.order);
  const isConclusion = (block: PresentationBlock) => block.teacher_reveal || (
    block.type === "text" && !!stage.knowledge_conclusion && block.text === `结论：${stage.knowledge_conclusion}`
  );
  const visibleBlocks = blocks.filter(block => (!flow || block.type !== "text" || block.text !== stage.title) && (revealConclusions || !isConclusion(block)));
  // 用环节 id 绑定阅读状态，切环节的首帧也不会挂载上个环节的内容。
  const readingBlock = reading?.stageId === stage.stage_id
    ? visibleBlocks.find(block => block.id === reading.blockId)
    : undefined;
  const readingId = readingBlock?.id;
  useEffect(() => {
    if (!readingId) return;
    readingRef.current?.focus();
    return () => {
      if (openerRef.current?.isConnected) openerRef.current.focus();
    };
  }, [readingId, stage.stage_id]);
  useEffect(() => setReading(null), [stage.stage_id]);
  useEffect(() => {
    if (reading && !readingBlock) setReading(null);
  }, [reading, readingBlock]);
  const textSize = Number.isFinite(fontSize) ? Math.max(28, Math.min(56, fontSize)) : 40;
  const surfaceStyle = {
    "--sps-font-size": `${textSize}px`,
    "--sps-title-size": `${Math.round(textSize * 1.15)}px`
  } as CSSProperties;

  function closeReading() {
    setReading(null);
  }

  function readingKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeReading();
    }
    if (event.key !== "Tab") return;
    const focusable = readingRef.current?.querySelectorAll<HTMLElement>("button, a[href], video[controls], [tabindex='0']");
    if (!focusable?.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === readingRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className={`sps${flow ? " sps-flow" : ""}`} style={surfaceStyle} data-testid="stage-presentation-surface">
      <h2 className="sps-stage-title">{stage.title}</h2>
      <div className="sps-canvas" role="region" aria-label="课堂展示内容" tabIndex={readingBlock ? -1 : 0} aria-hidden={readingBlock ? true : undefined}>
        {visibleBlocks.map((block, index) => (
          <div
            key={`${stage.stage_id}:${block.id}`}
            className="sps-cell"
            style={{ left: `${block.x * 100}%`, top: `${block.y * 100}%`, width: `${block.w * 100}%`, height: `${block.h * 100}%`, zIndex: block.z + 1 }}
          >
            <div className="sps-cell-tools">
              <button
                type="button"
                className="sps-read-button"
                aria-label={`展开${BLOCK_LABELS[block.type]} ${index + 1}`}
                tabIndex={readingBlock ? -1 : 0}
                onClick={event => {
                  openerRef.current = event.currentTarget;
                  setReading({ stageId: stage.stage_id, blockId: block.id });
                }}
              >
                展开阅读
              </button>
            </div>
            <div className="sps-cell-content" tabIndex={readingBlock ? -1 : 0} role="region" aria-label={`${BLOCK_LABELS[block.type]} ${index + 1}`}>
              {/* 展开时只保留一份素材，避免视频在两个区域同时播放。 */}
              {!readingBlock ? <SurfaceBlock block={block} stage={stage} onProjectQuestion={onProjectQuestion} onPresentScene={onPresentScene} /> : null}
            </div>
          </div>
        ))}
      </div>
      {readingBlock ? (
        <div className="sps-reading" role="dialog" aria-modal="true" aria-label={`${BLOCK_LABELS[readingBlock.type]}展开阅读`} tabIndex={-1} ref={readingRef} onKeyDown={readingKeyDown}>
          <header className="sps-reading-header">
            <h3>{stage.title} · {BLOCK_LABELS[readingBlock.type]}</h3>
            <button type="button" className="sps-read-button" onClick={closeReading}>返回展示板</button>
          </header>
          <div className="sps-reading-content" role="region" aria-label="完整内容" tabIndex={0}>
            <SurfaceBlock key={`${stage.stage_id}:${readingBlock.id}`} block={readingBlock} stage={stage} onProjectQuestion={onProjectQuestion} onPresentScene={onPresentScene} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
