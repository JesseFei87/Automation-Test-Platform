import { useEffect, useState } from "react";
import type { PageId } from "./types";
import { api, type AISettings } from "./data/api";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import { Dashboard } from "./pages/Dashboard";
import { RequirementsWorkspace } from "./pages/RequirementsWorkspace";
import { TestPointsMap } from "./pages/TestPointsMap";
import { CaseToolbox } from "./pages/CaseToolbox";
import { ExecutionCenter } from "./pages/ExecutionCenter";
import { ReportDetail } from "./pages/ReportDetail";
import { SystemSettings } from "./pages/SystemSettings";

const titles: Record<PageId, { title: string; subtitle: string }> = {
  dashboard: {
    title: "ICM AI 自动化测试平台",
    subtitle: "从需求到日常回归的一条龙测试工作台",
  },
  requirements: {
    title: "需求工作台",
    subtitle: "粘贴或上传需求文档，AI 生成测试点并进入可追溯链路。",
  },
  points: {
    title: "测试点思维导图",
    subtitle: "汇总已确认测试点，支持按测试类型或功能模块切换、编辑、导出和生成 YAML。",
  },
  cases: {
    title: "用例工具箱",
    subtitle: "从测试点生成 YAML 草稿，补齐 selector / 输入值 / 断言资产。",
  },
  execution: {
    title: "执行中心",
    subtitle: "选择单 case、链路或全量 batch，由后台队列调用本地 runner。",
  },
  reports: {
    title: "报告详情",
    subtitle: "聚合日志、截图、Markdown 报告与 AI 复盘结论。",
  },
  settings: {
    title: "系统设置",
    subtitle: "集中管理 AI 模型、Runner 执行方式和资产沉淀策略。",
  },
};

export default function App() {
  const [page, setPage] = useState<PageId>("dashboard");
  const [reportRunId, setReportRunId] = useState("");
  const [aiSettings, setAiSettings] = useState<AISettings | null>(null);
  const meta = titles[page];
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
    setPage("reports");
  }

  return (
    <div className={`app app--${page}`}>
      <Sidebar activePage={page} onNavigate={setPage} />
      <main className="main">
        <Topbar dashboard={page === "dashboard"} modelLabel={modelLabel} title={meta.title} subtitle={meta.subtitle} />
        {page === "dashboard" ? <Dashboard onNavigate={setPage} /> : null}
        {page === "requirements" ? <RequirementsWorkspace /> : null}
        {page === "points" ? <TestPointsMap /> : null}
        {page === "cases" ? <CaseToolbox /> : null}
        {page === "execution" ? <ExecutionCenter onOpenReport={openReport} /> : null}
        {page === "reports" ? <ReportDetail initialRunId={reportRunId} /> : null}
        {page === "settings" ? <SystemSettings onAISettingsChange={refreshAISettings} /> : null}
      </main>
    </div>
  );
}
