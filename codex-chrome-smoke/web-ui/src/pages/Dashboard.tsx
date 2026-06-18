import { useEffect, useMemo, useState } from "react";
import type { PageId, PlatformNavKey } from "../types";
import { api, type ApiCase, type ApiReportListItem, type ApiRun, type CaseDraft, type Project, type Requirement } from "../data/api";
import { Card } from "../components/Card";
import { StatusPill } from "../components/StatusPill";

type Health = {
  status: string;
  runner: string;
  api_version?: string;
};

type DashboardState = {
  health: Health | null;
  projects: Project[];
  requirements: Requirement[];
  drafts: CaseDraft[];
  cases: ApiCase[];
  runs: ApiRun[];
  reports: ApiReportListItem[];
  errors: string[];
};

const EMPTY_STATE: DashboardState = {
  health: null,
  projects: [],
  requirements: [],
  drafts: [],
  cases: [],
  runs: [],
  reports: [],
  errors: [],
};

function isRunning(run: ApiRun) {
  return ["queued", "running"].includes(run.status.toLowerCase());
}

function isPassed(value: string) {
  return value.toLowerCase() === "passed" || value.toLowerCase() === "completed";
}

function isFailed(value: string) {
  return value.toLowerCase() === "failed";
}

function formatTime(value?: string | null) {
  if (!value) return "暂无时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function readSettled<T>(result: PromiseSettledResult<T>, label: string, errors: string[]): T | null {
  if (result.status === "fulfilled") return result.value;
  errors.push(`${label} 读取失败`);
  return null;
}

export function Dashboard({ onNavigate }: { onNavigate: (page: PageId, navKey?: PlatformNavKey) => void }) {
  const [state, setState] = useState<DashboardState>(EMPTY_STATE);

  useEffect(() => {
    async function loadDashboard() {
      const errors: string[] = [];
      const [health, projects, requirements, drafts, cases, runs, reports] = await Promise.allSettled([
        api.health(),
        api.listProjects(),
        api.requirements(),
        api.caseDrafts(),
        api.cases(),
        api.runs(),
        api.reports(),
      ]);
      setState({
        health: readSettled(health, "平台健康", errors),
        projects: readSettled(projects, "项目", errors) || [],
        requirements: readSettled(requirements, "需求", errors) || [],
        drafts: readSettled(drafts, "草稿", errors) || [],
        cases: readSettled(cases, "用例", errors) || [],
        runs: readSettled(runs, "执行任务", errors) || [],
        reports: readSettled(reports, "测试报告", errors) || [],
        errors,
      });
    }
    void loadDashboard();
  }, []);

  const stats = useMemo(() => {
    const passed = state.runs.filter((run) => isPassed(run.status)).length;
    const running = state.runs.filter(isRunning).length;
    const failed = state.runs.filter((run) => isFailed(run.status)).length;
    const finished = passed + failed;
    const passRate = finished ? Math.round((passed / finished) * 100) : 0;
    const latestRequirement = state.requirements[0] || null;
    const latestRun = state.runs[0] || null;
    const latestReport = state.reports.find((report) => isFailed(report.status)) || state.reports[0] || null;
    return { passed, running, failed, passRate, latestRequirement, latestRun, latestReport };
  }, [state]);

  return (
    <div className="page dashboard qa-dashboard">
      {state.errors.length ? <div className="failure-callout">{state.errors.slice(0, 3).join(" / ")}</div> : null}

      <section className="qa-metrics" aria-label="平台统计">
        <MetricCard label="项目" value={state.projects.length} tag="Projects" />
        <MetricCard label="正式用例" value={state.cases.length} tag="Cases" />
        <MetricCard label="运行中任务" value={stats.running} tag="Running" />
        <MetricCard label="通过率" value={`${stats.passRate}%`} tag={stats.failed ? `${stats.failed} Failed` : "Rate"} danger={stats.failed > 0} />
      </section>

      <section className="qa-hero-grid" aria-label="快捷入口">
        <HeroCard tone="pink" title="AI 测试" subtitle="进入执行中台" icon="A" onClick={() => onNavigate("execution", "ai-test")} />
        <HeroCard tone="blue" title="AI 生成" subtitle="从需求生成用例" icon="G" onClick={() => onNavigate("ai-generate", "ai-generate")} />
        <HeroCard tone="green" title="测试报告" subtitle="查看历史执行报告" icon="R" onClick={() => onNavigate("reports", "reports")} />
      </section>

      <section className="qa-work-grid">
        <Card title="快捷操作">
          <div className="qa-quick-actions">
            <button className="btn btn--outline" onClick={() => onNavigate("requirements", "requirements")} type="button">
              新建需求
            </button>
            <button className="btn btn--outline" onClick={() => onNavigate("ai-generate", "ai-generate")} type="button">
              生成用例
            </button>
            <button className="btn btn--outline" onClick={() => onNavigate("execution", "ai-test")} type="button">
              发起执行
            </button>
          </div>
        </Card>

        <Card title="最近动态">
          <div className="qa-activity-list">
            <div className="qa-activity">
              <StatusPill tone="green">REQ</StatusPill>
              <span>{stats.latestRequirement ? `${stats.latestRequirement.title} / ${stats.latestRequirement.status}` : "暂无需求记录"}</span>
            </div>
            <div className="qa-activity">
              <StatusPill tone="blue">RUN</StatusPill>
              <span>{stats.latestRun ? `${stats.latestRun.case_id || stats.latestRun.id} / ${stats.latestRun.status}` : "暂无执行任务"}</span>
            </div>
            <div className="qa-activity">
              <StatusPill tone="amber">RPT</StatusPill>
              <span>{stats.latestReport ? `${stats.latestReport.case_name} / ${stats.latestReport.status} / ${formatTime(stats.latestReport.finished_at || stats.latestReport.started_at)}` : "暂无测试报告"}</span>
            </div>
          </div>
        </Card>

        <Card title="Runner 状态">
          <div className="qa-runner-box">
            <StatusPill tone={state.health ? "green" : "amber"}>{state.health ? "Ready" : "Unknown"}</StatusPill>
            <strong>{state.health?.runner || "FastAPI / Runner 未连接"}</strong>
            <span>正式用例 {state.cases.length} 条 / 草稿 {state.drafts.length} 份</span>
          </div>
        </Card>
      </section>
    </div>
  );
}

function MetricCard({ label, value, tag, danger = false }: { label: string; value: number | string; tag: string; danger?: boolean }) {
  return (
    <article className="qa-metric-card">
      <span>{label}</span>
      <strong className={danger ? "is-danger" : ""}>{value}</strong>
      <small>{tag}</small>
    </article>
  );
}

function HeroCard({
  tone,
  title,
  subtitle,
  icon,
  onClick,
}: {
  tone: "pink" | "blue" | "green";
  title: string;
  subtitle: string;
  icon: string;
  onClick: () => void;
}) {
  return (
    <button className={`qa-hero-card qa-hero-card--${tone}`} onClick={onClick} type="button">
      <span className="qa-hero-card__icon">{icon}</span>
      <div>
        <strong>{title}</strong>
        <p>{subtitle}</p>
      </div>
    </button>
  );
}
