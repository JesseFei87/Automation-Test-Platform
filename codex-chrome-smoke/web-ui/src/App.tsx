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

export default function App() {
  const [page, setPage] = useState<PageId>("dashboard");
  const [activeNavKey, setActiveNavKey] = useState<PlatformNavKey>("dashboard");
  const [reportRunId, setReportRunId] = useState("");
  const [executionRunId, setExecutionRunId] = useState("");
  const [aiSettings, setAiSettings] = useState<AISettings | null>(null);
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

  function openReport(runId: string) {
    setReportRunId(runId);
    setActiveNavKey("reports");
    setPage("reports");
  }

  function openExecution(runId: string) {
    setExecutionRunId(runId);
    setActiveNavKey("ai-test");
    setPage("execution");
  }

  function openCaseDraft(draftId: number) {
    // 跳转到用例工作台；draftId 通过 hash 透传（CaseToolbox 可后续按需解析）
    if (typeof window !== "undefined") {
      window.location.hash = `case-toolbox?draft=${draftId}`;
    }
    setActiveNavKey("cases");
    setPage("cases");
  }

  function navigate(pageId: PageId, navKey?: PlatformNavKey) {
    const item = navKey ? platformNavItems.find((candidate) => candidate.key === navKey) : null;
    setActiveNavKey(item?.key || platformNavItems.find((candidate) => candidate.page === pageId)?.key || "dashboard");
    setPage(pageId);
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
          <span>{modelLabel}</span>
          <strong>admin (System Admin)</strong>
        </div>
      </header>
      <main className="main platform-main">
        {page === "dashboard" ? <Dashboard onNavigate={navigate} /> : null}
        {page === "projects" ? <ProjectManagement /> : null}
        {page === "requirements" ? <RequirementManagement onNavigate={navigate} /> : null}
        {page === "ai-generate" ? <RequirementsWorkspace /> : null}
        {page === "points" ? <TestPointsMap /> : null}
        {page === "cases" ? <CaseToolbox onRunCreated={openExecution} /> : null}
        {page === "execution" ? <ExecutionCenter initialRunId={executionRunId} onOpenReport={openReport} onOpenCaseDraft={openCaseDraft} /> : null}
        {page === "reports" ? <ReportDetail initialRunId={reportRunId} /> : null}
        {page === "settings" ? <SystemSettings onAISettingsChange={refreshAISettings} /> : null}
      </main>
    </div>
  );
}
