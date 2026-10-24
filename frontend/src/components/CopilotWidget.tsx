import {useEffect, useRef, useState} from "react";
import {getApiBase} from "../api";
import {AssistantVoice, type AssistantVoiceSnapshot} from "../assistantVoice";
import {cancelSpeech, speak} from "../speechSynthesis";
import {AssistantImage,assistantImageUrl,type AssistantImageArtifact} from "./AssistantImage";
import {AssistantHistory} from "./AssistantHistory";
import {AssistantActivity} from "./AssistantActivity";
import {TeachingPet} from "./TeachingPet";
import type {AssistantTab, ChatMessage, ImageAttachment, JobRecord} from "../types";
import "./CopilotWidget.css";

type Props = {
  scopeKey?: string;
  projectId?: string;
  conversationId?: string;
  onSelectConversation?: (id: string) => Promise<void>;
  onNewConversation?: () => void | Promise<void>;
  chatLog: ChatMessage[];
  currentJob: JobRecord | null;
  inputValue: string;
  onInputChange: (value: string) => void;
  onSubmit: () => void;
  onQuickPrompt?: (prompt: string) => void;
  /** 打开全屏教案设计工作台（教案设计快捷入口；不发送聊天消息）。 */
  onConfirm: (confirmationId: string, decision?: "approve" | "reject") => void | Promise<void>;
  onVoiceSubmit: (transcript: string) => void | Promise<boolean | void>;
  onCancelTask?: () => void;
  onOpenDesign?: (designId: string) => void;
  onVoiceNotice: (tone: "info" | "success" | "error", title: string, detail?: string) => void;
  busy: boolean;
  /** Current lesson-workflow phase; drives the header chip and chip ordering. */
  teachingPhase?: "course_prep" | "in_class" | "post_class" | "";
  /** Increment to bring the GeoBot panel forward for a classroom AI activity. */
  pendingImage?: ImageAttachment | null;
  onAttachImage?: (image: ImageAttachment) => void;
  onUploadImage?: (file: File) => void;
  onRemoveImage?: () => void;
  openSignal?: number;
  /** 课堂控制台图片生成能力的迁移入口：MiniMax 文生图（结果自动入库）。 */
  onGenerateImage?: (payload: { prompt: string; model: string; aspectRatio: string }) => Promise<void>;
  imageGenerationLoading?: boolean;
  imageGenerationConfigured?: boolean;
  imageGenerationModel?: string;
  imageGenerationAdmin?: boolean;
  /** 当前功能页签：teaching（默认，教学助手）| interaction（智能交互语音操控）。 */
  assistantTab?: AssistantTab;
  onTabChange?: (tab: AssistantTab) => void | Promise<void>;
  /** 语音播报开关（interaction Tab 专用）。 */
  ttsEnabled?: boolean;
  onTtsToggle?: (enabled: boolean) => void;
  /** 后端本地 ASR（sherpa-onnx WS 流）是否可用（来自 /health 的 voice_asr）。 */
  voiceStreamAvailable?: boolean;
  /** /health 的 voice_asr.state（ready/initializing/incomplete/...），用于精确的不可用原因。 */
  voiceAsrState?: string;
  /** /health 的 voice_asr.reason，补充不可用说明。 */
  voiceAsrReason?: string;
  /** 常开聆听状态与实时转写上报（驱动全屏光晕层）。 */
  onListeningChange?: (listening: boolean) => void;
  onPartialTranscript?: (text: string) => void;
  onCapturedCommand?: (command: string) => void;
};


function safeUrl(value: unknown): string {
  if(typeof value!=="string")return "";
  try {const url=new URL(value,window.location.origin);return ["http:","https:"].includes(url.protocol)?url.href:"";} catch{return "";}
}
function MessageText({text}: {text: string}) {
  return <div className="assistant-message-text">{text.split(/\n\n+/).map((block,i)=>
    <p key={i}>{block.split(/(\*\*[^*]+\*\*)/).map((part,j)=>part.startsWith("**")?<strong key={j}>{part.slice(2,-2)}</strong>:part)}</p>)}</div>;
}
const EMPTY: AssistantVoiceSnapshot={capture:"off",phase:"",partial:"",queue:[]};

