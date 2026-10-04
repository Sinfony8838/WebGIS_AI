export type BasemapLoadPhase = "loading" | "ready" | "error";

/** A load is ready only after a real tile arrives; silence is bounded. */
export class BasemapLoadWatchdog {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private disposed = false;
  private loaded = false;
  private phase: BasemapLoadPhase = "loading";

  constructor(private update: (phase: BasemapLoadPhase) => void, timeoutMs = 12_000) {
    update("loading");
    this.timer = setTimeout(() => {
      if (!this.disposed && !this.loaded) { this.phase = "error"; update("error"); }
    }, timeoutMs);
  }

  ready() {
    if (this.disposed) return;
    this.loaded = true;
    this.phase = "ready";
    clearTimeout(this.timer);
    this.update("ready");
  }

  failed() {
    if (!this.disposed && !this.loaded) { this.phase = "error"; this.update("error"); }
  }

  report() { if (!this.disposed) this.update(this.phase); }

  dispose() {
    this.disposed = true;
    clearTimeout(this.timer);
  }
}
