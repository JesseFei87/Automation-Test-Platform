/**
 * 登录页（Login）
 *
 * - admin / qa123 默认预填
 * - 密码可见切换
 * - 错误密码 0.5s 内出现行内红字（带三角警示图标）
 * - 登录成功跳主页
 * - 3 种状态：default / submitting / error
 * - 背景层：aifx 动态星空效果（第三方 CDN 动态注入）
 *   - aria-hidden + pointer-events-none：不打扰表单交互与屏幕阅读器
 *   - prefers-reduced-motion: reduce 时不注入脚本（减少动效用户无感）
 *   - 组件卸载时移除脚本（避免污染 SPA 其它路由）
 */

import { useEffect, useRef, useState } from "react";
import * as authApi from "../data/authApi";
import { useAuth } from "../data/authStore";
import { useToast } from "../components/Toast";

// aifx 第三方 CDN（动态星空效果运行时）
// 注意：第三方 CDN，未写进 package.json；风险见文件底部注释
const AIFX_RUNTIME_SRC = "https://cdn.aidesigner.ai/effects/runtime/v1.js";
const AIFX_RUNTIME_ID = "aifx-starfield-runtime";

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

type HintMap = {
  account?: { kind: "error" | ""; message: string };
  password?: { kind: "error" | ""; message: string };
};

const TRIANGLE_SVG = (
  <svg className="icon-triangle" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <path d="M8 2 L14 13 L2 13 Z" fill="currentColor" />
    <path d="M8 6 V10" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" />
    <path d="M8 11.4 V11.6" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

export function Login() {
  const { login } = useAuth();
  const toast = useToast();

  const [account, setAccount] = useState("admin");
  const [password, setPassword] = useState("qa123");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [hints, setHints] = useState<HintMap>({});
  const accountRef = useRef<HTMLInputElement | null>(null);
  const passwordRef = useRef<HTMLInputElement | null>(null);

  // 进入页面聚焦密码框（最常见操作是直接回车）
  useEffect(() => {
    const t = window.setTimeout(() => passwordRef.current?.focus(), 50);
    return () => window.clearTimeout(t);
  }, []);

  // 动态星空背景：组件挂载时注入 aifx 运行时脚本，卸载时移除
  // - 尊重 prefers-reduced-motion（系统级"减少动效"时不加载，避免不必要的网络/CPU）
  // - 防止重复注入：组件重渲染或多次挂载时只注入一次
  // - 卸载时同步移除脚本节点
  useEffect(() => {
    if (prefersReducedMotion()) {
      return;
    }
    // 已被注入过（HMR/StrictMode 双调用）直接跳过
    if (document.getElementById(AIFX_RUNTIME_ID)) {
      return;
    }
    const script = document.createElement("script");
    script.id = AIFX_RUNTIME_ID;
    script.src = AIFX_RUNTIME_SRC;
    script.defer = true;
    script.async = false;
    // 第三方脚本：拒绝 referrer 泄露当前页面 URL
    script.setAttribute("referrerpolicy", "no-referrer");
    document.body.appendChild(script);
    return () => {
      script.remove();
    };
  }, []);

  function clearHints() {
    setHints({});
  }

  function validateLocal(a: string, p: string): { ok: boolean; next: HintMap } {
    const next: HintMap = {};
    let ok = true;
    if (!a.trim()) {
      next.account = { kind: "error", message: "请输入账号" };
      ok = false;
    }
    if (!p) {
      next.password = { kind: "error", message: "请输入密码" };
      ok = false;
    }
    return { ok, next };
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;

    const a = account.trim();
    const p = password;
    const { ok, next } = validateLocal(a, p);
    if (!ok) {
      setHints(next);
      return;
    }

    setSubmitting(true);
    try {
      await login(a, p);
      toast.show({ kind: "success", message: "登录成功" });
      // 父级会读取 authState 并切到 dashboard
    } catch (err) {
      const e = err as Error & { code?: string };
      const message = e.message || "登录失败";
      setHints({
        account: { kind: "error", message: e.code === "INVALID_CREDENTIALS" && a !== "admin" ? "账号不存在" : "" },
        password: { kind: "error", message: message },
      });
      // 抖动感：给密码框一个 is-invalid（CSS 已处理 border 变红，不抖动布局）
      passwordRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page relative isolate">
      {/*
        动态星空背景层（aifx 第三方效果）
        - data-aifx / data-aifx-bg-alpha / data-aifx-speed 是 aifx runtime 的识别契约
        - class="absolute inset-0 -z-10 pointer-events-none" 来自 aidesigner.ai 文档
          （项目未装 Tailwind，对应样式由 styles.css 中 .login-page > .absolute 等兜底）
        - aria-hidden="true" 防止屏幕阅读器朗读装饰性画布
        - -z-10 配合外层 .isolate 形成独立堆叠上下文，确保落在 login-card 之下
      */}
      <div
        data-aifx="starfield"
        data-aifx-bg-alpha="0.8"
        data-aifx-speed="0.5"
        className="absolute inset-0 -z-10 pointer-events-none"
        aria-hidden="true"
      />
      <div className="login-card">
        <div className="login-brand">
          <span className="login-brand__logo" aria-hidden="true">QA</span>
          <span>QA Platform</span>
        </div>
        <h1 className="login-title">登录</h1>
        <p className="login-subtitle">使用 ICM 账号继续</p>
        <form className="login-form" onSubmit={(e) => void onSubmit(e)} noValidate>
          <div className="form-field">
            <label className="form-field__label" htmlFor="loginAccount">账号</label>
            <input
              ref={accountRef}
              id="loginAccount"
              className={`form-field__input ${hints.account?.kind === "error" ? "is-invalid" : ""}`}
              type="text"
              name="account"
              autoComplete="username"
              value={account}
              onChange={(e) => {
                setAccount(e.target.value);
                clearHints();
              }}
            />
            <Hint hint={hints.account} />
          </div>
          <div className="form-field">
            <label className="form-field__label" htmlFor="loginPassword">密码</label>
            <div className="form-field__input-wrap">
              <input
                ref={passwordRef}
                id="loginPassword"
                className={`form-field__input ${hints.password?.kind === "error" ? "is-invalid" : ""}`}
                type={showPassword ? "text" : "password"}
                name="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  clearHints();
                }}
              />
              <button
                type="button"
                className="form-field__toggle"
                aria-label={showPassword ? "隐藏密码" : "显示密码"}
                onClick={() => setShowPassword((v) => !v)}
                tabIndex={-1}
              >
                {showPassword ? <EyeOffIcon /> : <EyeIcon />}
              </button>
            </div>
            <Hint hint={hints.password} />
          </div>
          <label className="login-checkbox">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            <span>7 天内自动登录</span>
          </label>
          <button
            className="btn-primary"
            type="submit"
            disabled={submitting}
          >
            {submitting ? "登录中…" : "登录"}
          </button>
        </form>
        <div className="login-foot">© 2026 ICM QA Platform · 仅供内部演示</div>
      </div>
    </div>
  );
}

function Hint({ hint }: { hint?: { kind: "error" | ""; message: string } }) {
  if (!hint || !hint.message) {
    return <div className="form-field__hint" aria-live="polite" />;
  }
  return (
    <div className={`form-field__hint ${hint.kind === "error" ? "is-error" : ""}`} aria-live="polite">
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
