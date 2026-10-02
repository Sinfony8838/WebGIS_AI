/** Global shortcuts must leave text editing (including inherited contenteditable) alone. */
export function isEditableKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  if (target.closest("input, textarea, select, [role='textbox'], [role='combobox'], [role='spinbutton']")) return true;
  if (target instanceof HTMLElement && target.isContentEditable) return true;
  const editable = target.closest("[contenteditable]");
  return Boolean(editable && editable.getAttribute("contenteditable")?.toLowerCase() !== "false");
}

/** Space/arrows belong to a focused button, link or media control, not the slide deck. */
export function isInteractiveKeyboardTarget(target: EventTarget | null): boolean {
  return isEditableKeyboardTarget(target) || (target instanceof Element && Boolean(
    target.closest("button, a[href], summary, audio, video, [role='button'], [role='slider'], [role='menuitem'], [role='tab']")
  ));
}
