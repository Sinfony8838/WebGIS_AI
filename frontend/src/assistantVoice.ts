import {createVoiceStream, type VoiceStreamHandle, type VoiceFinalMetadata} from "./voiceStream";
import {cancelSpeech, isSpeaking} from "./speechSynthesis";
import {screenTranscript} from "./voiceGate";
import type {JobRecord} from "./types";

type Pending = {id: number; text: string; dependency?: string};
export type AssistantVoiceSnapshot = {capture: "off" | "single" | "continuous"; phase: string; partial: string; queue: Pending[]};
type Options = {
  apiBase: () => string; mode: () => "chat" | "operate";
  submit: (text: string) => Promise<boolean | void>;
  snapshot: (value: AssistantVoiceSnapshot) => void;
  notice: (text: string) => void; draft: (text: string) => void;
  cancelTask: () => void; reply: (text: string) => void;
};

/** Capture, gestures and queueing are independent of the assistant's tool policy. */
export class AssistantVoice {
  private capture: AssistantVoiceSnapshot["capture"] = "off";
  private phase = "";
  private partial = "";
  private segments: string[] = [];
  private queue: Pending[] = [];
  private sequence = 0;
  private epoch = 0;
  private handle: VoiceStreamHandle | null = null;
  private abort: AbortController | null = null;
  private busy = false;
  private awaitingJob = false;
  private waitingConfirmation = false;
  private job: JobRecord | null = null;
  private voiceJobs = new Set<string>();
  private completedJobs = new Set<string>();
  private finals = new Set<string>();
  private playbackAllowed = false;
  private lastReply = "";
  private tapCount = 0;
  private tapUntil = 0;
  private tapTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnects = 0;
  private sessionTimer: ReturnType<typeof setTimeout> | null = null;
  private serverEnded = false;
  private disposed = false;
  constructor(private options: Options) {}
  private emit() {this.options.snapshot({capture: this.capture, phase: this.phase, partial: this.partial, queue: [...this.queue]});}
  private clearGesture() {if(this.tapTimer) clearTimeout(this.tapTimer); this.tapTimer=null;this.tapCount=0;}
  tap(now = Date.now()) {
    if(this.disposed) return;
    if(this.capture === "continuous") {this.hangup();this.tapUntil=now+700;return;}
    if(this.capture === "off" && now < this.tapUntil && this.tapCount === 0) return;
    if(this.tapCount && now <= this.tapUntil) {
      this.tapCount++;
      if(this.tapCount === 3) {this.clearGesture();this.startContinuous();}
      return;
    }
    if(this.capture === "single") {void this.finishSingle();return;}
    this.tapCount=1;this.tapUntil=now+700;
    this.start("single");
    this.tapTimer=setTimeout(() => {const taps=this.tapCount;this.clearGesture();if(taps===2) void this.finishSingle();},700);
  }
  startContinuous() {
    this.clearGesture();
    if(this.capture === "single") {this.capture="continuous";this.phase="长时通话中";this.emit();}
    else if(this.capture === "off") this.start("continuous");
  }
  private start(mode: "single" | "continuous") {
    this.capture=mode;this.phase="正在连接麦克风";this.partial="";this.segments=[];this.finals.clear();
    this.playbackAllowed=true;this.reconnects=0;this.serverEnded=false;
    this.sessionTimer=setTimeout(()=>{if(this.partial)this.options.draft(this.partial);this.hangup();this.options.notice("已达到本次通话时限，请重新开启麦克风。");},900000);
    this.emit();void this.connect();
  }
  private async connect() {
    if(this.capture === "off" || this.disposed || this.abort) return;
    const epoch=++this.epoch; const abort=new AbortController(); this.abort=abort;
    try {
      const handle=await createVoiceStream(this.options.apiBase(), {
        onOpen: () => {if(epoch===this.epoch) {this.phase=this.capture==="continuous"?"长时通话中":"正在聆听";this.emit();}},
        onPartial: text => {
          if(epoch!==this.epoch) return;
          this.partial=[...this.segments,text].filter(Boolean).join("，");
          if(this.capture==="continuous" && text.length>=4 && !this.isEcho(text)) cancelSpeech();
          this.emit();
        },
        onFinal: (text, meta) => {if(epoch===this.epoch) this.final(text,meta);},
        onServerError: payload => {if(epoch===this.epoch) {this.serverEnded=true;this.phase=payload.detail || "语音服务已结束";this.options.notice(this.phase);}},
        onClose: () => {
          if(epoch!==this.epoch || this.capture==="off") return;
          this.handle=null;this.abort=null;
          if(this.serverEnded || this.capture==="single" || this.reconnects>=3) {
            if(this.partial) this.options.draft(this.partial);
            const reason=this.phase;
            this.hangup();this.phase=reason || "语音连接结束，请重新开启";this.emit();return;
          }
          if(this.partial) {this.options.draft(this.partial);this.options.notice("连接中断，未完成语句已保留，未自动发送。");}
          this.segments=[];this.partial="";this.phase="正在重新连接";this.emit();
          this.reconnectTimer=setTimeout(() => {this.reconnectTimer=null;void this.connect();},[1000,2000,4000][this.reconnects++]);
        }
      },abort.signal);
      if(epoch!==this.epoch) {handle.abort();return;}
      this.handle=handle;
    } catch(error) {
      if(epoch!==this.epoch) return;
      this.hangup();this.phase=error instanceof Error?error.message:"麦克风连接失败";this.options.notice(this.phase);this.emit();
    }
  }
  private isEcho(text: string) {
    const clean=(v:string)=>v.replace(/[\s，。！？,.!?：:*#]/g,"");
    return Boolean(isSpeaking() && this.lastReply && clean(text).length>=4 && clean(this.lastReply).includes(clean(text)));
  }
  private final(text: string, meta?: VoiceFinalMetadata) {
    if(meta?.segment_id) {if(this.finals.has(meta.segment_id)) return;this.finals.add(meta.segment_id);}
    if(text.trim()) this.segments.push(text.trim());
    this.partial=this.segments.join("，");this.emit();
    if(this.capture!=="continuous" || meta?.end_reason==="segment") return;
    const utterance=this.segments.join("，").trim();this.segments=[];this.partial="";
    if(!utterance || this.isEcho(utterance)) {this.emit();return;}
    this.accept(utterance);
  }
  private accept(text: string) {
    const clean=text.replace(/^[小][智志知][，,]?/u,"").replace(/[\s，。！？,.!?]/g,"");
    if(/^(?:请)?(?:停止操作|取消任务|停止任务|取消操作)$/.test(clean)) {this.queue=[];cancelSpeech();this.options.cancelTask();this.phase="正在停止任务";this.emit();return;}
    if(/^(?:请)?(?:停止播报|停止说话|别说了)$/.test(clean)) {cancelSpeech();return;}
    if(this.options.mode()==="operate") {
      const gate=screenTranscript(text);
      if(!gate.accepted) {this.phase="未识别为操作请求";this.emit();return;}
      text=gate.command;
    }
    cancelSpeech();
    if(this.busy || this.awaitingJob || this.waitingConfirmation) {
      if(this.queue.length>=3) {this.options.draft(text);this.options.notice("队列已有 3 条请求，新内容已保留在输入框。");return;}
      const dependency=/刚才|刚刚|上个|上述|这个结果|那个结果/.test(text)?this.job && !this.completedJobs.has(this.job.job_id)?this.job.job_id:"pending":undefined;
      this.queue.push({id:++this.sequence,text,dependency});this.phase="已排队";this.emit();return;
    }
    void this.send(text);
  }
  private async send(text: string) {
    this.awaitingJob=true;
    const epoch=this.epoch;
    try {
      const accepted=await this.options.submit(text);
      if(accepted===false) {this.awaitingJob=false;if(epoch===this.epoch)this.options.draft(text);}
    } catch(error) {this.awaitingJob=false;if(epoch===this.epoch && !this.disposed){this.options.draft(text);this.options.notice(error instanceof Error?error.message:"发送失败");}}
    if(!this.disposed)this.emit();
  }
  private drain() {
    if(this.capture!=="continuous" || this.busy || this.awaitingJob || this.waitingConfirmation || !this.queue.length) return;
    const item=this.queue.shift()!;this.emit();void this.send(item.text);
  }
  setBusy(value: boolean) {this.busy=value;if(!value) queueMicrotask(()=>this.drain());}
  setJob(job: JobRecord | null) {
    this.job=job;
    if(!job)return;
    if(this.awaitingJob && !this.completedJobs.has(job.job_id)) {
      this.voiceJobs.add(job.job_id);this.awaitingJob=false;
      this.queue=this.queue.map(q=>q.dependency==="pending"?{...q,dependency:job.job_id}:q);
    }
    if(!["completed","failed"].includes(job.status)) return;
    this.waitingConfirmation=Boolean(job.result?.requires_confirmation);
    if(this.completedJobs.has(job.job_id))return;
    this.completedJobs.add(job.job_id);
    const failed=job.status==="failed" || ["partial","cancelled","blocked","budget_exhausted","needs_clarification"].includes(String(job.result?.outcome || job.result?.status || ""));
    if(failed) {
      const dependent=this.queue.filter(q=>q.dependency===job.job_id);
      this.queue=this.queue.filter(q=>q.dependency!==job.job_id);
      if(dependent.length) {this.options.draft(dependent.map(q=>q.text).join("\n"));this.options.notice("前一任务未完成，相关追问已保留，请明确要使用的结果。");}
    }
    if(this.voiceJobs.has(job.job_id) && this.playbackAllowed) {
      const text=String(job.result?.assistant_message || job.error || "");
      this.lastReply=text;if(text)this.options.reply(text);
    }
    this.emit();queueMicrotask(()=>this.drain());
  }
  removeQueued(id: number) {this.queue=this.queue.filter(q=>q.id!==id);this.emit();}
  async finishSingle() {
    this.clearGesture();
    if(this.capture!=="single")return;
    const handle=this.handle;const epoch=this.epoch;
    if(!handle) {this.hangup();return;}
    this.capture="off";this.phase="正在完成识别";this.emit();
    const tail=await handle.stop();
    if(epoch!==this.epoch)return;
    ++this.epoch; // Ignore callbacks arriving after the final flush.
    this.handle=null;this.abort=null;
    if(this.sessionTimer)clearTimeout(this.sessionTimer);this.sessionTimer=null;
    if(tail===null) {this.options.draft(this.partial);this.options.notice("识别结束未确认，转写已保留，未自动发送。");this.phase="识别未完成";this.emit();return;}
    const text=[...this.segments,tail].filter(Boolean).join("，").trim();
    this.segments=[];this.partial="";this.phase="";this.emit();
    if(text)this.accept(text);
  }
  hangup() {
    const count=this.queue.length;
    if(this.sessionTimer)clearTimeout(this.sessionTimer);this.sessionTimer=null;
    this.clearGesture();if(this.reconnectTimer)clearTimeout(this.reconnectTimer);this.reconnectTimer=null;
    ++this.epoch;this.capture="off";this.abort?.abort();this.abort=null;this.handle?.abort();this.handle=null;
    this.partial="";this.segments=[];this.queue=[];this.playbackAllowed=false;cancelSpeech();
    this.phase=count?`已结束通话，取消 ${count} 条排队请求`:"";this.emit();
  }
  dispose() {this.hangup();this.disposed=true;}
}
