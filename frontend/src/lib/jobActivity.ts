/** Only a server-confirmed read-only task can release classroom/map controls. */
export class JobActivity<T> {
  private jobs = new Map<T, boolean>();
  add(job: T, readOnly = false) { this.jobs.set(job, readOnly === true); }
  delete(job: T) { return this.jobs.delete(job); }
  has(job: T) { return this.jobs.has(job); }
  get busy() { return this.jobs.size > 0; }
  get mapBusy() { return [...this.jobs.values()].some((readOnly) => !readOnly); }
  closeAll(close: (job: T) => void) { this.jobs.forEach((_, job) => close(job)); this.jobs.clear(); }
}
