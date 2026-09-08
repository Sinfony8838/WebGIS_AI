export const DENSITY_SCALE = [
  { max:10, color:"#e8f4f2", label:"<10" },
  { max:100, color:"#b6ddd7", label:"10–<100" },
  { max:400, color:"#68b7ad", label:"100–<400" },
  { max:800, color:"#288b87", label:"400–<800" },
  { max:Infinity, color:"#07575f", label:"≥800" },
];
export function densityColor(value: unknown): string {
  if (value == null || value === "" || !Number.isFinite(Number(value)) || Number(value) < 0) return "#dbe1e6";
  return (DENSITY_SCALE.find(item => Number(value) < item.max) || DENSITY_SCALE[4]).color;
}
export function densityRadius(value: unknown): number {
  const density = Math.max(0, Number(value) || 0);
  return Math.max(4, Math.min(24, Math.sqrt(density) * 0.55));
}
export function rankColor(rank: number, count = 20): string {
  const t = Math.max(0, Math.min(1, (rank - 1) / Math.max(1, count - 1)));
  const a = [39,76,119], b = [183,201,226];
  return `#${a.map((start,index) => Math.round(start + (b[index]-start)*t).toString(16).padStart(2,"0")).join("")}`;
}

// District averages need their own scale; provincial breaks would saturate Shanghai.
export const SHANGHAI_DENSITY_SCALE = [
  { max:1000, color:'#edf6f3', label:'<1千' },
  { max:5000, color:'#b8ded4', label:'1千–<5千' },
  { max:10000, color:'#70bbae', label:'5千–<1万' },
  { max:20000, color:'#2e9187', label:'1万–<2万' },
  { max:Infinity, color:'#095c61', label:'≥2万' },
];
export function shanghaiDensityColor(value: unknown): string {
  if (value == null || value === '' || !Number.isFinite(Number(value)) || Number(value) < 0) return '#dbe1e6';
  return (SHANGHAI_DENSITY_SCALE.find(item => Number(value) < item.max) || SHANGHAI_DENSITY_SCALE[4]).color;
}
