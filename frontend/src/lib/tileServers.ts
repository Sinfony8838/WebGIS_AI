const unavailableUntil = new Map<string, number>();
const COOLDOWN_MS = 60_000;

function interchangeableServers(templates: string[]): URL[] {
  try {
    const parsed = templates.map(url => new URL(url));
    const first = parsed[0];
    return parsed.every(url => url.protocol === first.protocol && url.pathname === first.pathname && url.search === first.search)
      ? parsed : [];
  } catch { return []; }
}

/** Rotate only among explicitly configured mirrors with identical tile paths. */
export function alternateTileUrl(current: string, templates: string[], failed = false): string | undefined {
  const servers = interchangeableServers(templates);
  if (servers.length < 2) return undefined;
  let url: URL;
  try { url = new URL(current); } catch { return undefined; }
  const index = servers.findIndex(server => server.origin === url.origin);
  if (index < 0) return undefined;
  const now = Date.now();
  for (const [origin, expires] of unavailableUntil) if (expires <= now) unavailableUntil.delete(origin);
  if (failed) unavailableUntil.set(url.origin, now + COOLDOWN_MS);
  else if (!unavailableUntil.has(url.origin)) return undefined;
  for (let offset = 1; offset < servers.length; offset++) {
    const next = servers[(index + offset) % servers.length];
    if (!unavailableUntil.has(next.origin)) {
      url.host = next.host;
      return url.href;
    }
  }
  return undefined;
}

export function healthyTileUrl(url: string, templates: string[]): string {
  return alternateTileUrl(url, templates) || url;
}

/** Native image loading retains HTTP caching; retry at most one configured mirror. */
export async function loadTileImage(url: string, templates: string[], crossOrigin: string, signal?: AbortSignal): Promise<HTMLImageElement> {
  let next = healthyTileUrl(url, templates);
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      return await new Promise<HTMLImageElement>((resolve, reject) => {
        if (signal?.aborted) { reject(new Error("Tile load cancelled")); return; }
        const image = new Image();
        image.crossOrigin = crossOrigin;
        let settled = false;
        const cleanup = () => {
          window.clearTimeout(timer);
          image.onload = image.onerror = null;
          signal?.removeEventListener("abort", cancel);
        };
        const fail = () => {
          if (settled) return;
          settled = true;
          cleanup(); image.src = ""; reject(new Error("Tile unavailable"));
        };
        const cancel = () => {
          if (settled) return;
          settled = true;
          cleanup(); image.src = ""; reject(new Error("Tile load cancelled"));
        };
        const ready = () => {
          if (settled) return;
          settled = true;
          cleanup(); resolve(image);
        };
        const timer = window.setTimeout(fail, templates.length > 1 ? 4000 : 8000);
        image.onload = () => {
          // ImageTile.setImage() marks the tile LOADED immediately, bypassing
          // OpenLayers' normal decode gate. Keep the timeout and abort listener
          // until decoded pixels are ready for the canvas renderer.
          if (typeof image.decode === "function") {
            void image.decode().then(ready, fail);
          } else {
            ready();
          }
        };
        image.onerror = fail;
        signal?.addEventListener("abort", cancel, { once: true });
        image.src = next;
      });
    } catch (error) {
      if (signal?.aborted) throw error;
      const alternate = alternateTileUrl(next, templates, true);
      if (attempt > 0 || !alternate) throw error;
      next = alternate;
    }
  }
  throw new Error("Tile unavailable");
}
