import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { fetchQuestionBanks, fetchQuestionBankQuestions, type ClassroomPresentationTarget } from "../api";
import type { QuestionBankQuestion } from "../types";

const PHOTOS = [
  { target: "lujiazui" as const, title: "陆家嘴 · 高层商务景观", date: "2019-11-12", author: "Balon Greyjoy", license: "CC0 1.0", licenseUrl: "https://creativecommons.org/publicdomain/zero/1.0/", source: "https://commons.wikimedia.org/wiki/File:20191112_Lujiazui_skyline-3.jpg", image: "https://upload.wikimedia.org/wikipedia/commons/a/a4/20191112_Lujiazui_skyline-3.jpg", note: "从外滩拍摄的天际线；定位对象是陆家嘴，非拍摄机位。高层办公建筑不能直接代表常住人口密集。" },
  { target: "zhujiajiao" as const, title: "朱家角 · 低层滨水景观", date: "2018-04-01", author: "Pauloleong2002", license: "CC BY-SA 4.0", licenseUrl: "https://creativecommons.org/licenses/by-sa/4.0/", source: "https://commons.wikimedia.org/wiki/File:Houses_at_Zhujiajiao.jpg", image: "https://upload.wikimedia.org/wikipedia/commons/d/de/Houses_at_Zhujiajiao.jpg", note: "上海郊区古镇的低层建筑示例；不是整个郊区的代表样本，也不能仅凭楼低就判定人口稀疏。" }
];
const TABS = ["真题引入", "地图与年龄结构", "景观对照", "解释与拓展"];

function LandscapePhoto({ photo }: { photo: typeof PHOTOS[number] }) {
  const [failed, setFailed] = useState(false);
  return <figure className="shanghai-landscape">
    {failed ? <p role="status">照片暂时无法加载，可打开来源查看；地图影像仍可使用。</p> : <img src={photo.image} alt={photo.title} onError={() => setFailed(true)} loading="lazy" referrerPolicy="no-referrer" />}
    <figcaption><strong>{photo.title}</strong><p>{photo.note}</p>
      <small>{photo.date} · {photo.author} · <a href={photo.licenseUrl} target="_blank" rel="noreferrer">{photo.license}</a> · 原图未修改 · <a href={photo.source} target="_blank" rel="noreferrer">照片来源</a></small>
    </figcaption>
  </figure>;
}

