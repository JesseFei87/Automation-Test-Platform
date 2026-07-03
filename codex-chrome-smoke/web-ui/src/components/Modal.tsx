/**
 * 通用弹窗（Modal）
 *
 * 规格（design-tokens §2.2）：
 *  - 三档宽度 sm=360 / md=480 / lg=720
 *  - ESC + 点击遮罩 + X + 取消按钮四件套
 *  - 打开时焦点移入弹窗；关闭时焦点返回触发器（triggerRef 可选）
 *  - 锁定 body 滚动；ARIA role="dialog" + aria-modal + aria-labelledby
 *  - 入场动效 320ms / cubic-bezier(0.4,0,0.2,1)
 */

import { useEffect, useRef } from "react";
import type { ReactNode, RefObject } from "react";

export type ModalSize = "sm" | "md" | "lg";

export type ModalProps = {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  size?: ModalSize;
  /** 弹窗 ID（用于 aria-labelledby 关联）；默认内部生成 */
  titleId?: string;
  /** 触发器 ref，关闭时焦点回退到这里 */
  triggerRef?: RefObject<HTMLElement | null>;
  /** 是否允许点击遮罩关闭；默认 true */
  dismissOnMask?: boolean;
  /** body 区域 */
  children: ReactNode;
  /** 底部按钮区（与 body 分离） */
  footer?: ReactNode;
};

let modalIdCounter = 0;
function nextModalId(): string {
  modalIdCounter += 1;
  return `modal-title-${modalIdCounter}`;
}

export function Modal({
  open,
  onClose,
  title,
  size = "md",
  titleId,
  triggerRef,
  dismissOnMask = true,
  children,
  footer,
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const closeBtnRef = useRef<HTMLButtonElement | null>(null);
  const internalTitleId = useRef<string>(titleId || nextModalId());
  const titleElId = titleId || internalTitleId.current;
  const previousFocused = useRef<HTMLElement | null>(null);

  // 打开时：保存当前焦点、移入弹窗；关闭时：还原 body 滚动与焦点
  useEffect(() => {
    if (!open) return;

    previousFocused.current = (typeof document !== "undefined" ? (document.activeElement as HTMLElement | null) : null) || null;

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // 把焦点移到弹窗内第一个可聚焦元素
    const t = window.setTimeout(() => {
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusables = dialog.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      const first = focusables[0] || closeBtnRef.current;
      if (first && typeof first.focus === "function") {
        first.focus();
      }
    }, 0);

    return () => {
      window.clearTimeout(t);
      document.body.style.overflow = prevOverflow;
      // 关闭时焦点回退到触发器（或之前记录的焦点）
      const target = triggerRef?.current || previousFocused.current;
      if (target && typeof target.focus === "function") {
        // 等卸载后再 focus
        window.setTimeout(() => target.focus(), 0);
      }
    };
  }, [open, triggerRef]);

  // ESC 关闭
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  function onMaskClick() {
    if (dismissOnMask) onClose();
  }

  function onDialogClick(e: React.MouseEvent<HTMLDivElement>) {
    // 阻止冒泡到 mask
    e.stopPropagation();
  }

  return (
    <div
      className="modal-mask"
      role="presentation"
      onClick={onMaskClick}
    >
      <div
        ref={dialogRef}
        className={`modal modal--${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleElId}
        onClick={onDialogClick}
      >
        <div className="modal__head">
          <h2 className="modal__title" id={titleElId}>
            {title}
          </h2>
          <button
            ref={closeBtnRef}
            type="button"
            className="modal__close"
            aria-label="关闭"
            onClick={onClose}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M6 6l12 12" />
              <path d="M18 6L6 18" />
            </svg>
          </button>
        </div>
        <div className="modal__body">{children}</div>
        {footer ? <div className="modal__foot">{footer}</div> : null}
      </div>
    </div>
  );
}
