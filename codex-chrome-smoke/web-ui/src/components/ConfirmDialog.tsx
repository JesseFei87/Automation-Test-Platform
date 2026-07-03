/**
 * 通用确认弹窗（ConfirmDialog）
 *
 * 复用 Modal + sm 档；危险操作走 danger 变体按钮。
 * 用于退出登录、危险删除等确认场景。
 */

import { useState } from "react";
import { Modal } from "./Modal";

export type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description?: string;
  /** 危险操作 → 红色确认按钮 */
  danger?: boolean;
  confirmText?: string;
  cancelText?: string;
  onConfirm: () => void | Promise<void>;
  onClose: () => void;
  /** 触发器 ref，关闭时焦点回退 */
  triggerRef?: React.RefObject<HTMLElement | null>;
};

export function ConfirmDialog({
  open,
  title,
  description,
  danger = false,
  confirmText = "确认",
  cancelText = "取消",
  onConfirm,
  onClose,
  triggerRef,
}: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false);

  async function handleConfirm() {
    if (busy) return;
    setBusy(true);
    try {
      await onConfirm();
      // 成功后再让父级关弹窗
    } catch {
      // 失败时父级通常会展示错误，保持弹窗打开
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={() => {
        if (!busy) onClose();
      }}
      title={title}
      size="sm"
      triggerRef={triggerRef}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>
            {cancelText}
          </button>
          <button
            type="button"
            className={danger ? "btn-danger" : "btn-primary"}
            onClick={handleConfirm}
            disabled={busy}
            autoFocus
          >
            {busy ? "处理中…" : confirmText}
          </button>
        </>
      }
    >
      {description ? <p style={{ margin: 0, color: "var(--text)", fontSize: 14, lineHeight: 1.6 }}>{description}</p> : null}
    </Modal>
  );
}
