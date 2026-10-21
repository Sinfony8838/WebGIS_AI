import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { buildPublicFileUrl, getProjectPresentation, importProjectPresentation, listProjectPresentations, prepareProjectPresentation } from "../api";
import type { ProjectPresentation } from "../types";
import { loadPptSession, preloadPptImage, presentationSessionKey, releasePptImages, type PptSession } from "../lib/pptSession";
import "./DesktopPptControls.css";
import "./ProjectPptLibrary.css";

type Props = { projectId: string; userId: string; currentId: string; viewerOpen: boolean;
  onSelect: (deck: ProjectPresentation, session: PptSession, key: string) => void };

export function ProjectPptLibrary({ projectId, userId, currentId, viewerOpen, onSelect }: Props) {
  const scope = `${userId}:${projectId}`;
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ProjectPresentation[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState({ top: 64, right: 16 });
  const launcher = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController>();
  const sequence = useRef(0);
  const importing = useRef(false);
  const selected = useRef(false);
  const onSelectRef = useRef(onSelect); onSelectRef.current = onSelect;
  const refresh = useCallback(async (signal?: AbortSignal) => {
    const result = await listProjectPresentations(projectId, signal);
    signal?.throwIfAborted(); setItems(result.items); return result.items;
  }, [projectId]);

  const choose = useCallback(async (item: ProjectPresentation, retry = false) => {
    controller.current?.abort();
    const operation = ++sequence.current;
    const control = new AbortController(); controller.current = control;
    selected.current = true; setBusy(item.id); setError("");
    try {
      let deck = await getProjectPresentation(projectId, item.id, control.signal);
      if (deck.status === "pending" || (retry && deck.status === "failed")) {
        try { deck = await prepareProjectPresentation(projectId, item.id, retry, control.signal); }
        catch (failure) {
          control.signal.throwIfAborted();
          // A POST whose response was lost may already be running. Read it;
          // never replay a conversion on a transport timeout.
          deck = await getProjectPresentation(projectId, item.id, control.signal);
          if (deck.status === "pending" || deck.status === "failed") throw failure;
        }
      }
      const deadline = Date.now() + 180000;
      while (deck.status === "queued" || deck.status === "running") {
        setError("正在准备课件页面，可继续使用地图…");
        if (Date.now() >= deadline) throw new Error("课件仍在准备，请稍后刷新列表查看；不会重复提交转换。");
        await new Promise<void>((resolve, reject) => {
          const abort = () => { clearTimeout(timer); reject(new DOMException("已取消", "AbortError")); };
          const timer = setTimeout(() => { control.signal.removeEventListener("abort", abort); resolve(); }, 800);
          control.signal.addEventListener("abort", abort, { once: true });
        });
        deck = await getProjectPresentation(projectId, item.id, control.signal);
      }
      if (deck.status !== "ready" || !deck.slides?.length) throw new Error(deck.error || "课件尚未准备完成，请稍后重试。");
      const key = presentationSessionKey(scope, deck);
      const session = await loadPptSession(key);
      control.signal.throwIfAborted();
      session.currentIndex = Math.max(0, Math.min(session.currentIndex, deck.slides.length - 1));
      await preloadPptImage(buildPublicFileUrl(deck.slides[session.currentIndex].image_url), control.signal, scope);
      if (operation !== sequence.current) return;
      onSelectRef.current(deck, session, key); setOpen(false); setError("");
      void refresh(control.signal).catch(() => {});
    } catch (failure) {
      if (!control.signal.aborted && operation === sequence.current) {
        setError(failure instanceof Error ? failure.message : String(failure));
        void refresh(control.signal).catch(() => {});
      }
    } finally { if (operation === sequence.current) setBusy(""); }
  }, [projectId, refresh, scope]);

  useEffect(() => {
    if (!projectId) return;
    const control = new AbortController(); setLoading(true);
    void refresh(control.signal).then(rows => {
      if (selected.current) return;
      try {
        const previous = JSON.parse(localStorage.getItem(`ppt-current:${scope}`) || "null");
        const row = rows.find(item => item.id === previous?.id);
        if (row && previous.open) void choose(row);
      } catch { /* Storage can be disabled. */ }
    }).catch(failure => { if (!control.signal.aborted) setError(String(failure.message || failure)); })
      .finally(() => { if (!control.signal.aborted) setLoading(false); });
    return () => { control.abort(); controller.current?.abort(); sequence.current += 1; };
  }, [choose, refresh, scope]);

  useEffect(() => () => releasePptImages(scope), [scope]);

  useEffect(() => {
    if (!currentId) return;
    try { localStorage.setItem(`ppt-current:${scope}`, JSON.stringify({ id: currentId, open: viewerOpen })); } catch { /* Optional resume. */ }
  }, [currentId, scope, viewerOpen]);

  useEffect(() => {
    if (!open) return;
    const positionPanel = () => {
      const rect = launcher.current?.getBoundingClientRect();
      if (rect) setPosition({ top: rect.bottom + 10, right: Math.max(12, Math.min(window.innerWidth - 372, window.innerWidth - rect.right)) });
    };
    positionPanel(); panel.current?.querySelector<HTMLInputElement>("input[type=search]")?.focus();
    const outside = (event: PointerEvent) => {
      if (!panel.current?.contains(event.target as Node) && !launcher.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("resize", positionPanel); window.addEventListener("scroll", positionPanel, true);
    document.addEventListener("pointerdown", outside);
    return () => { window.removeEventListener("resize", positionPanel); window.removeEventListener("scroll", positionPanel, true); document.removeEventListener("pointerdown", outside); };
  }, [open]);

  const importFile = async (file: File) => {
    if (importing.current) return;
    importing.current = true; setBusy("import"); setError("");
    const control = new AbortController(); controller.current?.abort(); controller.current = control;
    const requestId = crypto.randomUUID();
    try {
      const item = await importProjectPresentation(projectId, file, requestId, control.signal);
      await refresh(control.signal); importing.current = false; await choose(item);
    } catch (failure) {
      if (control.signal.aborted) return;
      try {
        const rows = await refresh(control.signal);
        const recovered = rows.find(item => item.import_request_id === requestId);
        if (recovered) { importing.current = false; await choose(recovered); return; }
      } catch { /* Preserve the original unknown-result message. */ }
      setError(`${failure instanceof Error ? failure.message : failure}。导入结果未确认，请刷新列表查看；不会自动重新上传。`);
    } finally { importing.current = false; setBusy(""); }
  };

  return <>
    <button ref={launcher} type="button" className="desktop-switch-launcher" aria-label="PPT 课件" title="项目课件"
      aria-haspopup="dialog" aria-expanded={open} aria-busy={Boolean(busy)} disabled={!projectId}
      onClick={() => { setOpen(value => !value); if (!open) { setLoading(true); void refresh().catch(failure => setError(failure.message)).finally(() => setLoading(false)); } }}>
      <svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="29" cy="22" r="15" fill="#f5ba9d" />
        <path d="M29 7a15 15 0 0 1 15 15H29Z" fill="#d35230" /><rect x="5" y="12" width="24" height="27" rx="3" fill="#c43e1c" />
        <path d="M13 32V18h6a4.5 4.5 0 0 1 0 9h-3v5Zm3-8h3a1.5 1.5 0 0 0 0-3h-3Z" fill="white" /></svg>
    </button>
    {open ? createPortal(<section ref={panel} role="dialog" aria-label="项目课件" className="project-ppt-library" style={position}
      onKeyDown={event => { event.stopPropagation(); if (event.key === "Escape") { setOpen(false); launcher.current?.focus(); } }}>
      <header><div><strong>项目课件</strong><small>选择课件，继续课堂</small></div><button type="button" aria-label="关闭课件列表" onClick={() => { setOpen(false); launcher.current?.focus(); }}>×</button></header>
      <input type="search" aria-label="搜索项目课件" placeholder="搜索课件名称" value={query} onChange={event => setQuery(event.target.value)} />
      {error ? <p role="status" className="project-ppt-message">{error}</p> : null}
      <div className="project-ppt-items" aria-busy={loading}>
        {loading && !items.length ? <p>正在读取课件…</p> : null}
        {!loading && !items.length ? <p>当前项目还没有课件，可在下方导入。</p> : null}
        {items.filter(item => item.title.toLowerCase().includes(query.toLowerCase())).map(item => <button type="button" key={item.id}
          className={`project-ppt-card ${currentId === item.id ? "is-current" : ""}`} disabled={importing.current}
          onClick={() => void choose(item, item.status === "failed")}>
          {item.cover_url ? <img src={buildPublicFileUrl(item.cover_url)} alt="" loading="lazy" /> : <span className="project-ppt-placeholder">PPT</span>}
          <span><strong>{item.title}</strong><small>{item.page_count ? `${item.page_count} 页 · ` : ""}{busy === item.id ? "正在打开…" : currentId === item.id ? "继续播放" : item.status === "ready" ? "可播放" : item.status === "failed" ? "准备失败，点击重试" : item.status === "pending" ? "点击准备课件" : "正在准备"}</small></span>
        </button>)}
      </div>
      <footer><button type="button" className="toolbar-button" disabled={Boolean(busy)} onClick={() => fileInput.current?.click()}>导入课件</button>
        <button type="button" className="toolbar-button" onClick={() => void refresh().catch(failure => setError(failure.message))}>刷新列表</button></footer>
      <input ref={fileInput} type="file" accept=".ppt,.pptx" hidden aria-label="导入项目 PPT" onChange={event => {
        const file = event.target.files?.[0]; event.target.value = ""; if (file) void importFile(file);
      }} />
    </section>, document.body) : null}
  </>;
}
