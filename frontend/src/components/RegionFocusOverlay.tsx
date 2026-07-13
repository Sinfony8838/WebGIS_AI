import type { TeachingMaterial } from "../types";

type Props = {
  label: string;
  pixel: [number, number] | null;
  materials: TeachingMaterial[];
  onOpenMaterials: () => void;
};

export function RegionFocusOverlay({ label, pixel, materials, onOpenMaterials }: Props) {
  if (!pixel) {
    return null;
  }
  return (
    <div className="region-focus-overlay" style={{ left: pixel[0], top: pixel[1] }} data-testid="region-focus-overlay">
      <div className="region-focus-label">{label || "已选地区"}</div>
      {materials.length ? (
        <button type="button" className="region-material-arrow" onClick={onOpenMaterials} aria-label="打开地区教学资料">
          ›
          <span>{materials.length}</span>
        </button>
      ) : null}
    </div>
  );
}
