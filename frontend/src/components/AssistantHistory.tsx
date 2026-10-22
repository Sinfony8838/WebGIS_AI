import {useEffect, useRef, useState} from "react";
import {createAssistantFolder, fetchAssistantConversations, removeAssistantFolder, updateAssistantConversation, updateAssistantFolder} from "../api";
import type {AssistantFolder, ConversationSummary} from "../types";

type Props = {projectId?:string; mode:"chat"|"operate"; conversationId?:string; messageCount:number; busy:boolean;
  onNavigate:(id?:string, keepOpen?:boolean)=>Promise<boolean>};
export function AssistantHistory({projectId,mode,conversationId,messageCount,busy,onNavigate}:Props) {
  const [items,setItems]=useState<ConversationSummary[]>([]), [folders,setFolders]=useState<AssistantFolder[]>([]);
  const [trash,setTrash]=useState(false), [revision,setRevision]=useState(0), [status,setStatus]=useState("");
  const [pending,setPending]=useState(false), [menu,setMenu]=useState("");
  const [editing,setEditing]=useState<string|null>(null), [name,setName]=useState("");
  const alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  useEffect(()=>{
    let current=true;setItems([]);setFolders([]);
    if(!projectId)return;
    setStatus("正在读取会话");
    void fetchAssistantConversations(projectId,mode,trash).then(result=>{
      if(current){setItems(result.items);setFolders(result.folders || []);setStatus("");}
    }).catch(()=>{if(current)setStatus("会话读取失败，请重试");});
    return()=>{current=false;};
  },[projectId,mode,conversationId,messageCount,trash,revision]);
  const act=async(work:()=>Promise<unknown>)=>{
    if(pending || busy)return;
    setPending(true);setStatus("");
    try {await work();if(alive.current){setMenu("");setRevision(v=>v+1);}}
    catch(error){if(alive.current)setStatus(error instanceof Error?error.message:String(error));}
    finally {if(alive.current)setPending(false);}
  };
  const row=(item:ConversationSummary)=><div key={item.conversation_id} className="assistant-history-item">
    <div className="assistant-history-row">
      <button className="assistant-history-title" title={item.title} aria-current={conversationId===item.conversation_id?"page":undefined}
        disabled={busy || pending || trash} onClick={()=>void onNavigate(item.conversation_id)}>{item.title}</button>
      {trash ? <button disabled={pending} aria-label={`恢复 ${item.title}`} onClick={()=>void act(()=>updateAssistantConversation(item.conversation_id,{deleted:false}))}>恢复</button> :
        <button className="assistant-history-more" aria-label={`管理会话 ${item.title}`} aria-expanded={menu===item.conversation_id} onClick={()=>setMenu(menu===item.conversation_id?"":item.conversation_id)}>⋯</button>}
    </div>
    {menu===item.conversation_id && !trash && <div className="assistant-history-menu">
      <button disabled={pending} onClick={()=>void act(()=>updateAssistantConversation(item.conversation_id,{pinned:!item.pinned}))}>{item.pinned?"取消置顶":"置顶会话"}</button>
      <label>移入项目<select aria-label={`移动会话 ${item.title}`} disabled={pending} value={item.folder_id || ""}
        onChange={event=>{const folder_id=event.target.value;void act(()=>updateAssistantConversation(item.conversation_id,{folder_id}));}}>
        <option value="">未分组</option>{folders.map(folder=><option key={folder.folder_id} value={folder.folder_id}>{folder.name}</option>)}
      </select></label>
      <button disabled={pending} onClick={()=>void act(async()=>{
        if(item.conversation_id===conversationId && !await onNavigate(undefined,true))throw new Error("请先停止当前任务再删除会话");
        if(alive.current)await updateAssistantConversation(item.conversation_id,{deleted:true});
      })}>删除会话</button>
    </div>}
  </div>;
  return <nav className="assistant-history" aria-label={`${mode==="chat"?"Chat":"Operate"} 历史会话`}>
    <button className="assistant-new-conversation" disabled={busy || pending} onClick={()=>void onNavigate()}>＋ 新建会话</button>
    <button disabled={busy || pending || !projectId} onClick={()=>{setEditing("");setName("");setTrash(false);}}>＋ 新建项目</button>
    {editing!==null && <form className="assistant-folder-form" onSubmit={event=>{event.preventDefault();void act(async()=>{
      if(!projectId)return;
      if(editing)await updateAssistantFolder(projectId,editing,{name:name.trim()});else await createAssistantFolder(projectId,name.trim());
      if(alive.current){setEditing(null);setName("");}
    });}}><input aria-label="项目文件夹名称" autoFocus value={name} maxLength={80} placeholder="项目名称" onChange={event=>setName(event.target.value)}/>
      <button type="submit" disabled={pending || !name.trim()}>保存</button><button type="button" onClick={()=>setEditing(null)}>取消</button></form>}
    <div className="assistant-history-section"><small>{trash?"已删除":`${mode==="chat"?"Chat":"Operate"} 历史会话`}</small>
      <button onClick={()=>{setTrash(!trash);setMenu("");}}>{trash?"返回历史":"已删除"}</button></div>
    {status && <p role="status">{status}<button onClick={()=>setRevision(v=>v+1)}>重试</button></p>}
    {trash ? <>{items.map(row)}{!status && !items.length && <p>没有已删除会话</p>}</> : <>
      {items.some(item=>item.pinned) && <section aria-label="置顶会话"><small>置顶</small>{items.filter(item=>item.pinned).map(row)}</section>}
      {folders.map(folder=><div key={folder.folder_id} className="assistant-history-folder">
        <div className="assistant-history-row"><details open><summary title={folder.name}>{folder.pinned?"★ ":""}▱ {folder.name}</summary>
          {items.filter(item=>item.folder_id===folder.folder_id && !item.pinned).map(row)}
          {!items.some(item=>item.folder_id===folder.folder_id && !item.pinned) && <small>暂无未置顶会话</small>}
        </details><button className="assistant-history-more" aria-label={`管理项目 ${folder.name}`} aria-expanded={menu===folder.folder_id} onClick={()=>setMenu(menu===folder.folder_id?"":folder.folder_id)}>⋯</button></div>
        {menu===folder.folder_id && <div className="assistant-history-menu">
          <button disabled={pending} onClick={()=>void act(()=>updateAssistantFolder(projectId!,folder.folder_id,{pinned:!folder.pinned}))}>{folder.pinned?"取消置顶项目":"置顶项目"}</button>
          <button onClick={()=>{setEditing(folder.folder_id);setName(folder.name);setMenu("");}}>重命名</button>
          <button disabled={pending} onClick={()=>void act(()=>removeAssistantFolder(projectId!,folder.folder_id))}>移除文件夹，保留会话</button>
        </div>}
      </div>)}
      <small>未分组</small>{items.filter(item=>!item.folder_id && !item.pinned).map(row)}
      {!status && !items.length && <p>暂无历史会话</p>}
    </>}
  </nav>;
}
