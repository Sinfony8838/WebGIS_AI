import { useState } from "react";
import "./PresentationLayoutEditor.css";
import "./StagePresentationSurface.css";
import type { LessonStage, PresentationBlock } from "../types";
import { buildAuthenticatedUrl } from "../api";
import { defaultLayoutFromStage, isDirectVideo, isExternalUrl } from "../lib/presentationLayout";

type Props = {
  stage: LessonStage;
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
          autoPlay
          preload="auto"
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
export function StagePresentationSurface({ stage, onProjectQuestion, onPresentScene }: Props) {
  const layout = stage.presentation || defaultLayoutFromStage(stage);
  const blocks = [...layout.blocks].sort((a, b) => a.order - b.order);
  return (
    <div className="sps" data-testid="stage-presentation-surface">
      <div className="sps-stage-title">
        {stage.title}
        <small> · {stage.minutes} 分钟</small>
      </div>
      <div className="sps-canvas">
        {blocks.map((block) => (
          <div
            key={block.id}
            className="sps-cell"
            style={{ left: `${block.x * 100}%`, top: `${block.y * 100}%`, width: `${block.w * 100}%`, height: `${block.h * 100}%`, zIndex: block.z + 1 }}
          >
            <SurfaceBlock block={block} stage={stage} onProjectQuestion={onProjectQuestion} onPresentScene={onPresentScene} />
          </div>
        ))}
      </div>
    </div>
  );
}
