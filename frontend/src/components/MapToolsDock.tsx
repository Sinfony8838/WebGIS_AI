import { useId, useState, type ReactNode } from "react";
import "./MapToolsDock.css";

export function MapToolsDock({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const contentId = useId();
  return (
    <aside className={`right-rail map-tools-dock${collapsed ? " is-collapsed" : ""}`} aria-label="地图工具与可视化地图">
      <button type="button" className="map-tools-dock-toggle glass-panel"
        aria-expanded={!collapsed} aria-controls={contentId}
        aria-label={collapsed ? "展开地图工具与可视化地图" : "收起地图工具与可视化地图"}
        title={collapsed ? "展开地图工具与可视化地图" : "一并收起地图工具与可视化地图"}
        onClick={() => setCollapsed(value => !value)}>
        <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d={collapsed ? "m12 5-5 5 5 5" : "m8 5 5 5-5 5"} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        <span>{collapsed ? "工具" : "收起工具"}</span>
      </button>
      <div id={contentId} className="map-tools-dock-content" hidden={collapsed}>{children}</div>
    </aside>
  );
}
