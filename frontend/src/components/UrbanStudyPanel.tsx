import { useState } from "react";
import "./UrbanStudyPanel.css";

export type UrbanSource = { url: string; credit: string; kind: "photogrammetry" | "buildings"; format?: "geojson" };
export const SHANGHAI_BUILDINGS: UrbanSource = {
  url: "/data/shanghai-buildings.geojson",
  credit: "© OpenStreetMap contributors · ODbL · 2026-09-09 数据快照",
  kind: "buildings",
  format: "geojson"
};
export type UrbanStatus = "idle" | "loading" | "manifest" | "visible" | "error";
export const SHANGHAI_STOPS = [
  { name: "陆家嘴", lon: 121.505, lat: 31.237, range: 2600, question: "观察高层建筑与交通联系：商务集聚是否等于常住人口密集？" },
  { name: "中心城区", lon: 121.473, lat: 31.230, range: 2300, question: "比较商务、居住与公共空间。解释人口分布还需要哪些街道或栅格统计？" },
  { name: "松江新城", lon: 121.225, lat: 31.030, range: 2600, question: "与中心城区对照建筑形态、轨道交通和用地；讨论新城如何承接居住与就业。" }
];
export type UrbanStop = typeof SHANGHAI_STOPS[number];

const STATUS: Record<UrbanStatus, string> = {
  idle: "尚未加载三维数据",
  loading: "正在连接数据源…",
  manifest: "数据目录已连接，正在读取当前视野瓦片…",
  visible: "三维数据已加载，可旋转和缩放观察",
  error: "加载失败，请检查数据覆盖、访问权限与跨域配置"
};

type Props = {
  active: boolean;
  source: UrbanSource | null;
  status: UrbanStatus;
  onVisit: (stop: UrbanStop) => void;
  onSource: (source: UrbanSource | null) => void;
  onExit: () => void;
};

export function UrbanStudyPanel({ active, source, status, onVisit, onSource, onExit }: Props) {
  const [selected, setSelected] = useState(0);
  const [sampleOpen, setSampleOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [credit, setCredit] = useState("");
  const [kind, setKind] = useState<UrbanSource["kind"]>("photogrammetry");
  const [error, setError] = useState("");

  return (
    <section className="visual-map-topic urban-study-panel" data-testid="urban-study-section">
      <div className="visual-map-topic-title">城市三维实景</div>
      <p className="urban-study-intro">接入有来源署名的 3D Tiles 实景；内置上海数据仅用于演示建筑形态。</p>
      <div className="urban-study-entry-grid">
        <button type="button" className={connectOpen ? "active" : ""} aria-expanded={connectOpen} onClick={() => setConnectOpen((value) => !value)}>
          <span className="visual-map-badge visual-map-badge-3d" aria-hidden>3D</span>
          接入 3D Tiles 实景
        </button>
        <button type="button" className={sampleOpen ? "active" : ""} aria-expanded={sampleOpen} onClick={() => setSampleOpen((value) => !value)}>
          <span className="visual-map-badge visual-map-quality-badge" aria-hidden>示例</span>
          上海建筑模型
        </button>
      </div>

      {connectOpen ? (
        <form
          className="urban-study-form"
          onSubmit={(event) => {
            event.preventDefault();
            try {
              const parsed = new URL(url);
              if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || !credit.trim()) throw new Error();
              setError("");
              onSource({ url: parsed.href, credit: credit.trim(), kind });
            } catch {
              setError("请填写有效的 HTTP(S) 3D Tiles 地址和来源署名。");
            }
          }}
        >
          <label>3D Tiles 地址<input type="url" required value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://…/tileset.json" autoComplete="off" /></label>
          <label>数据来源与署名<input required maxLength={160} value={credit} onChange={(event) => setCredit(event.target.value)} placeholder="数据提供方 / 采集年份" /></label>
          <label>数据类型<select value={kind} onChange={(event) => setKind(event.target.value as UrbanSource["kind"])}><option value="photogrammetry">倾斜摄影 / 实景网格</option><option value="buildings">建筑模型（非实景）</option></select></label>
          <p>地址仅保留在本次页面会话；数据覆盖范围与采集年份须向提供方核实。</p>
          {error ? <p role="alert">{error}</p> : null}
          <button type="submit">连接并定位数据</button>
        </form>
      ) : null}

      {sampleOpen ? (
        <div className="urban-study-sample">
          <strong>上海建筑模型示例</strong>
          <p className="urban-study-warning">非倾斜摄影实景、非人口数据。建筑高度不能直接代表常住人口密度。</p>
          <div className="urban-study-stops">
            {SHANGHAI_STOPS.map((stop, index) => (
              <button
                key={stop.name}
                type="button"
                aria-pressed={active && source?.format === "geojson" && selected === index}
                onClick={() => {
                  setSelected(index);
                  onVisit(stop);
                  onSource(SHANGHAI_BUILDINGS);
                }}
              >
                {stop.name}
              </button>
            ))}
          </div>
          <p>{SHANGHAI_STOPS[selected].question}</p>
          {source?.format === "geojson" ? <p>青绿为 OSM 标注高度，蓝色为楼层数估算，灰色为高度缺失轮廓；仅为局部样本。</p> : null}
          <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap 数据许可</a>
        </div>
      ) : null}

      {(active || source) ? (
        <div className="urban-study-status" role="status">
          <span>{STATUS[status]}{source ? ` · ${source.kind === "photogrammetry" ? "实景网格数据源" : "建筑模型（非实景）"}` : ""}</span>
          {source ? <small>来源：{source.credit}</small> : null}
          <button type="button" className="urban-study-exit" onClick={onExit}>退出城市三维观察</button>
        </div>
      ) : null}
    </section>
  );
}
