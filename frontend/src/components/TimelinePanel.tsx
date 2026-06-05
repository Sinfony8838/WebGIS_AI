import { useRef } from "react";
import type { TimelineData, TimelineNode } from "../types";

type Props = {
  timeline: TimelineData | null;
  loading: boolean;
  onImport: (file: File) => void;
  onNodeClick: (nodeId: string) => void;
  onManualCreate: () => void;
};

export function TimelinePanel({
  timeline,
  loading,
  onImport,
  onNodeClick,
  onManualCreate,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const openFilePicker = () => fileInputRef.current?.click();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onImport(file);
    e.target.value = "";
  };

  if (loading) {
    return (
      <div className="timeline-loading">
        <span className="timeline-spinner" />
        <span>正在分析教案…</span>
      </div>
    );
  }

  if (!timeline) {
    return (
      <div className="timeline-empty">
        <p>导入教案文件以自动生成教学流程</p>
        <div className="timeline-import-actions">
          <button type="button" className="timeline-import-btn" onClick={openFilePicker}>
            导入教案文件
          </button>
          <button type="button" className="timeline-manual-btn" onClick={onManualCreate}>
            手动创建
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pptx,.pdf,.txt,.md"
          hidden
          onChange={handleFileChange}
        />
        <p className="timeline-hint">支持 .pptx / .pdf / .txt 格式</p>
      </div>
    );
  }

  const activeIndex = timeline.nodes.findIndex((n) => n.active);
  const progressPercent =
    timeline.nodes.length > 1
      ? (activeIndex / (timeline.nodes.length - 1)) * 100
      : 0;

  return (
    <div className="timeline-container">
      <div className="timeline-header">
        <div className="timeline-header-text">
          <strong>{timeline.title}</strong>
          <small>
            {timeline.totalDurationMin} 分钟 · {timeline.nodes.length} 个阶段
          </small>
        </div>
        <button type="button" className="timeline-reimport-btn" onClick={openFilePicker}>
          重新导入
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pptx,.pdf,.txt,.md"
          hidden
          onChange={handleFileChange}
        />
      </div>

      <div className="timeline-progress-bar">
        <div
          className="timeline-progress-fill"
          style={{ width: `${progressPercent}%` }}
        />
      </div>

      <div className="timeline-track">
        {timeline.nodes.map((node, index) => (
          <TimelineNodeRow
            key={node.id}
            node={node}
            index={index}
            isLast={index === timeline.nodes.length - 1}
            onClick={() => onNodeClick(node.id)}
          />
        ))}
      </div>
    </div>
  );
}

function TimelineNodeRow({
  node,
  index,
  isLast,
  onClick,
}: {
  node: TimelineNode;
  index: number;
  isLast: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`timeline-node${node.active ? " active" : ""}`}
      onClick={onClick}
    >
      <div className="timeline-node-track">
        {index > 0 && <div className="timeline-node-line timeline-node-line-top" />}
        <div className={`timeline-node-dot${node.active ? " active" : ""}`} />
        {!isLast && <div className="timeline-node-line timeline-node-line-bottom" />}
      </div>

      <div className="timeline-node-content">
        <div className="timeline-node-meta">
          <span className="timeline-node-stage">{node.stage}</span>
          <span className="timeline-node-duration">{node.durationMin}分钟</span>
        </div>
        <strong className="timeline-node-title">{node.title}</strong>
        {node.description ? (
          <p className="timeline-node-desc">{node.description}</p>
        ) : null}
      </div>
    </button>
  );
}
