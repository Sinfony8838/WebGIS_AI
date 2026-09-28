import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import "./PresentationLayoutEditor.css";
import type { LessonStage, PresentationBlock, PresentationBlockType, PresentationLayout } from "../types";
import { buildAuthenticatedUrl } from "../api";
import { defaultLayoutFromStage, isDirectVideo, isExternalUrl, makeBlock } from "../lib/presentationLayout";

export type LibraryAsset = {
  artifact_id: string;
  title: string;
  url: string;
  mime_type: string;
};

type Props = {
  stage: LessonStage;
  projectId: string;
  busy: boolean;
  libraryAssets: LibraryAsset[];
  onSave: (presentation: PresentationLayout) => void;
};

const INSERTABLE: Array<{ type: PresentationBlockType; label: string }> = [
  { type: "text", label: "文字" },
  { type: "image", label: "图片" },
  { type: "video", label: "视频" },
  { type: "question", label: "问题" },
  { type: "chart", label: "图表" },
  { type: "map", label: "地图" }
];

const BLOCK_LABELS: Record<PresentationBlockType, string> = {
  text: "文字",
  image: "图片",
  video: "视频",
  question: "问题",
  chart: "图表",
  map: "地图"
};

function BlockContent({ block, stage }: { block: PresentationBlock; stage: LessonStage }) {
  const [broken, setBroken] = useState(false);
  const asset = block.asset || {};
  useEffect(() => setBroken(false), [asset.url]);
  if (block.type === "text" || block.type === "map") {
    return <div className="ple-text">{block.text || (block.type === "map" ? "当前地图场景" : "双击下方编辑文字")}</div>;
  }
  if (block.type === "question") {
    const question = (stage.questions || []).find((item) => item.question_id === asset.question_id);
    return (
      <div className="ple-text">
        <span className="ple-tag">题</span>
        {block.text || question?.text || "未选题"}
      </div>
    );
  }
  if (broken || !asset.url) {
    return <div className="ple-placeholder">{BLOCK_LABELS[block.type]}：素材不可用</div>;
  }
  if (block.type === "video") {
    if (!isExternalUrl(asset.url) || isDirectVideo(asset.mime_type, asset.url)) {
      return (
        <video
          src={buildAuthenticatedUrl(asset.url)}
          controls
          preload="metadata"
          onError={() => setBroken(true)}
          className="ple-media"
        />
      );
    }
    return (
      <a className="ple-link-card" href={buildAuthenticatedUrl(asset.url)} target="_blank" rel="noopener noreferrer">
        <span>▶ 外部视频</span>
        <small>{asset.name || asset.url}</small>
      </a>
    );
  }
  return (
    <img
      src={buildAuthenticatedUrl(asset.url)}
      alt={asset.name || BLOCK_LABELS[block.type]}
      onError={() => setBroken(true)}
      className="ple-media"
    />
  );
}

