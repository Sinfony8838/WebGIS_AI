import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import "./ClassroomImageDialog.css";

type Props = { image: { name: string; url: string } | null; kind: "图例" | "题图"; onClose: () => void };

export function ClassroomImageDialog({ image, kind, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    if (!image) return;
    const previousFocus = document.activeElement;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.stopPropagation(); onCloseRef.current(); }
      if (event.key === "Tab") { event.preventDefault(); closeRef.current?.focus(); }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, [image]);
  if (!image) return null;
  return createPortal(<div className="classroom-image-backdrop" onClick={onClose}>
    <section className="classroom-image-dialog" role="dialog" aria-modal="true" aria-label={`${image.name}放大${kind}`} onClick={event => event.stopPropagation()}>
      <header><strong>{image.name} · {kind}</strong><button ref={closeRef} type="button" onClick={onClose}>关闭{kind}</button></header>
      <img src={image.url} alt={`${image.name}放大${kind}`}/>
    </section>
  </div>, document.body);
}
