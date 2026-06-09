import { useEffect, useMemo, useState } from "react";
import type { PageId } from "../types";
import { api, type AISettings, type ApiCase, type ApiReport, type ApiRun, type CaseDraft, type Requirement, type TestPoint } from "../data/api";
import { Card } from "../components/Card";
import { ConsolePanel } from "../components/ConsolePanel";
import { FlowSteps } from "../components/FlowSteps";
import { StatusPill } from "../components/StatusPill";

type Health = {
  status: string;
  runner: string;
  api_version?: string;
};

type DashboardState = {
  health: Health | null;
  aiSettings: AISettings | null;
  requirements: Requirement[];
  points: TestPoint[];
  drafts: CaseDraft[];
  cases: ApiCase[];
  runs: ApiRun[];
  reports: ApiReport[];
  logs: string[];
  errors: string[];
};

const EMPTY_STATE: DashboardState = {
  health: null,
  aiSettings: null,
  requirements: [],
  points: [],
  drafts: [],
  cases: [],
  runs: [],
  reports: [],
  logs: [],
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

function pointPriorityCount(points: TestPoint[], priority: string) {
  return points.filter((point) => point.priority === priority).length;
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

function latestFailedOrLatestReport(reports: ApiReport[]) {
  return reports.find((report) => isFailed(report.status)) || reports[0] || null;
}

function caseTitle(item: ApiCase | CaseDraft) {
  if ("promoted_case_id" in item && item.promoted_case_id) return item.promoted_case_id;
  return "id" in item && typeof item.id === "string" ? item.id : `draft #${item.id}`;
}

export function Dashboard({ onNavigate }: { onNavigate: (page: PageId) => void }) {
  const [state, setState] = useState<DashboardState>(EMPTY_STATE);
  const [loading, setLoading] = useState(true);

  async function loadDashboard() {
    setLoading(true);
    const errors: string[] = [];
    const [health, aiSettings, requirements, points, drafts, cases, runs, reports] = await Promise.allSettled([
      api.health(),
      api.aiSettings(),
      api.requirements(),
      api.testPoints("confirmed"),
      api.caseDrafts(),
      api.cases(),
      api.runs(),
      api.reports(),
    ]);

    const nextRuns = readSettled(runs, "执行任务", errors) || [];
    let logs: string[] = [];
    const activeRun = nextRuns.find(isRunning) || nextRuns[0];
    if (activeRun) {
      try {
        const detail = await api.runDetail(activeRun.id);
        logs = detail.logs.slice(-6).map((line) => `[${formatTime(line.created_at)}] ${line.line}`);
      } catch (error) {
        errors.push(`运行日志读取失败：${error instanceof Error ? error.message : "unknown error"}`);
      }
    }

    setState({
      health: readSettled(health, "平台健康状态", errors),
      aiSettings: readSettled(aiSettings, "AI 设置", errors),
      requirements: readSettled(requirements, "需求", errors) || [],
      points: readSettled(points, "测试点", errors) || [],
      drafts: readSettled(drafts, "YAML 草稿", errors) || [],
      cases: readSettled(cases, "正式 case", errors) || [],
      runs: nextRuns,
      reports: readSettled(reports, "报告", errors) || [],
      logs,
      errors,
    });
    setLoading(false);
  }

  useEffect(() => {
    loadDashboard();
  }, []);

  const stats = useMemo(() => {
    const passed = state.runs.filter((run) => isPassed(run.status)).length;
    const running = state.runs.filter(isRunning).length;
    const failed = state.runs.filter((run) => isFailed(run.status)).length;
    const latestRun = state.runs[0] || null;
    const latestReport = latestFailedOrLatestReport(state.reports);
    const latestRequirement = state.requirements[0] || null;
    const pendingDrafts = state.drafts.filter((draft) => draft.status !== "promoted");
    const promotedDrafts = state.drafts.filter((draft) => draft.status === "promoted");
    return { passed, running, failed, latestRun, latestReport, latestRequirement, pendingDrafts, promotedDrafts };
  }, [state]);

  const consoleLines = state.logs.length
    ? state.logs
    : state.runs.slice(0, 5).map((run) => `[${formatTime(run.created_at)}] ${run.mode} ${run.case_id || "batch"} ${run.status}`);

  return (
    <div className="page dashboard">
      <FlowSteps activeIndex={5} compact />

      {state.errors.length ? (
        <div className="failure-callout">
          {state.errors.slice(0, 3).join("；")}
          {state.errors.length > 3 ? `；另有 ${state.errors.length - 3} 项读取失败` : ""}
        </div>
      ) : null}

      <div className="dashboard-grid">
        <Card title="需求工作台" subtitle="真实需求文档、AI 分析状态和测试点覆盖情况">
          <div className="note-box">
            {stats.latestRequirement ? (
              <>
                <p><strong>{stats.latestRequirement.title}</strong></p>
                <p>状态：{stats.latestRequirement.status}</p>
                <p>测试点：{stats.latestRequirement.test_point_count ?? 0} 个</p>
                <p>草稿：{stats.latestRequirement.draft_count ?? 0} 份</p>
              </>
            ) : (
              <p>{loading ? "正在读取需求..." : "暂无需求，先创建并分析一份需求文档。"}</p>
            )}
          </div>
          <div className="button-row">
            <button className="btn btn--primary" onClick={() => onNavigate("requirements")} type="button">
              创建并分析
            </button>
            <button className="btn btn--soft" onClick={() => onNavigate("requirements")} type="button">查看需求</button>
            <StatusPill tone="green">{state.requirements.length} 需求</StatusPill>
          </div>
        </Card>

        <Card title="AI 测试点" subtitle="已确认测试点、优先级分布和最近覆盖">
          <div className="point-list">
            {state.points.slice(0, 4).map((point) => (
              <div className="point-row" key={point.id}>
                <span>{point.priority} {point.name}</span>
                <StatusPill tone={point.priority === "P0" ? "red" : point.priority === "P1" ? "amber" : "blue"}>{point.priority}</StatusPill>
              </div>
            ))}
            {!state.points.length ? <p className="empty-state">{loading ? "正在读取测试点..." : "暂无已确认测试点。"}</p> : null}
          </div>
          <div className="button-row">
            <button className="btn btn--cyan" onClick={() => onNavigate("points")} type="button">打开思维导图</button>
            <button className="btn btn--soft" onClick={() => onNavigate("cases")} type="button">生成 YAML</button>
            <StatusPill tone="red">P0 {pointPriorityCount(state.points, "P0")}</StatusPill>
            <StatusPill tone="amber">P1 {pointPriorityCount(state.points, "P1")}</StatusPill>
          </div>
        </Card>

        <Card title="执行中心" subtitle="后台队列调用本地 Python runner 的真实任务状态">
          <div className="stats">
            <div><strong>{stats.passed}</strong><span>Passed</span></div>
            <div><strong>{stats.running}</strong><span>Running</span></div>
            <div><strong className="danger">{stats.failed}</strong><span>Failed</span></div>
          </div>
          <div className="case-strip">{stats.latestRun?.case_id || stats.latestRun?.summary?.display_name || "暂无执行任务"}</div>
          <div className="button-row">
            <button className="btn btn--primary" onClick={() => onNavigate("execution")} type="button">执行 Case</button>
            <button className="btn btn--green" onClick={() => onNavigate("execution")} type="button">Batch 001-012</button>
            <StatusPill tone={stats.running ? "amber" : "green"}>{stats.running ? `队列 ${stats.running} 个任务` : "Runner Ready"}</StatusPill>
          </div>
        </Card>

        <Card className="dashboard-console-card" title="运行控制台">
          <ConsolePanel lines={consoleLines.length ? consoleLines : ["暂无运行日志，启动一次 case 后这里会显示最近输出。"]} running={stats.running > 0} />
          <p className="console-caption">
            {state.health ? `${state.health.runner} · API ${state.health.api_version || state.health.status}` : "后端未连接或健康检查失败"}
          </p>
        </Card>

        <Card title="报告与证据中心" subtitle="Markdown 报告、截图证据和失败优先提示">
          <div className="report-preview">
            <div className="report-preview__bar" />
            <div className="report-preview__tiles">
              <span />
              <span />
            </div>
          </div>
          <p className="muted center-text">
            {stats.latestReport ? `${stats.latestReport.case_id} / ${stats.latestReport.screenshot_count} 张截图` : "暂无报告"}
          </p>
          <div className={`analysis-box ${stats.latestReport && isFailed(stats.latestReport.status) ? "analysis-box--danger" : ""}`}>
            <strong>{stats.latestReport ? `${stats.latestReport.status.toUpperCase()} · ${stats.latestReport.case_name}` : "等待执行报告"}</strong>
            <p>
              {stats.latestReport
                ? `最新关注报告：${stats.latestReport.run_id}，更新时间 ${formatTime(new Date(stats.latestReport.updated_at * 1000).toISOString())}。`
                : "执行 case 后，这里会显示最新报告与截图证据。"}
            </p>
          </div>
          <div className="button-row">
            <button className="btn btn--soft" onClick={() => onNavigate("reports")} type="button">查看报告中心</button>
          </div>
        </Card>
      </div>

      <div className="bottom-tabs">
        <strong>用例工具箱</strong>
        {state.cases.slice(0, 4).map((item, index) => (
          <button className={index === 0 ? "is-selected" : ""} key={item.id} onClick={() => onNavigate("cases")} type="button">
            {item.id}
          </button>
        ))}
        {!state.cases.length && stats.promotedDrafts.slice(0, 4).map((item, index) => (
          <button className={index === 0 ? "is-selected" : ""} key={item.id} onClick={() => onNavigate("cases")} type="button">
            {caseTitle(item)}
          </button>
        ))}
        <span>
          {stats.pendingDrafts.length
            ? `${stats.pendingDrafts.length} 份 YAML 草稿待转正式 case`
            : `正式 case ${state.cases.length} 条 · AI ${state.aiSettings?.model || "未配置"}`}
        </span>
      </div>
    </div>
  );
}
