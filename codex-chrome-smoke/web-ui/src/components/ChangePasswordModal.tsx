/**
 * 修改密码弹窗（md=480）
 *
 * - 3 个输入：原密码 / 新密码 / 确认新密码
 * - 4 种实时校验：原密码空 / 新密码强度 / 两次一致 / 与旧密码不同
 * - 提交：弹窗内错误条 + Toast（成功 / 失败）
 * - 成功 0.3s 后自动登出回登录页
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { Modal } from "./Modal";
import * as authApi from "../data/authApi";
import { checkPasswordRules, isPasswordStrong } from "../data/authApi";
import { useAuth } from "../data/authStore";
import { useToast } from "./Toast";

export type ChangePasswordModalProps = {
  open: boolean;
  onClose: () => void;
  triggerRef?: RefObject<HTMLElement | null>;
};

type FieldName = "old" | "new" | "confirm";
type HintMap = Partial<Record<FieldName, { kind: "error" | "warning" | ""; message: string }>>;

const TRIANGLE_SVG = (
  <svg className="icon-triangle" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <path d="M8 2 L14 13 L2 13 Z" fill="currentColor" />
    <path d="M8 6 V10" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" />
    <path d="M8 11.4 V11.6" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

export function ChangePasswordModal({ open, onClose, triggerRef }: ChangePasswordModalProps) {
  const { state, logout } = useAuth();
  const toast = useToast();
  const userId = state.user?.id || "";

  const [oldPwd, setOldPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [showOld, setShowOld] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [hints, setHints] = useState<HintMap>({});
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const oldInputRef = useRef<HTMLInputElement | null>(null);
  const newInputRef = useRef<HTMLInputElement | null>(null);
  const confirmInputRef = useRef<HTMLInputElement | null>(null);

  // 弹窗打开时清空状态
  useEffect(() => {
    if (open) {
      setOldPwd("");
      setNewPwd("");
      setConfirmPwd("");
      setShowOld(false);
      setShowNew(false);
      setShowConfirm(false);
      setHints({});
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  const checks = useMemo(() => checkPasswordRules(newPwd, oldPwd), [newPwd, oldPwd]);

  const canSubmit = useMemo(() => {
    if (!oldPwd || !newPwd || !confirmPwd) return false;
    if (oldPwd === newPwd) return false;
    if (newPwd !== confirmPwd) return false;
    if (!isPasswordStrong(checks)) return false;
    return true;
  }, [oldPwd, newPwd, confirmPwd, checks]);

  function recomputeHints(nextOld: string, nextNew: string, nextConfirm: string) {
    const next: HintMap = {};

    if (nextOld.length === 0) {
      next.old = { kind: "error", message: "请输入原密码" };
    } else {
      next.old = { kind: "", message: "" };
    }

    if (nextNew.length === 0) {
      next.new = { kind: "", message: "" };
    } else if (!checks.lengthOk) {
      next.new = { kind: "error", message: "密码需 8 位以上" };
    } else if (!checks.hasLetter || !checks.hasNumber) {
      next.new = { kind: "warning", message: "建议同时包含字母和数字" };
    } else if (checks.sameAsOld) {
      next.new = { kind: "error", message: "新密码不能与原密码相同" };
    } else {
      next.new = { kind: "", message: "" };
    }

    if (nextConfirm.length === 0) {
      next.confirm = { kind: "", message: "" };
    } else if (nextConfirm !== nextNew) {
      next.confirm = { kind: "error", message: "两次输入的密码不一致" };
    } else {
      next.confirm = { kind: "", message: "" };
    }

    setHints(next);
  }

  function onOldChange(v: string) {
    setOldPwd(v);
    setError(null);
    recomputeHints(v, newPwd, confirmPwd);
  }
  function onNewChange(v: string) {
    setNewPwd(v);
    setError(null);
    recomputeHints(oldPwd, v, confirmPwd);
  }
  function onConfirmChange(v: string) {
    setConfirmPwd(v);
    setError(null);
    recomputeHints(oldPwd, newPwd, v);
  }

  async function submit() {
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      await authApi.changePassword(userId, oldPwd, newPwd);
      toast.show({ kind: "success", message: "密码修改成功，请重新登录" });
      onClose();
      // 0.3s 后登出回登录页
      window.setTimeout(() => {
        void logout();
      }, 300);
    } catch (e) {
      const err = e as Error & { code?: string };
      const code = err.code || "UNKNOWN";
      const message = err.message || "操作失败";
      // 业务错误码：OLD_PASSWORD_MISMATCH / PASSWORD_TOO_WEAK / PASSWORD_SAME_AS_OLD / RATE_LIMITED
      setError(message);
      toast.show({ kind: "error", message });
      if (code === "OLD_PASSWORD_MISMATCH") {
        setHints((prev) => ({ ...prev, old: { kind: "error", message } }));
      } else if (code === "PASSWORD_TOO_WEAK" || code === "PASSWORD_SAME_AS_OLD") {
        setHints((prev) => ({ ...prev, new: { kind: "error", message } }));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={() => {
        if (!submitting) onClose();
      }}
      title="修改密码"
      size="md"
      triggerRef={triggerRef}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose} disabled={submitting}>
            取消
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => void submit()}
            disabled={!canSubmit || submitting}
          >
            {submitting ? "提交中…" : "确认修改"}
          </button>
        </>
      }
    >
      {error ? (
        <div className="modal-error" role="alert">
          <span className="modal-error__icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <path d="M12 8v4" />
              <path d="M12 16.4V16.6" />
            </svg>
          </span>
          <span>{error}</span>
        </div>
      ) : null}
      <div className="form-field">
        <label className="form-field__label" htmlFor="pwd-old">原密码</label>
        <div className="form-field__input-wrap">
          <input
            ref={oldInputRef}
            id="pwd-old"
            className={`form-field__input ${hints.old?.kind === "error" ? "is-invalid" : ""}`}
            type={showOld ? "text" : "password"}
            autoComplete="current-password"
            value={oldPwd}
            onChange={(e) => onOldChange(e.target.value)}
          />
          <button
            type="button"
            className="form-field__toggle"
            aria-label={showOld ? "隐藏原密码" : "显示原密码"}
            onClick={() => setShowOld((v) => !v)}
            tabIndex={-1}
          >
            {showOld ? <EyeOffIcon /> : <EyeIcon />}
          </button>
        </div>
        <FieldHint hint={hints.old} />
      </div>
      <div className="form-field">
        <label className="form-field__label" htmlFor="pwd-new">新密码</label>
        <div className="form-field__input-wrap">
          <input
            ref={newInputRef}
            id="pwd-new"
            className={`form-field__input ${hints.new?.kind === "error" ? "is-invalid" : ""}`}
            type={showNew ? "text" : "password"}
            autoComplete="new-password"
            value={newPwd}
            onChange={(e) => onNewChange(e.target.value)}
          />
          <button
            type="button"
            className="form-field__toggle"
            aria-label={showNew ? "隐藏新密码" : "显示新密码"}
            onClick={() => setShowNew((v) => !v)}
            tabIndex={-1}
          >
            {showNew ? <EyeOffIcon /> : <EyeIcon />}
          </button>
        </div>
        <FieldHint hint={hints.new} />
        {newPwd.length > 0 ? (
          <ul className="pwd-rules" aria-label="密码规则">
            <li className={checks.lengthOk ? "is-ok" : ""}>≥ 8 位</li>
            <li className={checks.hasLetter ? "is-ok" : ""}>含字母</li>
            <li className={checks.hasNumber ? "is-ok" : ""}>含数字</li>
            <li className={!checks.sameAsOld && newPwd.length > 0 ? "is-ok" : ""}>与原密码不同</li>
          </ul>
        ) : null}
      </div>
      <div className="form-field">
        <label className="form-field__label" htmlFor="pwd-confirm">确认新密码</label>
        <div className="form-field__input-wrap">
          <input
            ref={confirmInputRef}
            id="pwd-confirm"
            className={`form-field__input ${hints.confirm?.kind === "error" ? "is-invalid" : ""}`}
            type={showConfirm ? "text" : "password"}
            autoComplete="new-password"
            value={confirmPwd}
            onChange={(e) => onConfirmChange(e.target.value)}
          />
          <button
            type="button"
            className="form-field__toggle"
            aria-label={showConfirm ? "隐藏确认密码" : "显示确认密码"}
            onClick={() => setShowConfirm((v) => !v)}
            tabIndex={-1}
          >
            {showConfirm ? <EyeOffIcon /> : <EyeIcon />}
          </button>
        </div>
        <FieldHint hint={hints.confirm} />
      </div>
    </Modal>
  );
}

function FieldHint({ hint }: { hint?: { kind: "error" | "warning" | ""; message: string } }) {
  if (!hint || !hint.message) {
    return <div className="form-field__hint" aria-live="polite" />;
  }
  const cls = hint.kind === "error" ? "is-error" : hint.kind === "warning" ? "is-warning" : "";
  return (
    <div className={`form-field__hint ${cls}`} aria-live="polite">
      {TRIANGLE_SVG}
      <span>{hint.message}</span>
    </div>
  );
}

function EyeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 3l18 18" />
      <path d="M10.6 6.2A10.7 10.7 0 0 1 12 6c6.5 0 10 6 10 6a14.6 14.6 0 0 1-3.3 4.1" />
      <path d="M6.2 6.2A14.6 14.6 0 0 0 2 12s3.5 6 10 6a10.7 10.7 0 0 0 4.4-.9" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </svg>
  );
}
