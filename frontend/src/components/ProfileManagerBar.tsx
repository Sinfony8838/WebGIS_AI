import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import "./ProfileManagerBar.css";

type Props = {
  count: number;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  children: ReactNode;
};

// Only presentation lives here; the map owner keeps measurement and window actions.
export function ProfileManagerBar({ count, collapsed, onToggleCollapsed, children }: Props) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const detailsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!expanded) return;
    detailsRef.current?.querySelector<HTMLElement>("button:not(:disabled), select:not(:disabled), input:not(:disabled), [tabindex='0']")?.focus();
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setExpanded(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [expanded]);
  const visibilityLabel = collapsed ? "恢复显示全部剖面" : "一键暂收全部剖面";
  return (
    <div ref={rootRef} className="profile-manager-bar" data-testid="profile-windows-bar"
      onKeyDown={event => {
        if (event.key === "Escape" && expanded) {
          event.preventDefault();
          event.stopPropagation();
          setExpanded(false);
          toggleRef.current?.focus();
        }
      }}>
      <div ref={detailsRef} id={detailsId} className="profile-manager-details" hidden={!expanded}>
        <strong>剖面管理 · 已测 {count} 条测线</strong>
        {children}
      </div>
      <button type="button" className="profile-manager-toggle" title={visibilityLabel} aria-label={visibilityLabel}
        aria-pressed={collapsed} onClick={onToggleCollapsed} data-testid="profiles-collapse-all">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          {collapsed ? <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M7 16h10M7 12l3-3 3 3 4-5" /></> : <><path d="M5 5h14M5 10h14M5 15h14M9 19l3 3 3-3" /></>}
        </svg>
      </button>
      <button ref={toggleRef} type="button" className="profile-manager-toggle" title={`管理 ${count} 条测线及其剖面窗口`}
        aria-label={expanded ? "收起剖面管理" : "展开剖面管理"} aria-expanded={expanded} aria-controls={detailsId}
        data-testid="profile-manager-toggle" onClick={() => setExpanded(value => !value)}>
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 4v16h16M8 16v-4M12 16V7M16 16v-6M20 16V4" />
        </svg>
        <span className="profile-manager-count" aria-hidden="true">{count}</span>
      </button>
    </div>
  );
}
