import { useEffect, useMemo, useState } from "react";
import type { PageId, PlatformNavKey } from "../types";
import { api, type ApiCase, type ApiReport, type ApiRun, type CaseDraft, type Project, type Requirement } from "../data/api";
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
  reports: ApiReport[];
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
  return value.toLowerCase() === "passed";
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
  errors.push(`${label} 读取失败：${result.reason instanceof Error ? result.reason.message : "unknown error"}`);
  return null;
}

function reportTime(report: ApiReport) {
  return formatTime(new Date(report.updated_at * 1000).toISOString());
}

export function Dashboard({ onNavigate }: { onNavigate: (page: PageId, navKey?: PlatformNavKey) => void }) {
  const [state, setState] = useState<DashboardState>(EMPTY_STATE);
  const [loading, setLoading] = useState(true);

  async function loadDashboard() {
    setLoading(true);
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
      health: readSettled(health, "平台健康状态", errors),
      projects: readSettled(projects, "项目", errors) || [],
      requirements: readSettled(requirements, "需求", errors) || [],
      drafts: readSettled(drafts, "YAML 草稿", errors) || [],
      cases: readSettled(cases, "正式用例", errors) || [],
      runs: readSettled(runs, "执行任务", errors) || [],
      reports: readSettled(reports, "测试报告", errors) || [],
      errors,
    });
    setLoading(false);
  }

  useEffect(() => {
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
    const pendingDrafts = state.drafts.filter((draft) => draft.status !== "promoted").length;
    return { passed, running, failed, passRate, latestRequirement, latestRun, latestReport, pendingDrafts };
  }, [state]);

  const recentActivities = [
    stats.latestRequirement
      ? `需求：${stats.latestRequirement.title} · ${stats.latestRequirement.status}`
      : loading
        ? "正在读取最近需求..."
        : "暂无需求记录",
    stats.latestRun
      ? `执行：${stats.latestRun.case_id || stats.latestRun.summary?.display_name || stats.latestRun.id} · ${stats.latestRun.status}`
      : "暂无执行任务",
    stats.latestReport
      ? `报告：${stats.latestReport.case_id} · ${stats.latestReport.status} · ${reportTime(stats.latestReport)}`
      : "暂无测试报告",
  ];

  return (
    <div className="page dashboard qa-dashboard">
      {state.errors.length ? (
        <div className="failure-callout">
          {state.errors.slice(0, 3).join("；")}
          {state.errors.length > 3 ? `；另有 ${state.errors.length - 3} 项读取失败` : ""}
        </div>
      ) : null}

      <section className="qa-metrics" aria-label="平台统计">
        <MetricCard label="参与项目" value={state.projects.length} tag="Projects" />
        <MetricCard label="正式用例" value={state.cases.length} tag="Cases" />
        <MetricCard label="运行中任务" value={stats.running} tag="Running" />
        <MetricCard label="通过率" value={`${stats.passRate}%`} tag={stats.failed ? `${stats.failed} Failed` : "Rate"} danger={stats.failed > 0} />
      </section>

      <section className="qa-hero-grid" aria-label="快捷入口">
        <HeroCard
          tone="pink"
          title="AI 测试"
          subtitle="选择用例，后台自动调用本地 runner"
          icon="▶"
          onClick={() => onNavigate("execution", "ai-test")}
        />
        <HeroCard
          tone="blue"
          title="AI 生成"
          subtitle="上传需求，智能生成规范用例"
          icon="✦"
          onClick={() => onNavigate("ai-generate", "ai-generate")}
        />
        <HeroCard
          tone="green"
          title="测试报告"
          subtitle="查看历史执行记录与证据链"
          icon="▣"
          onClick={() => onNavigate("reports", "reports")}
        />
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
              执行批跑
            </button>
          </div>
        </Card>

        <Card title="最近动态">
          <div className="qa-activity-list">
            {recentActivities.map((item) => (
              <div className="qa-activity" key={item}>
                <StatusPill tone="green">INFO</StatusPill>
                <span>{item}</span>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Runner 状态">
          <div className="qa-runner-box">
            <StatusPill tone={state.health ? "green" : "amber"}>{state.health ? "Ready" : "Unknown"}</StatusPill>
            <strong>{state.health?.runner || "FastAPI / Runner 未连接"}</strong>
            <span>正式用例 {state.cases.length} 条 · YAML 草稿 {stats.pendingDrafts} 份</span>
          </div>
        </Card>
      </section>

      <section className="qa-lower-grid">
        <Card className="qa-flow-card" title="当前主链路" subtitle="需求上传 -> AI 生成测试用例 -> 用例管理 -> AI测试执行 -> 测试报告">
          <div className="qa-flow-strip">
            {["需求", "AI生成", "用例", "执行", "报告"].map((item, index) => (
              <span key={item} className={index === 1 ? "is-hot" : ""}>
                {item}
              </span>
            ))}
          </div>
          <p className="muted">
            测试点思维导图已保留为隐藏能力，第一版主流程不再强制暴露。
          </p>
        </Card>

        <Card className="qa-report-card" title="报告焦点">
          <div className="qa-report-focus">
            <StatusPill tone={stats.latestReport && isFailed(stats.latestReport.status) ? "red" : "green"}>
              {stats.latestReport?.status || "none"}
            </StatusPill>
            <strong>{stats.latestReport?.case_id || "暂无报告"}</strong>
            <span>
              {stats.latestReport
                ? `${stats.latestReport.case_name || "未命名报告"} · ${stats.latestReport.screenshot_count} 张截图`
                : "执行 case 后这里会展示最新报告证据。"}
            </span>
            <button className="btn btn--soft" onClick={() => onNavigate("reports", "reports")} type="button">
              查看报告
            </button>
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
      <span>
        <strong>{title}</strong>
        <small>{subtitle}</small>
      </span>
      <em>›</em>
    </button>
  );
}
