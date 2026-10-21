import { BrushHistory } from "./brushHistory";

export type PptSession = { currentIndex: number; fullscreen: boolean; widthPercent: number; history: BrushHistory };
type SavedSession = Omit<PptSession, "history"> & { pages: Record<string, string | null> };
const memory = new Map<string, PptSession>();
const writes = new Map<string, Promise<void>>();
let database: Promise<IDBDatabase> | undefined;

function db(): Promise<IDBDatabase> {
  database ??= new Promise((resolve, reject) => {
    const request = indexedDB.open("webgis-project-ppt", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("sessions");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return database;
}

export async function loadPptSession(key: string): Promise<PptSession> {
  const cached = memory.get(key);
  if (cached) return cached;
  let saved: SavedSession | undefined;
  try {
    const database = await db();
    saved = await new Promise((resolve, reject) => {
      const request = database.transaction("sessions").objectStore("sessions").get(key);
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
  } catch { /* In restricted storage modes keep the current tab usable. */ }
  const session = { currentIndex: saved?.currentIndex || 0, fullscreen: saved?.fullscreen || false,
    widthPercent: Math.max(22, Math.min(70, saved?.widthPercent || 46)), history: BrushHistory.restore(saved?.pages || {}) };
  memory.set(key, session); return session;
}

export function savePptSession(key: string, session: PptSession): Promise<void> {
  memory.set(key, session);
  const saved: SavedSession = { currentIndex: session.currentIndex, fullscreen: session.fullscreen,
    widthPercent: session.widthPercent, pages: session.history.snapshot() };
  const write = (writes.get(key) || Promise.resolve()).catch(() => {}).then(async () => {
    const database = await db();
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction("sessions", "readwrite");
      transaction.objectStore("sessions").put(saved, key);
      transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  });
  writes.set(key, write);
  return write;
}

export function presentationSessionKey(scope: string, deck: { id: string; source_hash?: string; render_version: string }) {
  return `${scope}:${deck.id}:${deck.source_hash || ""}:${deck.render_version}`;
}

const images = new Map<string, { objectUrl: string; bytes: number }>();
const imageEpochs = new Map<string, number>();
const MAX_IMAGE_BYTES = 48 * 1024 * 1024;
export function cachedPptImage(url: string, scope = ""): string {
  return images.get(`${scope}:${url}`)?.objectUrl || url;
}
export function releasePptImages(scope: string): void {
  imageEpochs.set(scope, (imageEpochs.get(scope) || 0) + 1);
  for (const [key, entry] of images) if (key.startsWith(`${scope}:`)) {
    URL.revokeObjectURL(entry.objectUrl); images.delete(key);
  }
}

export async function preloadPptImage(url: string, signal?: AbortSignal, scope = ""): Promise<void> {
  const epoch = imageEpochs.get(scope) || 0;
  const key = `${scope}:${url}`;
  const cached = images.get(key);
  if (cached) { images.delete(key); images.set(key, cached); return; }
  const timeout = new AbortController();
  const abortFetch = () => timeout.abort(); signal?.addEventListener("abort", abortFetch, { once: true });
  signal?.throwIfAborted();
  const fetchTimer = setTimeout(abortFetch, 20000);
  let blob: Blob;
  try {
    const response = await fetch(url, { credentials: "include", signal: timeout.signal });
    if (!response.ok) throw new Error("课件页面加载失败，请刷新课件列表后重试。");
    blob = await response.blob();
  } finally { clearTimeout(fetchTimer); signal?.removeEventListener("abort", abortFetch); }
  signal?.throwIfAborted();
  const objectUrl = URL.createObjectURL(blob);
  try { await validateImage(objectUrl, signal); }
  catch (error) { URL.revokeObjectURL(objectUrl); throw error; }
  if (epoch !== (imageEpochs.get(scope) || 0)) {
    URL.revokeObjectURL(objectUrl); throw new DOMException("项目已切换", "AbortError");
  }
  const previous = images.get(key); if (previous) URL.revokeObjectURL(previous.objectUrl);
  images.set(key, { objectUrl, bytes: blob.size });
  let bytes = [...images.values()].reduce((sum, entry) => sum + entry.bytes, 0);
  for (const [oldKey, entry] of images) {
    if (bytes <= MAX_IMAGE_BYTES || oldKey === key) break;
    URL.revokeObjectURL(entry.objectUrl); images.delete(oldKey); bytes -= entry.bytes;
  }
}

function validateImage(url: string, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal?.throwIfAborted();
    const image = new Image();
    const finish = (error?: Error) => {
      signal?.removeEventListener("abort", abort); clearTimeout(timer);
      image.onload = null; image.onerror = null;
      if (error) reject(error); else resolve();
    };
    const abort = () => { image.src = ""; finish(new DOMException("已取消", "AbortError")); };
    const timer = setTimeout(() => finish(new Error("页面加载超时，请重试；当前课件已保留。")), 20000);
    signal?.addEventListener("abort", abort, { once: true });
    image.onload = () => finish();
    image.onerror = () => finish(new Error("页面图像加载失败，请重试；当前课件已保留。"));
    image.src = url;
  });
}
