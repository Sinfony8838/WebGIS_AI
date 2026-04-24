import { useEffect, useMemo, useRef, useState } from "react";
import type { BasemapPreset } from "../types";

type Props = {
  items: BasemapPreset[];
  activeId: string;
  disabled?: boolean;
  onSelect: (basemapId: string) => void | Promise<void>;
};

export function BasemapMenu({ items, activeId, disabled = false, onSelect }: Props) {
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);

  const activeItem = useMemo(
    () => items.find((item) => item.id === activeId) || items[0] || null,
    [activeId, items]
  );

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  return (
    <div className="basemap-menu" ref={menuRef}>
      <button
        type="button"
        className={`toolbar-button basemap-trigger ${open ? "active" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled || !items.length}
        onClick={() => setOpen((value) => !value)}
      >
        {`底图 · ${activeItem?.title || "未连接"}`}
      </button>

      {open ? (
        <div className="basemap-menu-panel glass-panel" role="menu" aria-label="底图选择">
          {items.map((item) => {
            const selected = item.id === activeId;
            return (
              <button
                key={item.id}
                type="button"
                role="menuitemradio"
                aria-checked={selected}
                className={`basemap-option ${selected ? "active" : ""}`}
                onClick={async () => {
                  await onSelect(item.id);
                  setOpen(false);
                }}
              >
                <strong>{item.title}</strong>
                <span>{item.description}</span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
