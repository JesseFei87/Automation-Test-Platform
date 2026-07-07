/**
 * 主题切换按钮（浅色 ↔ 深色）
 *
 * 行为：
 *  - 初次渲染时从 localStorage("theme") 读取，没有则默认 "light"
 *  - 状态变化时同步写入 localStorage + 在 document.documentElement 上加 data-theme 属性
 *  - CSS 端通过 :root[data-theme="dark"] 选择器覆盖变量
 */

import { useEffect, useState } from "react";

export type ThemeMode = "light" | "dark";

const STORAGE_KEY = "theme";
const ATTR = "data-theme";

function readInitialTheme(): ThemeMode {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return "light";
}

function applyTheme(mode: ThemeMode) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute(ATTR, mode);
}

export function useThemeMode() {
  const [mode, setMode] = useState<ThemeMode>(() => readInitialTheme());

  useEffect(() => {
    applyTheme(mode);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, mode);
    }
  }, [mode]);

  function toggle() {
    setMode((prev) => (prev === "light" ? "dark" : "light"));
  }

  return { mode, toggle, setMode };
}

/**
 * 纯 UI 组件，渲染一个 32×32 的圆形按钮，跟 topbar trigger 风格一致。
 * 父组件通过 <ThemeToggle mode={mode} onToggle={toggle} /> 注入状态。
 */
export function ThemeToggle({
  mode,
  onToggle,
}: {
  mode: ThemeMode;
  onToggle: () => void;
}) {
  const isDark = mode === "dark";
  const label = isDark ? "切换到浅色主题" : "切换到深色主题";

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={onToggle}
      aria-label={label}
      aria-pressed={isDark}
      title={label}
    >
      {isDark ? <MoonIcon /> : <SunIcon />}
    </button>
  );
}

function SunIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2" />
      <path d="M12 20v2" />
      <path d="M4.93 4.93l1.41 1.41" />
      <path d="M17.66 17.66l1.41 1.41" />
      <path d="M2 12h2" />
      <path d="M20 12h2" />
      <path d="M4.93 19.07l1.41-1.41" />
      <path d="M17.66 6.34l1.41-1.41" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}