export function ShanghaiPopulationInquiry({ projectId, onPresent, onAssistantPrompt, onClose }: {
  projectId: string;
  onPresent: (target: ClassroomPresentationTarget) => Promise<void>;
  onAssistantPrompt?: (prompt: string, display?: string) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState(0);
  const [collapsed, setCollapsed] = useState(false);
  const [questions, setQuestions] = useState<QuestionBankQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [mapError, setMapError] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [selectedPhoto, setSelectedPhoto] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setLoadError(""); setQuestions([]); setRevealed(false);
    void (async () => {
      try {
        const banks = await fetchQuestionBanks(projectId);
        const groups = await Promise.all(banks.items.map(bank => fetchQuestionBankQuestions(bank.bank_id, { search: "年轻环", pageSize: 100 })));
        const found = groups.flatMap(group => group.items).filter(q => q.year === "2025" && q.region.includes("河南") && q.material.includes("上海") && q.material.includes("年轻环"));
        const unique = [...new Map(found.map(q => [q.stem, q])).values()].sort((a,b) => Number(a.number)-Number(b.number));
        if (!cancelled) setQuestions(unique);
      } catch (error) { if (!cancelled) setLoadError(error instanceof Error ? error.message : "题库读取失败"); }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [projectId, retry]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  async function showMap(target: ClassroomPresentationTarget, nextTab: number, photo = selectedPhoto) {
    if (busy) return;
    setBusy(true); setMapError("");
    try { await onPresent(target); setTab(nextTab); setSelectedPhoto(photo); }
    catch (error) { setMapError(error instanceof Error ? error.message : "地图定位失败，请重试"); }
    finally { setBusy(false); }
  }
  function askAssistant() {
    if (!questions.length || !onAssistantPrompt) return;
    const prompt = ["GeoBot 头脑风暴：请围绕上海人口分布补充环节的2025河南卷年轻环题，生成一个条件变化追问与教师参考回答。",
      "材料：" + questions[0].material,
      ...questions.map(q => `题干：${q.stem}；选项：${q.options.join("；")}；题库参考答案：${q.answer}`),
      "限定任务：如果郊区仅增加住宅但缺少就业岗位，年轻环一定会形成吗？讨论成立条件，不再做密度乘面积的假设计算。",
      "密度、老年人口比例、老年人口数量必须分开。人口密度图不能证明年龄比例；景观照片不能证明年龄或入住率。无同年分年龄统计时不得编造比例、边界与迁移数。",
      "这是教师补充追问，不是学生回答或观察，不执行地图操作，不修改教案。输出追问、教师参考回答和一句总结。"].join("\n");
    onAssistantPrompt(prompt, "上海真题拓展：只有住宅，没有就业，会形成年轻环吗？");
    onClose();
  }
  return createPortal(<section className={`shanghai-inquiry glass-panel${collapsed ? " is-collapsed" : ""}`} role="dialog" aria-label="上海人口与年龄结构拓展">
    <header><div><small>基础讲解后的补充 · 不切换课堂环节</small><h2>从人口分布到“年轻环”</h2></div><button className="toolbar-button compact" aria-expanded={!collapsed} onClick={()=>setCollapsed(v=>!v)}>{collapsed ? "展开真题" : "收起看地图"}</button><button className="mini-control" onClick={onClose} aria-label="关闭上海真题拓展">×</button></header>
    <nav aria-label="上海真题探究步骤">{TABS.map((label,index) => <button key={label} aria-pressed={tab===index} disabled={busy} onClick={() => index===1 ? void showMap("shanghai_density",1) : index===2 ? void showMap(PHOTOS[selectedPhoto].target,2) : setTab(index)}>{index+1} · {label}</button>)}</nav>
    {mapError && <p role="alert">{mapError}</p>}{busy && <p role="status">正在定位并切换图层…</p>}
    <div className="shanghai-inquiry-body">
    {tab===0 && <>
      <p className="shanghai-source">2025 河南卷 · 来自当前项目已导入题库</p>
      {loading ? <p role="status">正在读取原题…</p> : loadError ? <p role="alert">{loadError}<button onClick={() => setRetry(v=>v+1)}>重新读取</button></p> : !questions.length ? <p>本项目尚未导入对应题组。请在数据库导入2025河南卷“年轻环”题；地图与景观探究仍可使用。</p> : <>
        <p className="shanghai-question-material">{questions[0].material}</p>
        {questions.map((q,index) => <article className="shanghai-question" key={q.question_id}><h3>{index+1}. {q.stem}</h3><ul>{q.options.map(o=><li key={o}>{o}</li>)}</ul></article>)}
        <p>先作判断并说明理由。参考答案在“解释与拓展”中由教师揭示。</p>
      </>}
    </>}
    {tab===1 && <>
      <h3>先看密度，再区分年龄结构</h3><p>地图显示2020年上海区级平均人口密度。比较中心城区与外围，定位题干所说的空间层次；不能用这张图推算老年人口比例。</p>
      <div className="shanghai-age-pattern" role="img" aria-label="按题干绘制的定性示意：中心城区老年比例高，郊区低，农村高；郊区有年轻劳动力集聚">
        {[['中心城区','老年人口比例高'],['郊区','老年人口比例低 · 年轻劳动力集聚'],['农村','老年人口比例高']].map(([name,value])=><div key={name}><strong>{name}</strong><span>{value}</span></div>)}
      </div>
      <small>依据原题材料的空间顺序示意，无精确比例、距离或边界；不是上海实测年龄分布地图。</small>
      <p>思考：老年人口比例升高，是否必须伴随老年人口数量增加？年轻人口外迁会怎样改变分母？</p>
      <button className="toolbar-button" disabled={busy} onClick={() => void showMap("shanghai_density",1)}>重新定位上海密度图</button>
    </>}
    {tab===2 && <>
      <p>选择地点后切换到局部二维影像，关闭密度填色以看清地表；历史景观照片辅助比较建筑形态。</p>
      <div className="shanghai-photo-tabs">{PHOTOS.map((photo,index)=><button key={photo.target} disabled={busy} aria-pressed={index===selectedPhoto} onClick={()=>void showMap(photo.target,2,index)}>{photo.title}</button>)}</div>
      <LandscapePhoto key={selectedPhoto} photo={PHOTOS[selectedPhoto]} />
      <p>两处均为景观样例，不是“年轻环”的取样证明。建筑高度、住宅数量、人口密度和年龄结构不能相互替代。</p>
    </>}
    {tab===3 && <>
      <h3>把空间格局与作用过程连起来</h3>
      <ol><li>年轻人口外迁 → 中心城区人口年龄构成变化；比例变化不等于同幅度的数量变化。</li><li>郊区制造业提供就业 → 吸引年轻劳动人口；还要考虑住房与通勤条件。</li><li>公共服务完善是题目给出的判断线索；不能由照片推断具体街区老年人口比例。</li></ol>
      <button className="toolbar-button" disabled={!questions.length} onClick={()=>setRevealed(v=>!v)}>{revealed ? "隐藏参考答案" : "揭示题库参考答案"}</button>
      {revealed && questions.map((q,index)=><article key={q.question_id}><h3>第{index+1}题：{q.answer_letter || q.answer || "题库暂无答案"}</h3><p>{q.explanation || "题库暂无解析，请教师核验。"}</p></article>)}
      <p>迁移追问：如果郊区只增加住宅、没有相应就业机会，是否仍会形成“年轻环”？你还需要哪些资料来检验？</p>
      {onAssistantPrompt && <button className="toolbar-button" disabled={!questions.length} onClick={askAssistant}>请助教展开这个追问</button>}
    </>}
    </div>
    <footer><button className="toolbar-button" disabled={busy} onClick={() => void showMap("stage",tab)}>恢复本环节地图</button><button className="toolbar-button primary" disabled={busy} onClick={async () => {
      setBusy(true); setMapError("");
      try { await onPresent("stage"); onClose(); }
      catch (error) { setMapError(error instanceof Error ? error.message : "恢复地图失败，请重试"); }
      finally { setBusy(false); }
    }}>结束补充，返回课堂</button></footer>
  </section>, document.body);
}
