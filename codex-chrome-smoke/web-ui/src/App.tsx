import { useEffect, useState } from "react";
import type { PageId, PlatformNavKey } from "./types";
import { api, type AISettings } from "./data/api";
import { platformNavItems } from "./data/navigation";
import { Dashboard } from "./pages/Dashboard";
import { ProjectManagement } from "./pages/ProjectManagement";
import { RequirementManagement } from "./pages/RequirementManagement";
import { RequirementsWorkspace } from "./pages/RequirementsWorkspace";
import { TestPointsMap } from "./pages/TestPointsMap";
import { CaseToolbox } from "./pages/CaseToolbox";
import { ExecutionCenter } from "./pages/ExecutionCenter";
import { ReportDetail } from "./pages/ReportDetail";
import { SystemSettings } from "./pages/SystemSettings";

const LAST_PAGE_STORAGE_KEY = "icm.currentPage";
const PAGE_IDS: PageId[] = ["dashboard", "projects", "requirements", "ai-generate", "points", "cases", "execution", "reports", "settings"];

function navKeyForPage(pageId: PageId, navKey?: PlatformNavKey): PlatformNavKey {
  return navKey || platformNavItems.find((candidate) => candidate.page === pageId)?.key || "dashboard";
}

function readInitialPage(): PageId {
  if (typeof window === "undefined") return "dashboard";
  if (window.location.hash.startsWith("#case-toolbox")) return "cases";
  const storedPage = window.localStorage.getItem(LAST_PAGE_STORAGE_KEY);
  return PAGE_IDS.includes(storedPage as PageId) ? (storedPage as PageId) : "dashboard";
}

function rememberPage(pageId: PageId) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(LAST_PAGE_STORAGE_KEY, pageId);
  }
}

export default function App() {
  const [page, setPage] = useState<PageId>(() => readInitialPage());
  const [activeNavKey, setActiveNavKey] = useState<PlatformNavKey>(() => navKeyForPage(readInitialPage()));
  const [reportRunId, setReportRunId] = useState("");
  const [executionRunId, setExecutionRunId] = useState("");
  const [aiSettings, setAiSettings] = useState<AISettings | null>(null);
  const [hasOpenedAIGenerate, setHasOpenedAIGenerate] = useState(() => readInitialPage() === "ai-generate");
  const [modelSwitching, setModelSwitching] = useState(false);
  const modelLabel = aiSettings?.model || "AI 未配置";

  async function refreshAISettings() {
    try {
      setAiSettings(await api.aiSettings());
    } catch {
      setAiSettings(null);
    }
  }

  useEffect(() => {
    void refreshAISettings();
  }, []);

  useEffect(() => {
    setModelSwitching(true);
    const timer = window.setTimeout(() => setModelSwitching(false), 520);
    return () => window.clearTimeout(timer);
  }, [modelLabel]);

  function openReport(runId: string) {
    setReportRunId(runId);
    navigate("reports", "reports");
  }

  function openExecution(runId: string) {
    setExecutionRunId(runId);
    navigate("execution", "ai-test");
  }

  function openCaseDraft(draftId: number) {
    // 跳转到用例工作台；draftId 通过 hash 透传（CaseToolbox 可后续按需解析）
    if (typeof window !== "undefined") {
      window.location.hash = `case-toolbox?draft=${draftId}`;
    }
    navigate("cases", "cases");
  }

  function navigate(pageId: PageId, navKey?: PlatformNavKey) {
    if (pageId === "ai-generate") {
      setHasOpenedAIGenerate(true);
    }
    setActiveNavKey(navKeyForPage(pageId, navKey));
    setPage(pageId);
    rememberPage(pageId);
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
          <span className={modelSwitching ? "is-switching" : undefined}>{modelLabel}</span>
          <strong>admin (System Admin)</strong>
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
        {page === "cases" ? <CaseToolbox onRunCreated={openExecution} /> : null}
        {page === "execution" ? <ExecutionCenter initialRunId={executionRunId} onOpenReport={openReport} onOpenCaseDraft={openCaseDraft} /> : null}
        {page === "reports" ? <ReportDetail initialRunId={reportRunId} /> : null}
        {page === "settings" ? <SystemSettings onAISettingsChange={refreshAISettings} /> : null}
      </main>
    </div>
  );
}
