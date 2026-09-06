import { useEffect, useMemo, useRef, useState } from "react";
import type { DatasetCatalogItem, LayerRecord } from "../types";

type Props = {
  open: boolean;
  onClose: () => void;
  layers: LayerRecord[];
  busy?: boolean;
  onToggleLayer: (layerId: string, visible: boolean) => void;
  onFocusLayer: (layerId: string) => void;
  onDeleteLayer: (layerId: string) => void;
  datasetCatalogItems: DatasetCatalogItem[];
  onLoadDataset: (item: DatasetCatalogItem) => void;
};

function isLoadableCatalogItem(item: DatasetCatalogItem): boolean {
  const format = item.format.toLowerCase();
  const isKnownJoinableCsv = item.id === "world_population_by_country";
  return format === "geojson" || (format === "csv" && (isKnownJoinableCsv || Boolean(item.geometry_source && item.join_key)));
}

/** QGIS 风格的图层管理弹窗：查看、显隐、定位、删除与从一张图数据集添加。 */
export function LayerManager({
  open,
  onClose,
  layers,
  busy = false,
  onToggleLayer,
  onFocusLayer,
  onDeleteLayer,
  datasetCatalogItems,
  onLoadDataset
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    const handlePointer = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        onClose();
      }
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("mousedown", handlePointer);
    window.addEventListener("keydown", handleKey);
    return () => {
      window.removeEventListener("mousedown", handlePointer);
      window.removeEventListener("keydown", handleKey);
    };
  }, [open, onClose]);

  const orderedLayers = useMemo(() => [...layers].sort((left, right) => right.z_index - left.z_index), [layers]);
  const visibleCount = orderedLayers.filter((layer) => layer.visible).length;
  const addableItems = useMemo(() => datasetCatalogItems.filter(isLoadableCatalogItem), [datasetCatalogItems]);

  if (!open) return null;

  return (
    <div className="layer-manager glass-panel" ref={containerRef} data-testid="layer-manager" role="dialog" aria-label="图层管理">
      <header className="layer-manager-header">
        <div>
          <span>LAYERS</span>
          <strong>图层管理</strong>
        </div>
        <button type="button" className="mini-control" onClick={onClose} aria-label="关闭图层管理">
          ×
        </button>
      </header>
      <p className="layer-manager-summary">
        可见 {visibleCount} / 共 {orderedLayers.length} 个图层
      </p>
      <ul className="qgis-layer-list layer-manager-list">
        {orderedLayers.map((layer) => (
          <li key={layer.layer_id} className={`qgis-layer-item${layer.visible ? "" : " layer-item-hidden"}`}>
            <button
              type="button"
              className="layer-manager-eye"
              onClick={() => onToggleLayer(layer.layer_id, !layer.visible)}
              aria-label={layer.visible ? `隐藏 ${layer.name}` : `显示 ${layer.name}`}
              title={layer.visible ? "隐藏图层" : "显示图层"}
            >
              {layer.visible ? "◉" : "○"}
            </button>
            <button
              type="button"
              className="layer-manager-name"
              onClick={() => onFocusLayer(layer.layer_id)}
              title="定位到图层范围"
            >
              {layer.name || layer.layer_id}
            </button>
            <span className="layer-manager-kind">{layer.kind === "raster" ? "栅格" : "矢量"}</span>
            <button
              type="button"
              className="layer-manager-delete"
              disabled={busy}
              onClick={() => {
                const name = layer.name || layer.layer_id;
                if (window.confirm(`确认删除图层「${name}」？删除后可从数据库数据集重新添加。`)) {
                  onDeleteLayer(layer.layer_id);
                }
              }}
              aria-label={`删除 ${layer.name}`}
            >
              删除
            </button>
          </li>
        ))}
        {!orderedLayers.length ? (
          <li className="layer-manager-empty">暂无业务图层，可从下方数据集添加。</li>
        ) : null}
      </ul>
      <div className="layer-manager-add">
        <button
          type="button"
          className="toolbar-button compact"
          onClick={() => setAddOpen((value) => !value)}
          disabled={busy || !addableItems.length}
          data-testid="layer-manager-add-toggle"
        >
          从数据库添加{addableItems.length ? `（${addableItems.length}）` : ""}
        </button>
        {addOpen ? (
          <ul className="layer-manager-add-list" data-testid="layer-manager-add-list">
            {addableItems.map((item) => (
              <li key={item.id}>
                <button type="button" disabled={busy} onClick={() => onLoadDataset(item)}>
                  {item.name || item.id}
                </button>
                <small>{item.category || item.format}</small>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
