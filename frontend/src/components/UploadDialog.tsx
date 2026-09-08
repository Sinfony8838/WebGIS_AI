import { useCallback, useEffect, useState } from "react";
import "./UploadDialog.css";

type CrsWarning = { code: string; message_zh: string };

type ImportCrsReport = {
  source_crs?: string | null;
  target_crs?: string;
  reprojected?: boolean;
  warnings?: CrsWarning[];
  detection_method?: string;
};

type RowReport = {
  total_rows?: number;
  imported_rows?: number;
  skipped_rows?: number;
  skip_reasons?: Record<string, number>;
  encoding?: string;
  lat_field?: string;
  lon_field?: string;
};

type FeatureReport = {
  total_features?: number;
  imported_features?: number;
  skipped_features?: number;
  skip_reasons?: Record<string, number>;
};

type ImportSummary = {
  layer?: {
    name?: string;
    metadata?: {
      feature_count?: number;
      source_crs?: string | null;
      stored_crs?: string | null;
      crs_converted?: boolean;
    };
  };
  crs?: ImportCrsReport;
  row_report?: RowReport;
  feature_report?: FeatureReport;
  message?: string;
};

type Props = {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  /**
   * Submits the upload. Resolving with an {@link ImportSummary}-shaped
   * payload (as `POST /datasets/upload` already returns) lets the dialog
   * show the detailed Chinese import report; resolving with nothing keeps
   * the legacy behaviour of closing immediately.
   */
  onSubmit: (formData: FormData) => Promise<unknown> | unknown;
};

function isImportSummary(value: unknown): value is ImportSummary {
  return Boolean(value) && typeof value === "object" && "layer" in (value as Record<string, unknown>);
}

export function UploadDialog({ open, busy, onClose, onSubmit }: Props) {
  const [datasetName, setDatasetName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [latField, setLatField] = useState("");
  const [lonField, setLonField] = useState("");
  const [bounds, setBounds] = useState({ west: "", south: "", east: "", north: "" });
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [summary, setSummary] = useState<ImportSummary | null>(null);

  useEffect(() => {
    if (!open) {
      // Reset transient state when the dialog is dismissed/reopened.
      setErrorMessage("");
      setSummary(null);
      setSubmitting(false);
    }
  }, [open]);

  const fileName = file?.name.toLowerCase() || "";
  const isCsv = fileName.endsWith(".csv");
  const isImage = fileName.endsWith(".png") || fileName.endsWith(".jpg") || fileName.endsWith(".jpeg");

  const skipLines = (report: Record<string, number> | undefined) =>
    Object.entries(report || {})
      .sort((a, b) => b[1] - a[1])
      .map(([reason, count]) => `${count} 条${reason}`);

  const handleSubmit = useCallback(async () => {
    if (!file || submitting) {
      return;
    }
    setSubmitting(true);
    setErrorMessage("");
    setSummary(null);
    const formData = new FormData();
    formData.append("file", file);
    if (datasetName.trim()) {
      formData.append("dataset_name", datasetName.trim());
    }
    if (isCsv) {
      // Empty values let the backend auto-detect lat/lon (incl. 纬度/经度).
      if (latField.trim()) formData.append("lat_field", latField.trim());
      if (lonField.trim()) formData.append("lon_field", lonField.trim());
    }
    if (isImage) {
      formData.append("west", bounds.west);
      formData.append("south", bounds.south);
      formData.append("east", bounds.east);
      formData.append("north", bounds.north);
    }
    try {
      const result = await onSubmit(formData);
      if (isImportSummary(result)) {
        // Keep the dialog open and show the detailed import report.
        setSummary(result);
      } else {
        onClose();
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }, [bounds, datasetName, file, isCsv, isImage, latField, lonField, onClose, onSubmit, submitting]);

  if (!open) {
    return null;
  }

  const layerMeta = summary?.layer?.metadata;
  const sourceCrs = summary?.crs?.source_crs ?? layerMeta?.source_crs;
  const storedCrs = summary?.crs?.target_crs ?? layerMeta?.stored_crs;
  const converted = summary?.crs?.reprojected ?? layerMeta?.crs_converted;
  const warnings = summary?.crs?.warnings ?? [];
  const skippedLines = skipLines(summary?.row_report?.skip_reasons ?? summary?.feature_report?.skip_reasons);

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
              <input
                value={latField}
                onChange={(event) => setLatField(event.target.value)}
                placeholder="留空自动识别（lat / 纬度）"
              />
            </label>
            <label className="dialog-field">
              <span>经度字段</span>
              <input
                value={lonField}
                onChange={(event) => setLonField(event.target.value)}
                placeholder="留空自动识别（lon / 经度）"
              />
            </label>
          </div>
        ) : null}

        {isImage ? (
          <div className="dialog-grid">
            <label className="dialog-field">
              <span>西界（经度）</span>
              <input value={bounds.west} onChange={(event) => setBounds({ ...bounds, west: event.target.value })} placeholder="113.0" />
            </label>
            <label className="dialog-field">
              <span>南界（纬度）</span>
              <input value={bounds.south} onChange={(event) => setBounds({ ...bounds, south: event.target.value })} placeholder="22.5" />
            </label>
            <label className="dialog-field">
              <span>东界（经度）</span>
              <input value={bounds.east} onChange={(event) => setBounds({ ...bounds, east: event.target.value })} placeholder="114.3" />
            </label>
            <label className="dialog-field">
              <span>北界（纬度）</span>
              <input value={bounds.north} onChange={(event) => setBounds({ ...bounds, north: event.target.value })} placeholder="23.9" />
            </label>
          </div>
        ) : null}

        {errorMessage ? (
          <div className="upload-dialog-feedback upload-dialog-feedback--error" role="alert">
            <strong>导入失败</strong>
            <span>{errorMessage}</span>
          </div>
        ) : null}

        {summary ? (
          <div className="upload-dialog-feedback upload-dialog-feedback--success" role="status">
            <strong>{summary.message || `已导入图层：${summary.layer?.name ?? "未命名"}`}</strong>
            {typeof summary.row_report?.total_rows === "number" ? (
              <span>
                共 {summary.row_report.total_rows} 行，成功 {summary.row_report.imported_rows ?? 0} 行
                {summary.row_report.skipped_rows ? `，跳过 ${summary.row_report.skipped_rows} 行` : ""}。
              </span>
            ) : null}
            {skippedLines.length > 0 ? <span>跳过明细：{skippedLines.join("；")}。</span> : null}
            {sourceCrs || storedCrs ? (
              <span>
                坐标系：来源 {sourceCrs ?? "未声明"} → 存储 {storedCrs ?? "未声明"}
                {converted ? "（已完成转换）" : "（未转换）"}。
              </span>
            ) : null}
            {warnings.map((warning) => (
              <span key={warning.code} className="upload-dialog-warning">
                ⚠ {warning.message_zh}
              </span>
            ))}
          </div>
        ) : null}

        <div className="dialog-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            {summary ? "关闭" : "取消"}
          </button>
          <button type="button" disabled={busy || submitting || !file || Boolean(summary)} onClick={handleSubmit}>
            {submitting ? "正在导入…" : summary ? "已导入" : "导入到课堂"}
          </button>
        </div>
      </div>
    </div>
  );
}
