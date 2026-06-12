import { API_ORIGIN, type ApiScreenshot } from "../data/api";

export function ScreenshotLightbox({
  screenshot,
  onClose,
}: {
  screenshot: ApiScreenshot | null;
  onClose: () => void;
}) {
  if (!screenshot) return null;

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label="截图放大查看">
      <button className="lightbox__backdrop" onClick={onClose} type="button" aria-label="关闭截图预览" />
      <div className="lightbox__panel">
        <div className="lightbox__header">
          <div>
            <strong>{screenshot.filename}</strong>
            <span>{screenshot.case_id}</span>
          </div>
          <button className="lightbox__close" onClick={onClose} type="button">
            关闭
          </button>
        </div>
        <img alt={screenshot.filename} src={`${API_ORIGIN}${screenshot.url}`} />
      </div>
    </div>
  );
}
