import { useEffect, useState } from "react";

type Props = {
  value: string;
  label: string;
  placeholder?: string;
  multiline?: boolean;
  numeric?: boolean;
  disabled?: boolean;
  onSave: (value: string) => void;
  testId?: string;
};

// 表格式教案的单元格：点击展开输入，保存/取消；Esc 取消，Ctrl+Enter 保存。
export function LessonCellEditor({ value, label, placeholder = "", multiline = false, numeric = false, disabled = false, onSave, testId }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  function save() {
    const cleaned = numeric ? draft.replace(/[^0-9]/g, "") : draft.trim();
    if (numeric && (!cleaned || Number(cleaned) < 1)) {
      setDraft(String(value));
      setEditing(false);
      return;
    }
    setEditing(false);
    if (cleaned !== String(value)) onSave(cleaned);
  }

  function cancel() {
    setDraft(value);
    setEditing(false);
  }

  if (!editing) {
    return (
      <button
        type="button"
        className="lse-cell"
        data-testid={testId}
        aria-label={`编辑${label}`}
        disabled={disabled}
        onClick={() => {
          setDraft(value);
          setEditing(true);
        }}
      >
        <span className={value ? "" : "lse-cell-empty"}>{value || placeholder || "点击填写"}</span>
      </button>
    );
  }

  return (
    <span className="lse-cell-editing">
      {multiline ? (
        <textarea
          autoFocus
          value={draft}
          aria-label={label}
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              cancel();
            } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              save();
            }
          }}
        />
      ) : (
        <input
          autoFocus
          type="text"
          value={draft}
          aria-label={label}
          inputMode={numeric ? "numeric" : undefined}
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              cancel();
            } else if (event.key === "Enter") {
              event.preventDefault();
              save();
            }
          }}
        />
      )}
      <span className="lse-cell-actions">
        <button type="button" className="toolbar-button compact" aria-label={`保存${label}`} disabled={disabled} onClick={save}>
          ✓
        </button>
        <button type="button" className="toolbar-button compact" aria-label={`取消编辑${label}`} onClick={cancel}>
          ×
        </button>
      </span>
    </span>
  );
}
