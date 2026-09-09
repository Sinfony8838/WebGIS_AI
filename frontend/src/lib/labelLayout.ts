export type LabelBox = { id: string; left: number; top: number; width: number; height: number };

/** Candidates arrive in teaching priority order; keep every accepted label legible. */
export function selectVisibleLabels(boxes: LabelBox[], width: number, height: number): Set<string> {
  const accepted: LabelBox[] = [];
  for (const box of boxes) {
    if (![box.left, box.top, box.width, box.height].every(Number.isFinite) || box.width <= 0 || box.height <= 0) continue;
    if (box.left < 8 || box.top < 8 || box.left + box.width > width - 8 || box.top + box.height > height - 8) continue;
    if (accepted.some(other => box.left < other.left + other.width + 8 && box.left + box.width + 8 > other.left &&
      box.top < other.top + other.height + 6 && box.top + box.height + 6 > other.top)) continue;
    accepted.push(box);
  }
  return new Set(accepted.map(box => box.id));
}
