/**
 * 全局 Toast 容器
 *
 * - 4 类型：success / error / info / warning
 * - 3s 自动关闭；最多堆叠 3 条
 * - 通过 useToast() hook 调用；Provider 挂在 App 外层
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

export type ToastKind = "success" | "error" | "info" | "warning";

export type ToastInput = {
  id?: string;
  kind?: ToastKind;
  message: string;
  /** 自定义关闭时间（毫秒）；0 表示不自动关闭 */
  duration?: number;
};

type ToastItem = Required<Omit<ToastInput, "duration">> & { duration: number };

type ToastContextValue = {
  show: (toast: ToastInput) => string;
  dismiss: (id: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);
const TOAST_LIMIT = 3;

function makeId(): string {
  return `toast-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef<Map<string, number>>(new Map());

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((it) => it.id !== id));
    const handle = timers.current.get(id);
    if (handle !== undefined) {
      window.clearTimeout(handle);
      timers.current.delete(id);
    }
  }, []);

  const show = useCallback(
    (toast: ToastInput) => {
      const id = toast.id || makeId();
      const item: ToastItem = {
        id,
        kind: toast.kind || "info",
        message: toast.message,
        duration: toast.duration === undefined ? 3000 : toast.duration,
      };
      setItems((prev) => {
        // 限流：超过 3 条移除最早
        const next = [...prev, item];
        if (next.length > TOAST_LIMIT) {
          const removed = next.splice(0, next.length - TOAST_LIMIT);
          for (const r of removed) {
            const handle = timers.current.get(r.id);
            if (handle !== undefined) {
              window.clearTimeout(handle);
              timers.current.delete(r.id);
            }
          }
        }
        return next;
      });

      if (item.duration > 0) {
        const handle = window.setTimeout(() => dismiss(id), item.duration);
        timers.current.set(id, handle);
      }
      return id;
    },
    [dismiss],
  );

  // 卸载时清理所有定时器
  useEffect(() => {
    const map = timers.current;
    return () => {
      for (const handle of map.values()) {
        window.clearTimeout(handle);
      }
      map.clear();
    };
  }, []);

  const value = useMemo<ToastContextValue>(() => ({ show, dismiss }), [show, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastStack items={items} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within <ToastProvider>");
  }
  return ctx;
}

function ToastStack({ items, onDismiss }: { items: ToastItem[]; onDismiss: (id: string) => void }) {
  return (
    <div className="toast-stack" role="region" aria-live="polite" aria-label="通知">
      {items.map((it) => (
        <ToastView key={it.id} item={it} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastView({ item, onDismiss }: { item: ToastItem; onDismiss: (id: string) => void }) {
  return (
    <div className={`toast toast--${item.kind}`} role="status">
      <span className="toast__icon" aria-hidden="true">
        <ToastIcon kind={item.kind} />
      </span>
      <span className="toast__text">{item.message}</span>
      <button
        type="button"
        className="toast__close"
        aria-label="关闭通知"
        onClick={() => onDismiss(item.id)}
      >
        <CloseIcon />
      </button>
    </div>
  );
}

function ToastIcon({ kind }: { kind: ToastKind }) {
  if (kind === "success") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <path d="M8 12l3 3 5-6" />
      </svg>
    );
  }
  if (kind === "warning") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 3 L22 20 H2 Z" />
        <path d="M12 10v4" />
        <path d="M12 16.4V16.6" />
      </svg>
    );
  }
  if (kind === "error") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <path d="M9 9l6 6" />
        <path d="M15 9l-6 6" />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 11v6" />
      <path d="M12 7.6V7.8" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 6l12 12" />
      <path d="M18 6L6 18" />
    </svg>
  );
}
