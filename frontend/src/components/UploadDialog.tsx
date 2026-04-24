import { useState } from "react";

type Props = {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onSubmit: (formData: FormData) => Promise<void>;
};

export function UploadDialog({ open, busy, onClose, onSubmit }: Props) {
  const [datasetName, setDatasetName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [latField, setLatField] = useState("lat");
  const [lonField, setLonField] = useState("lon");
  const [bounds, setBounds] = useState({ west: "", south: "", east: "", north: "" });

  if (!open) {
    return null;
  }

  const fileName = file?.name.toLowerCase() || "";
  const isCsv = fileName.endsWith(".csv");
  const isImage = fileName.endsWith(".png") || fileName.endsWith(".jpg") || fileName.endsWith(".jpeg");

  return (
    <div className="dialog-backdrop" role="presentation" onClick={onClose}>
      <div className="dialog-panel" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <div className="dialog-panel-header">
          <p className="panel-tag">Dataset Upload</p>
          <h3>导入课堂数据</h3>
          <span>支持 GeoJSON、CSV、栅格图片覆盖层和 ZIP Shapefile。</span>
        </div>

        <label className="dialog-field">
          <span>数据名称</span>
          <input value={datasetName} onChange={(event) => setDatasetName(event.target.value)} placeholder="例如：课堂调查点位" />
        </label>

        <label className="dialog-field">
          <span>选择文件</span>
          <input type="file" onChange={(event) => setFile(event.target.files?.[0] || null)} />
        </label>

        {isCsv ? (
          <div className="dialog-grid">
            <label className="dialog-field">
              <span>纬度字段</span>
              <input value={latField} onChange={(event) => setLatField(event.target.value)} />
            </label>
            <label className="dialog-field">
              <span>经度字段</span>
              <input value={lonField} onChange={(event) => setLonField(event.target.value)} />
            </label>
          </div>
        ) : null}

        {isImage ? (
          <div className="dialog-grid">
            <label className="dialog-field">
              <span>西界</span>
              <input value={bounds.west} onChange={(event) => setBounds({ ...bounds, west: event.target.value })} />
            </label>
            <label className="dialog-field">
              <span>南界</span>
              <input value={bounds.south} onChange={(event) => setBounds({ ...bounds, south: event.target.value })} />
            </label>
            <label className="dialog-field">
              <span>东界</span>
              <input value={bounds.east} onChange={(event) => setBounds({ ...bounds, east: event.target.value })} />
            </label>
            <label className="dialog-field">
              <span>北界</span>
              <input value={bounds.north} onChange={(event) => setBounds({ ...bounds, north: event.target.value })} />
            </label>
          </div>
        ) : null}

        <div className="dialog-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            disabled={busy || !file}
            onClick={async () => {
              if (!file) {
                return;
              }

              const formData = new FormData();
              formData.append("file", file);
              if (datasetName.trim()) {
                formData.append("dataset_name", datasetName.trim());
              }
              if (isCsv) {
                formData.append("lat_field", latField);
                formData.append("lon_field", lonField);
              }
              if (isImage) {
                formData.append("west", bounds.west);
                formData.append("south", bounds.south);
                formData.append("east", bounds.east);
                formData.append("north", bounds.north);
              }
              await onSubmit(formData);
              onClose();
            }}
          >
            导入到课堂
          </button>
        </div>
      </div>
    </div>
  );
}
