import { useState } from "react";
import type { WorkflowPreview } from "../types";

export function WorkflowParameters({ preview, busy, onChange, onReset }: {
  preview: WorkflowPreview | null; busy: boolean;
  onChange: (key: string, value: unknown) => void; onReset: () => void;
}) {
  const [unit, setUnit] = useState("km");
  if (!preview) return null;
  const p = preview.parameters;
  const origin = (key: string) => ({ manual: "已手动设置", message: "来自文字", default: "默认值" }[preview.parameter_sources[key]] || "");
  const field = (key: string, title: string, control: JSX.Element) => (
    <label className="workflow-parameter" key={key}><span>{title}<small>{origin(key)}</small></span>{control}</label>
  );
  return <section className="workflow-parameters" aria-label="执行参数">
    <div className="workflow-parameters__heading"><strong>执行参数</strong>
      <button type="button" onClick={onReset}>恢复文字解析</button></div>
    <p>手动设置优先于文字要求。{busy ? "正在校验…" : "将按下列参数执行。"}</p>
    {preview.template_id === "facility_buffer" && <>
      {field("distance_m", "缓冲距离", <span className="workflow-distance">
        <input aria-label="缓冲距离" type="number" min="0" step="any"
          value={Number(p.distance_m ?? 0) / (unit === "km" ? 1000 : 1)}
          onChange={e => onChange("distance_m", e.target.value === "" ? "" : Number(e.target.value) * (unit === "km" ? 1000 : 1))} />
        <select aria-label="距离单位" value={unit} onChange={e => setUnit(e.target.value)}>
          <option value="km">公里</option><option value="m">米</option>
        </select></span>)}
      {field("dissolve", "合并重叠区域", <input aria-label="合并重叠区域" type="checkbox" checked={Boolean(p.dissolve)}
        onChange={e => onChange("dissolve", e.target.checked)} />)}
      {field("label_field", "标签字段", <select aria-label="标签字段" value={String(p.label_field ?? "")}
        onChange={e => onChange("label_field", e.target.value)}>
        <option value="">使用要素编号</option>{preview.fields.map(f => <option key={f.name} value={f.name}>{f.name}</option>)}
      </select>)}
    </>}
    {preview.template_id === "classify_field" && <>
      {field("field", "分级字段", <select aria-label="分级字段" value={String(p.field ?? "")} onChange={e => onChange("field", e.target.value)}>
        <option value="">请选择数值字段</option>{preview.fields.filter(f => f.numeric).map(f => <option key={f.name} value={f.name}>{f.name}</option>)}
      </select>)}
      {field("method", "分级方法", <select aria-label="分级方法" value={String(p.method ?? "jenks")} onChange={e => onChange("method", e.target.value)}>
        <option value="equal">等距</option><option value="quantile">分位数</option><option value="jenks">自然断点</option><option value="stddev">标准差</option>
      </select>)}
      {field("classes", "分级数", <input aria-label="分级数" type="number" min="2" max="12" step="1"
        value={String(p.classes ?? 5)} onChange={e => onChange("classes", e.target.value)} />)}
      {field("output_field", "输出字段", <input aria-label="输出字段" value={String(p.output_field ?? "")}
        onChange={e => onChange("output_field", e.target.value)} />)}
    </>}
    {preview.issues.length > 0 && <ul role="alert">{preview.issues.map((issue, i) =>
      <li key={i}>{issue.user_friendly || issue.message}</li>)}</ul>}
  </section>;
}
