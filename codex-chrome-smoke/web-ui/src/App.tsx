import { useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import type { PageId, PlatformNavKey } from "./types";
import { api, type AISettings } from "./data/api";
import { platformNavItems } from "./data/navigation";
import { buildAppHash, parseAppRoute, type AppRoute } from "./routing";
import { Dashboard } from "./pages/Dashboard";
import { ProjectManagement } from "./pages/ProjectManagement";
import { RequirementManagement } from "./pages/RequirementManagement";
import { RequirementsWorkspace } from "./pages/RequirementsWorkspace";
import { TestPointsMap } from "./pages/TestPointsMap";
import { CaseToolbox } from "./pages/CaseToolbox";
import { Recorder } from "./pages/Recorder";
import { ExecutionCenter } from "./pages/ExecutionCenter";
import { ReportDetail } from "./pages/ReportDetail";
import { ElementKnowledge } from "./pages/ElementKnowledge";
import { SystemSettings } from "./pages/SystemSettings";
import { Login } from "./pages/Login";
import { AuthProvider, useAuth } from "./data/authStore";
import { ToastProvider, useToast } from "./components/Toast";
import { Avatar } from "./components/Avatar";
import { ChangePasswordModal } from "./components/ChangePasswordModal";
import { AvatarEditModal } from "./components/AvatarEditModal";
import { ConfirmDialog, ConfirmProvider } from "./components/ConfirmDialog";
import { ThemeToggle, useThemeMode } from "./components/ThemeToggle";

// ============================================================
//  用户菜单：3 项 + 分隔线
// ============================================================
type UserMenuAction = "edit-avatar" | "change-password" | "logout";

function UserMenuTrigger({
  onAction,
  triggerButtonRef,
}: {
  onAction: (action: UserMenuAction, triggerEl: HTMLElement | null) => void;
  triggerButtonRef?: RefObject<HTMLButtonElement | null>;
}) {
  const { state } = useAuth();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const localTriggerRef = useRef<HTMLButtonElement | null>(null);
  const triggerRef = triggerButtonRef || localTriggerRef;
  const user = state.user;
  const displayName = user?.displayName || user?.username || "?";

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open, triggerRef]);

  function triggerAction(action: UserMenuAction) {
    setOpen(false);
    // 把触发菜单的 button 元素也回传给上层（弹窗关闭时焦点回退）
    onAction(action, triggerRef.current);
  }

  return (
    <div ref={wrapperRef} className="user-menu-wrapper">
      <button
        ref={triggerRef}
        type="button"
        className="user-menu-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="账号菜单"
        onClick={() => setOpen((prev) => !prev)}
      >
        <Avatar
          username={user?.username}
          displayName={user?.displayName}
          src={user?.avatarUrl}
          size="sm"
        />
        <svg
          className={`user-menu-trigger__caret ${open ? "is-open" : ""}`}
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden="true"
        >
          <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open ? (
        <div className="user-menu" role="menu" aria-label="账号操作">
          <div className="user-menu__header">
            <Avatar
              username={user?.username}
              displayName={user?.displayName}
              src={user?.avatarUrl}
              size="md"
            />
            <div className="user-menu__id">
              <strong>{displayName}</strong>
            </div>
          </div>
          <button
            type="button"
            role="menuitem"
            className="user-menu__item"
            onClick={() => triggerAction("edit-avatar")}
          >
            <UserCircleIcon />
            <span>修改头像</span>
          </button>
          <button
            type="button"
            role="menuitem"
            className="user-menu__item"
            onClick={() => triggerAction("change-password")}
          >
            <LockIcon />
            <span>修改密码</span>
          </button>
          <div className="user-menu__divider" role="separator" />
          <button
            type="button"
            role="menuitem"
            className="user-menu__item user-menu__item--danger"
            onClick={() => triggerAction("logout")}
          >
            <LogOutIcon />
            <span>退出登录</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}

// ============================================================
//  路由状态机 + 弹窗状态
// ============================================================
const LAST_PAGE_STORAGE_KEY = "icm.currentPage";
const PAGE_IDS: PageId[] = ["dashboard", "projects", "requirements", "ai-generate", "points", "cases", "recorder", "execution", "reports", "element-knowledge", "settings"];

function navKeyForPage(pageId: PageId, navKey?: PlatformNavKey): PlatformNavKey {
  return navKey || platformNavItems.find((candidate) => candidate.page === pageId)?.key || "dashboard";
}

function readInitialRoute(): AppRoute {
  if (typeof window === "undefined") return { page: "dashboard" };
  const storedPage = window.localStorage.getItem(LAST_PAGE_STORAGE_KEY);
  const fallback = PAGE_IDS.includes(storedPage as PageId) ? (storedPage as PageId) : "dashboard";
  return parseAppRoute(window.location.hash, fallback);
}

function rememberPage(pageId: PageId) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(LAST_PAGE_STORAGE_KEY, pageId);
  }
}

type ModalKind = "edit-avatar" | "change-password" | "logout" | null;

