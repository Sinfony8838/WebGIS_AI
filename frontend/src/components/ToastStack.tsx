type ToastItem = {
  id: string;
  tone: "info" | "success" | "error";
  title: string;
  detail?: string;
};

type Props = {
  items: ToastItem[];
  onDismiss: (toastId: string) => void;
};

export type { ToastItem };

export function ToastStack({ items, onDismiss }: Props) {
  return (
    <div className="toast-stack" aria-live="polite" aria-label="通知中心">
      {items.map((item) => (
        <article key={item.id} className={`toast-card ${item.tone}`}>
          <div>
            <strong>{item.title}</strong>
            {item.detail ? <p>{item.detail}</p> : null}
          </div>
          <button type="button" className="toast-close" onClick={() => onDismiss(item.id)} aria-label="关闭通知">
            ×
          </button>
        </article>
      ))}
    </div>
  );
}
