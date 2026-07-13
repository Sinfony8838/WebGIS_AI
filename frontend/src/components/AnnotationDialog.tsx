import { useEffect, useRef, useState } from "react";

type Props = {
  open: boolean;
  location: [number, number] | null;
  defaultValue?: string;
  onSubmit: (text: string) => void;
  onCancel: () => void;
};

function formatLngLat(value: number, suffix: [string, string]): string {
  const hemisphere = value >= 0 ? suffix[0] : suffix[1];
  return `${Math.abs(value).toFixed(4)}° ${hemisphere}`;
}

export function AnnotationDialog({ open, location, defaultValue = "", onSubmit, onCancel }: Props) {
  const [value, setValue] = useState(defaultValue);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (open) {
      setValue(defaultValue);
      const id = window.setTimeout(() => {
        textareaRef.current?.focus();
        textareaRef.current?.select();
      }, 60);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [open, defaultValue]);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, onCancel]);

  if (!open) {
    return null;
  }

  const trimmed = value.trim();

  return (
    <div
      className="dialog-backdrop annotation-dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onCancel();
        }
      }}
    >
      <div
        className="dialog-panel annotation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="annotation-dialog-title"
      >
        <div className="dialog-panel-header">
          <h3 id="annotation-dialog-title">添加课堂标注</h3>
          <span>该标注将作为教师注释发送给智能助教，并在地图上保留可见标记。</span>
        </div>

        {location ? (
          <div className="annotation-dialog-location" aria-label="标注位置">
            <span className="annotation-dialog-location-label">位置</span>
            <strong>{formatLngLat(location[0], ["E", "W"])}</strong>
            <span className="annotation-dialog-location-sep">·</span>
            <strong>{formatLngLat(location[1], ["N", "S"])}</strong>
          </div>
        ) : null}

        <div className="dialog-field">
          <label htmlFor="annotation-dialog-input">标注内容</label>
          <textarea
            ref={textareaRef}
            id="annotation-dialog-input"
            className="annotation-dialog-input"
            value={value}
            placeholder="例如：此处为长江三角洲核心港群"
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && trimmed) {
                event.preventDefault();
                onSubmit(trimmed);
              }
            }}
          />
          <small className="annotation-dialog-hint">
            <kbd>⌘ / Ctrl</kbd> + <kbd>Enter</kbd> 添加 · <kbd>Esc</kbd> 取消
          </small>
        </div>

        <div className="dialog-actions">
          <button type="button" className="secondary-button" onClick={onCancel}>
            取消
          </button>
          <button
            type="button"
            className="annotation-dialog-submit"
            onClick={() => onSubmit(trimmed)}
            disabled={!trimmed}
          >
            添加标注
          </button>
        </div>
      </div>
    </div>
  );
}