// 环节展示布局编辑器：插入/拖动/缩放/排序区块，保存到预演工作副本。
export function PresentationLayoutEditor({ stage, projectId, busy, libraryAssets, onSave }: Props) {
  const stageRef = useRef(stage);
  stageRef.current = stage;
  const [layout, setLayout] = useState<PresentationLayout>(() => stage.presentation || defaultLayoutFromStage(stage));
  const [selectedId, setSelectedId] = useState("");
  const [picker, setPicker] = useState<"image" | "video" | "question" | "">("");
  const [videoLink, setVideoLink] = useState("");
  const [dirty, setDirty] = useState(false);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ id: string; mode: "move" | "resize"; startX: number; startY: number; origin: PresentationBlock } | null>(null);
  const videoInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setLayout(stageRef.current.presentation || defaultLayoutFromStage(stageRef.current));
    setDirty(false);
    setSelectedId("");
  }, [stage.stage_id]);

  const sortedBlocks = useMemo(() => [...layout.blocks].sort((a, b) => a.order - b.order), [layout.blocks]);

  function updateBlock(blockId: string, patch: Partial<PresentationBlock>) {
    setLayout((previous) => ({
      blocks: previous.blocks.map((block) => (block.id === blockId ? { ...block, ...patch } : block))
    }));
    setDirty(true);
  }

  function addBlock(type: PresentationBlockType) {
    const block = makeBlock(type, {
      order: layout.blocks.length,
      x: 0.28,
      y: 0.32,
      w: type === "text" ? 0.4 : 0.34,
      h: type === "text" ? 0.16 : 0.3
    });
    setLayout((previous) => ({ blocks: [...previous.blocks, block] }));
    setSelectedId(block.id);
    setDirty(true);
  }

  function attachAsset(asset: { url?: string; mime_type?: string; name?: string; question_id?: string }) {
    const target = sortedBlocks.find((block) => block.id === selectedId && ["image", "video", "chart", "question"].includes(block.type));
    if (target) {
      updateBlock(target.id, { asset });
      setPicker("");
      return;
    }
    const type: PresentationBlockType = asset.question_id ? "question" : "image";
    const block = makeBlock(type, { order: layout.blocks.length, x: 0.3, y: 0.34, w: 0.4, h: 0.32, asset });
    setLayout((previous) => ({ blocks: [...previous.blocks, block] }));
    setSelectedId(block.id);
    setDirty(true);
    setPicker("");
  }

  function removeSelected() {
    if (!selectedId) return;
    setLayout((previous) => ({ blocks: previous.blocks.filter((block) => block.id !== selectedId) }));
    setSelectedId("");
    setDirty(true);
  }

  function reorder(direction: 1 | -1) {
    const target = sortedBlocks.find((block) => block.id === selectedId);
    if (!target) return;
    const others = sortedBlocks.filter((block) => block.id !== selectedId);
    const index = sortedBlocks.findIndex((block) => block.id === selectedId);
    const insertAt = Math.max(0, Math.min(others.length, index + (direction === 1 ? 1 : -1)));
    const next = [...others];
    next.splice(insertAt, 0, { ...target, order: 0 });
    setLayout({ blocks: next.map((block, position) => ({ ...block, order: position })) });
    setDirty(true);
  }

  function onPointerDown(event: ReactPointerEvent, block: PresentationBlock, mode: "move" | "resize") {
    if (busy) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedId(block.id);
    dragRef.current = { id: block.id, mode, startX: event.clientX, startY: event.clientY, origin: { ...block } };
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event: ReactPointerEvent) {
    const drag = dragRef.current;
    const canvas = canvasRef.current;
    if (!drag || !canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const dx = (event.clientX - drag.startX) / rect.width;
    const dy = (event.clientY - drag.startY) / rect.height;
    const clamp01 = (value: number) => Math.min(1, Math.max(0, value));
    if (drag.mode === "move") {
      updateBlock(drag.id, {
        x: clamp01(drag.origin.x + dx),
        y: clamp01(drag.origin.y + dy)
      });
    } else {
      updateBlock(drag.id, {
        w: Math.min(1, Math.max(0.05, drag.origin.w + dx)),
        h: Math.min(1, Math.max(0.05, drag.origin.h + dy))
      });
    }
  }

  function onPointerUp() {
    dragRef.current = null;
  }

  function resetToDefault() {
    setLayout(defaultLayoutFromStage(stageRef.current));
    setSelectedId("");
    setDirty(true);
  }

  const selected = sortedBlocks.find((block) => block.id === selectedId);

  return (
    <div className="ple" data-testid={`ple-${stage.stage_id}`}>
      <div className="ple-toolbar">
        {INSERTABLE.map(({ type, label }) => (
          <button
            key={type}
            type="button"
            className="toolbar-button compact"
            disabled={busy}
            aria-label={`插入${label}区块`}
            onClick={() => {
              if (type === "image" || type === "chart") {
                setPicker(picker === "image" ? "" : "image");
              } else if (type === "video") {
                setPicker(picker === "video" ? "" : "video");
              } else if (type === "question") {
                setPicker(picker === "question" ? "" : "question");
              } else {
                addBlock(type);
              }
            }}
          >
            {label}
          </button>
        ))}
        <span className="ple-spacer" />
        <button type="button" className="toolbar-button compact" disabled={busy} onClick={resetToDefault}>
          生成默认布局
        </button>
        <button
          type="button"
          className="toolbar-button compact primary"
          disabled={busy || !dirty || !layout.blocks.length}
          onClick={() => onSave({ blocks: layout.blocks })}
          data-testid="ple-save"
        >
          保存展示编排
        </button>
      </div>
      {picker === "image" ? (
        <div className="ple-picker" data-testid="ple-image-picker">
          {libraryAssets.length ? (
            libraryAssets.map((asset) => (
              <button
                key={asset.artifact_id}
                type="button"
                className="ple-picker-item"
                disabled={busy}
                onClick={() => attachAsset({ url: asset.url, mime_type: asset.mime_type, name: asset.title })}
              >
                <img src={buildAuthenticatedUrl(asset.url)} alt={asset.title} />
                <small>{asset.title}</small>
              </button>
            ))
          ) : (
            <span className="ple-hint">项目图片库为空，可先在地图面板上传图片。</span>
          )}
          <span className="ple-hint">图表区块同样引用图片快照；选中已有图片/图表区块后再点选可直接替换素材。</span>
        </div>
      ) : null}
      {picker === "video" ? (
        <div className="ple-picker" data-testid="ple-video-picker">
          <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => videoInputRef.current?.click()}>
            上传视频（MP4/WebM ≤100MB）
          </button>
          <input
            ref={videoInputRef}
            type="file"
            accept=".mp4,.webm"
            hidden
            aria-label="选择视频文件"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              import("../api").then(({ uploadVideoAsset }) =>
                uploadVideoAsset(projectId, file, `${stage.title} 视频`)
                  .then((result) => {
                    const url = String(result.artifact.metadata?.public_url || "");
                    if (url) attachAsset({ url, mime_type: String(result.artifact.metadata?.mime_type || "video/mp4"), name: file.name });
                  })
                  .catch(() => undefined)
              );
            }}
          />
          <span className="ple-hint">或填写 https 直链：</span>
          <input
            type="text"
            value={videoLink}
            aria-label="视频 https 链接"
            placeholder="https://…/intro.mp4"
            onChange={(event) => setVideoLink(event.target.value)}
          />
          <button
            type="button"
            className="toolbar-button compact"
            disabled={busy || !videoLink.trim()}
            onClick={() => {
              attachAsset({ url: videoLink.trim(), name: "外部链接" });
              setVideoLink("");
            }}
          >
            使用链接
          </button>
        </div>
      ) : null}
      {picker === "question" ? (
        <div className="ple-picker" data-testid="ple-question-picker">
          {(stage.questions || []).length ? (
            (stage.questions || []).map((question) => (
              <button
                key={question.question_id}
                type="button"
                className="toolbar-button compact"
                disabled={busy}
                onClick={() => attachAsset({ question_id: question.question_id })}
              >
                {question.text || question.task_text || question.question_id}
              </button>
            ))
          ) : (
            <span className="ple-hint">本环节还没有题目；请先在「课中题目」里检索或录入。</span>
          )}
        </div>
      ) : null}
      <div
        className="ple-canvas"
        ref={canvasRef}
        data-testid="ple-canvas"
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        {sortedBlocks.map((block) => (
          <div
            key={block.id}
            className={`ple-block ${block.id === selectedId ? "selected" : ""}`}
            style={{ left: `${block.x * 100}%`, top: `${block.y * 100}%`, width: `${block.w * 100}%`, height: `${block.h * 100}%`, zIndex: block.z + 1 }}
            data-testid={`ple-block-${block.id}`}
            onPointerDown={(event) => onPointerDown(event, block, "move")}
          >
            <div className="ple-block-head">
              <span>{BLOCK_LABELS[block.type]}</span>
              {block.type === "text" ? (
                <input
                  value={block.text || ""}
                  aria-label={`区块文字（${block.id}）`}
                  disabled={busy}
                  onClick={(event) => event.stopPropagation()}
                  onPointerDown={(event) => event.stopPropagation()}
                  onChange={(event) => updateBlock(block.id, { text: event.target.value })}
                />
              ) : null}
            </div>
            <div className="ple-block-body">
              <BlockContent block={block} stage={stageRef.current} />
            </div>
            {block.id === selectedId ? (
              <span
                className="ple-resize-handle"
                aria-label={`缩放区块（${block.id}）`}
                onPointerDown={(event) => onPointerDown(event, block, "resize")}
              />
            ) : null}
          </div>
        ))}
      </div>
      {selected ? (
        <div className="ple-selection" data-testid="ple-selection">
          <span>选中：{BLOCK_LABELS[selected.type]}（{selected.id.slice(-6)}）</span>
          <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => reorder(-1)}>
            上移层级
          </button>
          <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => reorder(1)}>
            下移层级
          </button>
          <button type="button" className="toolbar-button compact" disabled={busy} onClick={() => setPicker("image")}>
            替换素材
          </button>
          <button type="button" className="toolbar-button compact" disabled={busy} onClick={removeSelected}>
            删除区块
          </button>
        </div>
      ) : null}
    </div>
  );
}