function ShellApp() {
  const { state, logout } = useAuth();
  const toast = useToast();
  const { mode: themeMode, toggle: toggleTheme } = useThemeMode();
  const [initialRoute] = useState(() => readInitialRoute());
  const [page, setPage] = useState<PageId>(initialRoute.page);
  const [activeNavKey, setActiveNavKey] = useState<PlatformNavKey>(() => navKeyForPage(initialRoute.page));
  const [reportRunId, setReportRunId] = useState(initialRoute.page === "reports" ? initialRoute.runId || "" : "");
  const [executionRunId, setExecutionRunId] = useState(initialRoute.page === "execution" ? initialRoute.runId || "" : "");
  const [caseDraftId, setCaseDraftId] = useState(initialRoute.page === "cases" ? initialRoute.draftId : undefined);
  const [aiSettings, setAiSettings] = useState<AISettings | null>(null);
  const [aiOnline, setAiOnline] = useState<boolean | null>(null);
  const [hasOpenedAIGenerate, setHasOpenedAIGenerate] = useState(() => initialRoute.page === "ai-generate");
  const [modelSwitching, setModelSwitching] = useState(false);
  const checkingAIRef = useRef(false);
  const modelLabel = aiSettings?.model || "AI 未配置";
  const aiStatusLabel = aiOnline === null ? "检测中" : aiOnline ? "在线" : "离线";

  const [modal, setModal] = useState<ModalKind>(null);
  const [modalTrigger, setModalTrigger] = useState<HTMLElement | null>(null);
  const userMenuTriggerRef = useRef<HTMLButtonElement | null>(null);

  async function refreshAISettings() {
    try {
      setAiSettings(await api.aiSettings());
    } catch {
      setAiSettings(null);
    }
  }

  async function refreshAIStatus() {
    if (checkingAIRef.current) return;
    checkingAIRef.current = true;
    try {
      const result = await api.testAIConnection();
      setAiOnline(result.status === "ok");
    } catch {
      setAiOnline(false);
    } finally {
      checkingAIRef.current = false;
    }
  }

  useEffect(() => {
    if (state.status === "authenticated") {
      void refreshAISettings();
      void refreshAIStatus();
    }
  }, [state.status]);

  useEffect(() => {
    if (state.status !== "authenticated") return;
    const timer = window.setInterval(() => void refreshAIStatus(), 30_000);
    return () => window.clearInterval(timer);
  }, [state.status]);

  useEffect(() => {
    setModelSwitching(true);
    const timer = window.setTimeout(() => setModelSwitching(false), 520);
    return () => window.clearTimeout(timer);
  }, [modelLabel]);

  useEffect(() => {
    function applyBrowserRoute() {
      const route = readInitialRoute();
      setPage(route.page);
      setActiveNavKey(navKeyForPage(route.page));
      setReportRunId(route.page === "reports" ? route.runId || "" : "");
      setExecutionRunId(route.page === "execution" ? route.runId || "" : "");
      setCaseDraftId(route.page === "cases" ? route.draftId : undefined);
      if (route.page === "ai-generate") setHasOpenedAIGenerate(true);
      rememberPage(route.page);
    }

    const canonicalHash = buildAppHash(initialRoute);
    if (window.location.hash !== canonicalHash) {
      window.history.replaceState(null, "", canonicalHash);
    }
    window.addEventListener("popstate", applyBrowserRoute);
    window.addEventListener("hashchange", applyBrowserRoute);
    return () => {
      window.removeEventListener("popstate", applyBrowserRoute);
      window.removeEventListener("hashchange", applyBrowserRoute);
    };
  }, [initialRoute]);

  function openReport(runId: string) {
    navigate("reports", "reports", { runId });
  }

  function openExecution(runId: string) {
    navigate("execution", "ai-test", { runId });
  }

  function openCaseDraft(draftId: number) {
    navigate("cases", "cases", { draftId });
  }

  function navigate(pageId: PageId, navKey?: PlatformNavKey, routeState: Pick<AppRoute, "runId" | "draftId"> = {}) {
    if (pageId === "ai-generate") {
      setHasOpenedAIGenerate(true);
    }
    setReportRunId(pageId === "reports" ? routeState.runId || "" : "");
    setExecutionRunId(pageId === "execution" ? routeState.runId || "" : "");
    setCaseDraftId(pageId === "cases" ? routeState.draftId : undefined);
    setActiveNavKey(navKeyForPage(pageId, navKey));
    setPage(pageId);
    rememberPage(pageId);
    const hash = buildAppHash({ page: pageId, ...routeState });
    if (window.location.hash !== hash) window.history.pushState(null, "", hash);
  }

  function handleUserMenuAction(action: UserMenuAction, triggerEl: HTMLElement | null) {
    setModalTrigger(triggerEl || userMenuTriggerRef.current);
    if (action === "edit-avatar") {
      setModal("edit-avatar");
    } else if (action === "change-password") {
      setModal("change-password");
    } else if (action === "logout") {
      setModal("logout");
    }
  }

  function closeModal() {
    setModal(null);
    setModalTrigger(null);
  }

  // 把 HTMLElement 包装为 ref-like，兼容 Modal 组件的 triggerRef 形参
  const modalTriggerRef = useMemo<RefObject<HTMLElement | null>>(
    () => ({ current: modalTrigger }),
    [modalTrigger],
  );

  // 加载中（bootstrap）
  if (state.status === "loading") {
    return (
      <div className="app app--loading">
        <div className="app-loading" role="status" aria-live="polite">加载中…</div>
      </div>
    );
  }

  // 未登录 → 渲染登录页
  if (state.status !== "authenticated" || !state.user) {
    return (
      <div className="app app--login">
        <Login />
      </div>
    );
  }

  return (
    <div className={`app app--${page}`}>
      <header className="platform-header">
        <button className="platform-brand" type="button" onClick={() => navigate("dashboard", "dashboard")}>
          <span className="platform-brand__logo">QA</span>
          <strong>QA PLATFORM</strong>
        </button>
        <nav className="platform-nav" aria-label="主导航">
          {platformNavItems.map((item) => (
            <button
              className={`platform-nav__item ${activeNavKey === item.key ? "is-active" : ""} ${item.badge ? "has-badge" : ""}`}
              data-nav-key={item.key}
              key={item.key}
              onClick={() => navigate(item.page, item.key)}
              type="button"
            >
              {item.label}
              {item.badge ? <span>{item.badge}</span> : null}
            </button>
          ))}
        </nav>
        <div className="platform-user">
          <span
            aria-label={`当前大模型 ${modelLabel}，${aiStatusLabel}`}
            className={`platform-model-status ${aiOnline === null ? "is-checking" : aiOnline ? "is-online" : "is-offline"} ${modelSwitching ? "is-switching" : ""}`}
            role="status"
            title={`当前大模型：${modelLabel} · ${aiStatusLabel}`}
          >
            <i aria-hidden="true" className="platform-model-status__dot" />
            {modelLabel}
          </span>
          <ThemeToggle mode={themeMode} onToggle={toggleTheme} />
          <UserMenuTrigger
            onAction={handleUserMenuAction}
            triggerButtonRef={userMenuTriggerRef}
          />
        </div>
      </header>
      <main className="main platform-main">
        {page === "dashboard" ? <Dashboard onNavigate={navigate} /> : null}
        {page === "projects" ? <ProjectManagement /> : null}
        {page === "requirements" ? <RequirementManagement onNavigate={navigate} /> : null}
        {hasOpenedAIGenerate ? (
          <div hidden={page !== "ai-generate"}>
            <RequirementsWorkspace />
          </div>
        ) : null}
        {page === "points" ? <TestPointsMap /> : null}
        {page === "cases" ? <CaseToolbox initialDraftId={caseDraftId} onRunCreated={openExecution} /> : null}
        {page === "recorder" ? <Recorder /> : null}
        {page === "execution" ? <ExecutionCenter initialRunId={executionRunId} onOpenReport={openReport} onOpenCaseDraft={openCaseDraft} /> : null}
        {page === "reports" ? <ReportDetail initialRunId={reportRunId} onRouteChange={(runId) => navigate("reports", "reports", { runId })} /> : null}
        {page === "element-knowledge" ? <ElementKnowledge /> : null}
        {page === "settings" ? <SystemSettings onAISettingsChange={async () => { await refreshAISettings(); await refreshAIStatus(); }} /> : null}
      </main>

      {/* 三个弹窗（按需挂载） */}
      <ChangePasswordModal
        open={modal === "change-password"}
        onClose={closeModal}
        triggerRef={modalTriggerRef}
      />
      <AvatarEditModal
        open={modal === "edit-avatar"}
        onClose={closeModal}
        triggerRef={modalTriggerRef}
      />
      <ConfirmDialog
        open={modal === "logout"}
        title="退出登录"
        description="是否退出当前登录？退出后需要重新输入账号密码。"
        danger
        confirmText="确认退出"
        cancelText="取消"
        triggerRef={modalTriggerRef}
        onClose={closeModal}
        onConfirm={async () => {
          try {
            await logout();
            toast.show({ kind: "info", message: "已退出登录" });
            closeModal();
          } catch (e) {
            toast.show({ kind: "error", message: (e as Error).message || "退出失败" });
          }
        }}
      />
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <ConfirmProvider>
        <AuthProvider>
          <ThemeBoot>
            <ShellApp />
          </ThemeBoot>
        </AuthProvider>
      </ConfirmProvider>
    </ToastProvider>
  );
}

// ============================================================
//  主题启动器：确保即使 Login 页没渲染 topbar 时，
//  documentElement 上的 data-theme 与 localStorage 也已同步
// ============================================================
function ThemeBoot({ children }: { children: React.ReactNode }) {
  useThemeMode();
  return <>{children}</>;
}

// ============================================================
//  菜单图标
// ============================================================
function UserCircleIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 4-7 8-7s8 3 8 7" />
    </svg>
  );
}
function LockIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="4" y="11" width="16" height="9" rx="2" />
      <path d="M8 11V8a4 4 0 1 1 8 0v3" />
    </svg>
  );
}
function LogOutIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" />
      <path d="M10 17l-5-5 5-5" />
      <path d="M5 12h12" />
    </svg>
  );
}