export function CopilotWidget(props: Props) {
  const latest=useRef(props);latest.current=props;
  const mode=props.assistantTab==="interaction"?"operate":"chat";
  const [expanded,setExpanded]=useState(false);
  const [historyOpen,setHistoryOpen]=useState(false);
  const navigate=async (id?:string,keepOpen=false):Promise<boolean>=>{
    if(switching)return false;
    voice.current?.hangup();setSwitching(true);
    try {if(id)await props.onSelectConversation?.(id);else await props.onNewConversation?.();if(!expanded && !keepOpen)setHistoryOpen(false);return true;}
    catch(error){props.onVoiceNotice("error","会话切换未完成",String(error));return false;}
    finally {setSwitching(false);}
  };
  const [minimized,setMinimized]=useState(false);
  const [switching,setSwitching]=useState(false);
  const [confirming,setConfirming]=useState(false);
  const confirmingRef=useRef(false);
  const confirm=async (id:string,decision:"approve"|"reject")=>{
    if(confirmingRef.current || props.busy || switching)return;
    confirmingRef.current=true;setConfirming(true);
    try {await props.onConfirm(id,decision);}
    catch(error){props.onVoiceNotice("error","确认操作失败",error instanceof Error?error.message:String(error));}
    finally {confirmingRef.current=false;setConfirming(false);}
  };
  const [micMenu,setMicMenu]=useState(false);
  const [voiceState,setVoiceState]=useState<AssistantVoiceSnapshot>(EMPTY);
  const voice=useRef<AssistantVoice | null>(null);
  const upload=useRef<HTMLInputElement>(null);
  const bottom=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const controller=new AssistantVoice({apiBase:getApiBase,mode:()=>latest.current.assistantTab==="interaction"?"operate":"chat",
      submit:text=>Promise.resolve(latest.current.onVoiceSubmit(text)),
      snapshot:state=>{setVoiceState(state);latest.current.onListeningChange?.(state.capture!=="off");latest.current.onPartialTranscript?.(state.partial);},
      notice:text=>latest.current.onVoiceNotice("info","语音",text),draft:text=>latest.current.onInputChange(text),
      cancelTask:()=>latest.current.onCancelTask?.(),reply:text=>{if(latest.current.ttsEnabled!==false)speak(text);}});
    voice.current=controller;
    const visibility=()=>{if(document.hidden)controller.hangup();};
    document.addEventListener("visibilitychange",visibility);
    return ()=>{document.removeEventListener("visibilitychange",visibility);controller.dispose();voice.current=null;};
  },[props.scopeKey,mode]);
  useEffect(()=>{voice.current?.setJob(props.currentJob);voice.current?.setBusy(props.busy);},[props.currentJob,props.busy]);
  useEffect(()=>{if(props.openSignal)setMinimized(false);},[props.openSignal]);
  useEffect(()=>{bottom.current?.scrollIntoView?.({block:"nearest"});},[props.chatLog.length]);
  const change=async (tab: AssistantTab)=>{
    if(tab===props.assistantTab || switching)return;
    voice.current?.hangup();setSwitching(true);
    try {await props.onTabChange?.(tab);} catch {/* Parent keeps the old mode and reports the failure. */} finally {setSwitching(false);}
  };
  const mic=()=>{
    if(!props.voiceStreamAvailable && voiceState.capture==="off") {props.onVoiceNotice("info","语音识别不可用","本地识别服务尚未就绪，可以先打字。");return;}
    voice.current?.tap();
  };
  const confirmation=props.currentJob?.result?.requires_confirmation ? props.currentJob.result.confirmation_id : "";
  if(minimized)return <button className="assistant-launcher" aria-label="打开智能助教" onClick={()=>setMinimized(false)}><TeachingPet busy={props.busy} currentJob={props.currentJob} minimized isListening={voiceState.capture!=="off"} size="orb"/></button>;
  return <aside className={`assistant-panel${expanded?" is-expanded":""}`} aria-label="智能助教">
    <header className="assistant-header">
      <span className="assistant-mascot" role="img" aria-label="智能助教吉祥物"><TeachingPet busy={props.busy} currentJob={props.currentJob} minimized={false} isListening={voiceState.capture!=="off"} size="header"/></span>
      <nav aria-label="助教模式">{([['teaching','Chat'],['interaction','Operate']] as const).map(([tab,label])=>
        <button key={tab} role="tab" aria-selected={props.assistantTab===tab || (!props.assistantTab && tab==='teaching')} disabled={switching} onClick={()=>void change(tab)}>{label}</button>)}</nav>
      <button aria-label="历史会话" aria-expanded={historyOpen} onClick={()=>setHistoryOpen(!historyOpen)} title="历史会话">☰</button>
      <button aria-label={expanded?"收起面板":"展开面板"} onClick={()=>setExpanded(!expanded)}>{expanded?"↙":"↗"}</button>
      <button aria-label="最小化助教" onClick={()=>setMinimized(true)}>−</button>
    </header>
    <div className="assistant-body">
    {historyOpen && <AssistantHistory key={`${props.scopeKey}:${props.projectId}:${mode}`} projectId={props.projectId} mode={mode}
      conversationId={props.conversationId} messageCount={props.chatLog.length} busy={switching} onNavigate={navigate}/>}
    <div className="assistant-conversation">
    <main className="assistant-messages">
      {props.chatLog.map((message,index)=><article key={`${index}:${message.timestamp}`} className={`assistant-message ${message.role}`}>
        {message.image_attachment && <img src={assistantImageUrl(message.image_attachment.public_url)} alt={message.image_attachment.title}/>}
        {message.execution && <AssistantActivity job={message.execution} busy={false}/>}
        <MessageText text={message.text}/>
        {(message.actions_executed || []).map((item,i)=>{
          const artifact=item.result?.generated_artifact as AssistantImageArtifact | undefined;
          return artifact?<AssistantImage key={artifact.artifact_id || i} artifact={artifact}/>:null;
        })}
        {message.citations?.length?<details><summary>参考来源</summary>{message.citations.map((item,i)=><p key={i}>{safeUrl(item.url)?<a href={safeUrl(item.url)} target="_blank" rel="noreferrer">{item.title}</a>:item.title}</p>)}</details>:null}

      </article>)}
      {props.busy && <AssistantActivity job={props.currentJob} busy/>}
      {props.busy && props.currentJob?.activity?.answer_text && <article className="assistant-message"><MessageText text={props.currentJob.activity.answer_text}/></article>}
      {confirmation && <div className="assistant-confirmation"><div role="group" aria-label="确认操作" aria-busy={confirming || props.busy}>
        <MessageText text={props.currentJob?.result?.assistant_message || "请核对以上操作后确认执行。"}/>
        <button disabled={confirming || props.busy || switching} onClick={()=>void confirm(confirmation,"approve")}>{confirming?"正在提交确认":"确认"}</button>
        <button disabled={confirming || props.busy || switching} onClick={()=>void confirm(confirmation,"reject")}>取消</button>
      </div></div>}
      <div ref={bottom}/>
    </main>
    <footer>
      {voiceState.queue.length>0 && <details className="assistant-queue" open><summary>已排队 {voiceState.queue.length}/3</summary>{voiceState.queue.map(q=><div key={q.id}><span>{q.text}</span><button aria-label={`删除排队请求 ${q.text}`} onClick={()=>voice.current?.removeQueued(q.id)}>×</button></div>)}</details>}
      {props.pendingImage && mode==="chat" && <div className="assistant-attachment"><img src={assistantImageUrl(props.pendingImage.public_url)} alt={props.pendingImage.title}/><button onClick={props.onRemoveImage}>移除</button></div>}
      <form onSubmit={e=>{e.preventDefault();props.onSubmit();}}>
        <textarea aria-label="消息" value={props.inputValue} onChange={e=>props.onInputChange(e.target.value)} placeholder={mode==="chat"?"提问或描述想生成的图片":"描述你要完成的操作"}
          onKeyDown={e=>{if(e.key==="Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {e.preventDefault();if(!props.busy && !switching)props.onSubmit();}}}/>
        <div className="assistant-composer-controls">
          {mode==="chat" && <><input ref={upload} hidden type="file" accept="image/*" onChange={e=>{const file=e.target.files?.[0];if(file)props.onUploadImage?.(file);e.target.value="";}}/><button type="button" title="添加图片" aria-label="添加图片" onClick={()=>upload.current?.click()}>＋</button></>}
          <button type="button" className={`assistant-mic ${voiceState.capture!=="off"?"recording":""}`} aria-label={voiceState.capture==="continuous"?"结束通话":voiceState.capture==="single"?"结束语音输入":"开始语音输入"} aria-pressed={voiceState.capture!=="off"} title="点按录音，再点按发送；连续点按三次开始长时通话" onClick={mic} onContextMenu={e=>{e.preventDefault();setMicMenu(!micMenu);}}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>
          </button>
          <button type="button" aria-label="语音选项" onClick={()=>setMicMenu(!micMenu)}>⌄</button>
          {micMenu && <div className="assistant-mic-menu"><button type="button" disabled={!props.voiceStreamAvailable} onClick={()=>{voice.current?.startContinuous();setMicMenu(false);}}>开始长时通话</button><button type="button" onClick={()=>{props.onTtsToggle?.(!props.ttsEnabled);cancelSpeech();}}>{props.ttsEnabled?"关闭播报":"开启播报"}</button></div>}
          <span className="assistant-control-spacer"/>
          {props.busy?<button type="button" aria-label="停止任务" onClick={()=>{voice.current?.hangup();props.onCancelTask?.();}}>■</button>:<button type="submit" className="assistant-send" aria-label="发送" disabled={switching || (!props.inputValue.trim() && !props.pendingImage)}><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6"/></svg></button>}
        </div>
      </form>
      <div className="assistant-status" aria-live="polite"><span>{voiceState.partial || (switching?"正在停止当前任务":voiceState.phase)}</span></div>
    </footer>
    </div></div>
  </aside>;
}
