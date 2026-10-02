type PageInk = { image: string | null; undo: number[] };
type UndoEntry = { page: string; image: string | null };

/** Compressed canvas snapshots, with one undo budget shared by the whole deck. */
export class BrushHistory {
  private pages = new Map<string, PageInk>();
  private entries = new Map<number, UndoEntry>();
  private order: number[] = [];
  private sequence = 0;

  constructor(private readonly limit = 30) {}

  private page(key: string): PageInk {
    let page = this.pages.get(key);
    if (!page) {
      page = { image: null, undo: [] };
      this.pages.set(key, page);
    }
    return page;
  }

  image(key: string): string | null { return this.page(key).image; }
  canUndo(key: string): boolean { return this.page(key).undo.length > 0; }
  get retainedSteps(): number { return this.order.length; }

  commit(key: string, image: string | null): void {
    const page = this.page(key);
    if (page.image === image) return;
    const id = ++this.sequence;
    this.entries.set(id, { page: key, image: page.image });
    this.order.push(id);
    page.undo.push(id);
    page.image = image;
    while (this.order.length > Math.max(0, this.limit)) {
      const oldest = this.order.shift()!;
      const entry = this.entries.get(oldest)!;
      const owner = this.page(entry.page);
      owner.undo = owner.undo.filter(value => value !== oldest);
      this.entries.delete(oldest);
    }
  }

  undo(key: string): boolean {
    const page = this.page(key);
    const id = page.undo.pop();
    if (id === undefined) return false;
    page.image = this.entries.get(id)!.image;
    this.entries.delete(id);
    this.order = this.order.filter(value => value !== id);
    return true;
  }

  /** Explicit image imports start a new history for this page only. */
  replace(key: string, image: string | null): void {
    const page = this.page(key);
    const removed = new Set(page.undo);
    page.undo.forEach(id => this.entries.delete(id));
    this.order = this.order.filter(id => !removed.has(id));
    page.undo = [];
    page.image = image;
  }
}
