type Props = { fileName: string; message: string; busy: boolean; onRetry: () => void; onSimplePreview: () => void; onClose: () => void };

export function PptImportFailure({ fileName, message, busy, onRetry, onSimplePreview, onClose }: Props) {
  return <section className="ppt-import-failure" role="alert" aria-label="PPT 渲染失败">
    <strong>{fileName} 未完成高保真渲染</strong>
    <p>{message}</p>
    <p>请检查服务器的 PowerPoint 或 LibreOffice 能否打开此课件。简易预览可能丢失字体、母版和复杂图形，授课前请核对原稿。</p>
    <div><button type="button" disabled={busy} onClick={onRetry}>重新渲染</button>
      <button type="button" disabled={busy} onClick={onSimplePreview}>使用简易预览</button>
      <button type="button" disabled={busy} onClick={onClose}>关闭</button></div>
  </section>;
}
