import { createContext, useCallback, useContext, useEffect, useState, type ReactNode, type RefObject } from "react";
import { Modal } from "./Modal";

export type ConfirmDialogOptions = {
  title: string;
  description: string;
  danger?: boolean;
  confirmText?: string;
  cancelText?: string;
};

export type ConfirmDialogProps = ConfirmDialogOptions & {
  open: boolean;
  onConfirm: () => void | Promise<void>;
  onClose: () => void;
  triggerRef?: RefObject<HTMLElement | null>;
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

  useEffect(() => {
    if (!open) setBusy(false);
  }, [open]);

  async function handleConfirm() {
    if (busy) return;
    setBusy(true);
    try {
      await onConfirm();
    } catch {
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
      dismissOnMask={!busy}
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
      <div className={`confirm-dialog__content ${danger ? "is-danger" : ""}`}>
        <span className="confirm-dialog__icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3 2.8 20h18.4z" />
            <path d="M12 9v4M12 17h.01" />
          </svg>
        </span>
        <p>{description}</p>
      </div>
    </Modal>
  );
}

type PendingConfirmation = ConfirmDialogOptions & {
  resolve: (confirmed: boolean) => void;
};

const ConfirmContext = createContext<((options: ConfirmDialogOptions) => Promise<boolean>) | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingConfirmation | null>(null);

  const confirm = useCallback((options: ConfirmDialogOptions) => {
    return new Promise<boolean>((resolve) => {
      setPending({ ...options, resolve });
    });
  }, []);

  function finish(confirmed: boolean) {
    if (!pending) return;
    const current = pending;
    setPending(null);
    current.resolve(confirmed);
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <ConfirmDialog
        open={Boolean(pending)}
        title={pending?.title || ""}
        description={pending?.description || ""}
        danger={pending?.danger}
        confirmText={pending?.confirmText}
        cancelText={pending?.cancelText}
        onClose={() => finish(false)}
        onConfirm={() => finish(true)}
      />
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error("useConfirm must be used within ConfirmProvider");
  return confirm;
}
