const TRANSIENT_STATUS = new Set([502, 503, 504, 520, 521, 522, 523, 524, 530]);

/** Retry a transient read once. Never replay writes, auth failures or aborted work. */
export async function fetchReadRequest(input: RequestInfo | URL, init: RequestInit): Promise<Response> {
  const canRetry = String(init.method || "GET").toUpperCase() === "GET";
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await fetch(input, init);
      if (!canRetry || attempt > 0 || !TRANSIENT_STATUS.has(response.status) || init.signal?.aborted) return response;
      await response.body?.cancel();
    } catch (error) {
      if (!canRetry || attempt > 0 || init.signal?.aborted || !(error instanceof TypeError)) throw error;
    }
    await new Promise<void>(resolve => setTimeout(resolve, 350));
    if (init.signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
  }
}
