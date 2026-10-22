import {useState} from "react";
import {getApiBase,saveAssistantImage} from "../api";
export type AssistantImageArtifact={artifact_id?:string;artifact_type?:string;title?:string;metadata?:{public_url?:string;saved_to_library?:boolean;geography_review?:{status:string;summary?:string;checks?:Array<{requirement:string;status:string;evidence:string}>};geography_brief?:{generation_method?:string}}};
export function assistantImageUrl(value?:string){
  if(!value)return "";
  try {const url=new URL(value,getApiBase() || window.location.origin);return ["http:","https:"].includes(url.protocol)?url.href:"";}catch{return "";}
}
export function AssistantImage({artifact}:{artifact:AssistantImageArtifact}){
  const [saved,setSaved]=useState(artifact.metadata?.saved_to_library===true || artifact.artifact_type==="generated_image");
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[deferred,setDeferred]=useState(false),[failed,setFailed]=useState(false);
  const review=artifact.metadata?.geography_review;
  const blocked=!!review && review.status!=="pass";
  const url=assistantImageUrl(artifact.metadata?.public_url);
  if(!url)return null;
  const save=async()=>{if(!artifact.artifact_id || busy || blocked)return;setBusy(true);setError("");try{await saveAssistantImage(artifact.artifact_id);setSaved(true);}catch{setError("保存失败，可以重试；预览仍保留。");}finally{setBusy(false);}};
  return <figure className="assistant-image-card">
    <a href={url} target="_blank" rel="noreferrer"><img src={url} alt={artifact.title || "AI 生成图片"} onLoad={()=>setFailed(false)} onError={()=>setFailed(true)}/></a>
    {failed && <p role="alert">图片加载失败，点击图片可打开原图。</p>}
    {review && <details className="assistant-image-review"><summary>{review.status==="pass"?"地理自动检查完成 · 仍需教师审阅":review.status==="fail"?"发现地理问题 · 暂不保存":"地理检查未完成 · 暂不保存"}</summary><p>{review.summary}</p>{artifact.metadata?.geography_brief?.generation_method==="reference_redraw" && <p>根据读图结果重新绘制，未在原图上编辑。</p>}<ul>{review.checks?.map((item,index)=><li key={index}>{item.status==="pass"?"✓":item.status==="fail"?"×":"?"} {item.requirement}：{item.evidence}</li>)}</ul></details>}
    {artifact.artifact_id && <figcaption>{saved?<span>已保存到素材库</span>:<><button disabled={busy || blocked} onClick={()=>void save()}>{busy?"正在保存":"保存到素材库"}</button>{deferred?<span>仅保留在会话中</span>:<button onClick={()=>setDeferred(true)}>暂不保存</button>}</>}{error && <span role="alert">{error}</span>}</figcaption>}
  </figure>;
}
