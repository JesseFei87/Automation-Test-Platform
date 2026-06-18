import type { ApiReportListItem, ApiRun, ApiRunDetail, ApiRunDetailView, ApiScreenshot, ApiStructuredStep } from "./api";

export type ExecutionListItem = {
  runId: string;
  mode: "worker" | "agent";
  modeLabel: string;
  displayName: string;
  caseId: string;
  status: string;
  statusLabel: string;
  startedAtLabel: string;
  durationLabel: string;
  hasReport: boolean;
  hasEvidence: boolean;
  source: ApiRun;
};

export type ReportListItem = {
  runId: string;
  caseId: string;
  caseName: string;
  mode: "worker" | "agent";
  modeLabel: string;
  status: string;
  operator: string;
  startedAtLabel: string;
  finishedAtLabel: string;
  hasReport: boolean;
  hasEvidence: boolean;
  source: ApiReportListItem;
};

export type StepDetailViewModel = {
  key: string;
  index: number;
  title: string;
  status: string;
  summary: string;
  screenshotUrl: string;
  aiAnalysis: string;
  finalUrl: string;
  commandOutput: string[];
  errorMessage: string;
  selectors: string[];
  inputs: Array<{ name?: string; value?: string }>;
  consoleLogs: Array<Record<string, unknown>>;
  networkLogs: Array<Record<string, unknown>>;
  domSnapshotUrl: string;
  events: Array<Record<string, unknown>>;
};

export type RunDetailViewModel = {
  runId: string;
  caseId: string;
  caseName: string;
  mode: "worker" | "agent";
  trigger: "manual" | "self_heal" | string;
  parentRunId: string;
  modeLabel: string;
  status: string;
  statusLabel: string;
  operator: string;
  startedAtLabel: string;
  finishedAtLabel: string;
  durationLabel: string;
  summaryText: string;
  failureText: string;
  finalUrl: string;
  steps: StepDetailViewModel[];
  screenshots: ApiScreenshot[];
  rawReport: string;
  evidence?: ApiRunDetailView["evidence"];
  agentExplore?: ApiRunDetailView["agent_explore"];
  analysis?: ApiRunDetailView["analysis"];
  artifacts: ApiRunDetailView["artifacts"];
  logs: Array<{ id: number; run_id: string; stream: string; line: string; created_at: string }>;
  healingHint: string;
};

function timeLabel(value?: string | null) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function modeLabel(mode: "worker" | "agent") {
  return mode === "agent" ? "智能探索" : "常规执行";
}

function statusLabel(status: string) {
  if (status === "completed" || status === "passed" || status === "success") return "已通过";
  if (status === "failed") return "失败";
  if (status === "running") return "运行中";
  if (status === "queued") return "排队中";
  return status || "未知";
}

function sourceMode(mode: ApiRun["mode"]): "worker" | "agent" {
  return mode === "agent-explore" ? "agent" : "worker";
}

function screenshotFromUrl(url: string, screenshots: ApiScreenshot[]) {
  if (!url) return null;
  return screenshots.find((item) => item.url === url) || null;
}

function mapLegacyAgentSteps(detail: ApiRunDetail): ApiStructuredStep[] {
  const history = detail.agent_explore?.trace?.history || [];
  return history.map((item, index) => {
    const decision = (item.decision || {}) as Record<string, unknown>;
    const execution = (item.execution || {}) as Record<string, unknown>;
    const action = String(decision.action || `步骤 ${index + 1}`);
    const summary = String(decision.reason || execution.result || execution.error || "");
    return {
      step_index: Number(item.step || index + 1),
      step_code: `agent_${index + 1}`,
      title: action,
      status: execution.error ? "failed" : "completed",
      summary,
      error_message: String(execution.error || ""),
      screenshot_url: detail.screenshots[Math.min(index, Math.max(detail.screenshots.length - 1, 0))]?.url || "",
      ai_analysis: String(decision.reason || ""),
      final_url: String(detail.agent_explore?.trace?.finalUrl || detail.agent_explore?.trace?.final_url || ""),
      command_output: detail.logs.slice(-8).map((log) => log.line),
      selectors: [],
      inputs: [],
      console_logs: detail.evidence?.console.latest || [],
      network_logs: detail.evidence?.network.latest || [],
      dom_snapshot_url: detail.evidence?.dom.files.at(-1)?.url || "",
      events: detail.evidence?.events.latest || [],
    };
  });
}

function mapLegacyWorkerSteps(detail: ApiRunDetail): ApiStructuredStep[] {
  const operationLine = detail.report
    .split(/\r?\n/)
    .find((line) => line.trim().toLowerCase().startsWith("- operation steps:"));
  const rawSteps = operationLine
    ? operationLine
        .split(":", 2)[1]
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean)
    : [];
  const source = rawSteps.length ? rawSteps : detail.screenshots.map((shot) => shot.filename);
  return (source.length ? source : ["执行摘要"]).map((title, index) => ({
    step_index: index + 1,
    step_code: `worker_${index + 1}`,
    title,
    status: detail.task.status === "failed" && index === source.length - 1 ? "failed" : detail.task.status === "running" ? "running" : "completed",
    summary: title,
    error_message: detail.task.status === "failed" && index === source.length - 1 ? detail.task.error || "" : "",
    screenshot_url: detail.screenshots[Math.min(index, Math.max(detail.screenshots.length - 1, 0))]?.url || "",
    ai_analysis: detail.analysis?.conclusion || "",
    final_url: "",
    command_output: detail.logs.slice(-8).map((log) => log.line),
    selectors: [],
    inputs: [],
    console_logs: detail.evidence?.console.latest || [],
    network_logs: detail.evidence?.network.latest || [],
    dom_snapshot_url: detail.evidence?.dom.files.at(-1)?.url || "",
    events: detail.evidence?.events.latest || [],
  }));
}

export function legacyRunDetailToView(detail: ApiRunDetail): ApiRunDetailView {
  const mode = detail.task.mode === "agent-explore" ? "agent" : "worker";
  const status = detail.task.status === "passed" ? "completed" : detail.task.status;
  const finalUrl = String(detail.agent_explore?.trace?.finalUrl || detail.agent_explore?.trace?.final_url || "");
  return {
    run_id: detail.task.id,
    case_id: detail.task.case_id,
    case_name: detail.task.summary?.display_name || detail.task.case_id || detail.task.id,
    mode,
    trigger: (detail.task.trigger as "manual" | "self_heal" | string | undefined) || "manual",
    parent_run_id: detail.task.parent_run_id || "",
    status,
    operator: "admin",
    started_at: detail.task.started_at || detail.task.created_at,
    finished_at: detail.task.finished_at,
    duration_seconds: detail.task.summary?.duration_seconds ?? null,
    final_url: finalUrl,
    summary: {
      title: detail.task.summary?.display_name || detail.task.case_id || detail.task.id,
      conclusion: detail.agent_explore?.trace?.summary || detail.analysis?.conclusion || detail.task.summary?.status_label || "",
      failure_reason: detail.agent_explore?.trace?.error || detail.task.error || "",
      ai_analysis: detail.analysis?.conclusion || "",
    },
    steps: mode === "agent" ? mapLegacyAgentSteps(detail) : mapLegacyWorkerSteps(detail),
    artifacts: {
      report_markdown_url: detail.report ? `/api/reports/${detail.task.id}` : "",
      observed_asset_path: "",
      observed_asset_merge_url: `/api/runs/${detail.task.id}/merge-observed-asset`,
      trace_download_url: detail.evidence?.trace.exists ? detail.evidence.trace.url : "",
      candidate_flow_url: detail.agent_explore?.candidate_flow_path ? `/api/runs/${detail.task.id}/agent-explore/candidate-flow` : "",
    },
    raw_report: detail.report,
    logs: detail.logs,
    screenshots: detail.screenshots,
    evidence: detail.evidence,
    agent_explore: detail.agent_explore,
    analysis: detail.analysis,
    healing_hint: "",
  };
}

function mapStep(step: ApiStructuredStep, screenshots: ApiScreenshot[]): StepDetailViewModel {
  const shot = screenshotFromUrl(step.screenshot_url || "", screenshots);
  return {
    key: step.step_code || `step-${step.step_index}`,
    index: step.step_index,
    title: step.title || `步骤 ${step.step_index}`,
    status: step.status || "queued",
    summary: step.summary || step.title || "",
    screenshotUrl: shot?.url || step.screenshot_url || "",
    aiAnalysis: step.ai_analysis || "",
    finalUrl: step.final_url || "",
    commandOutput: step.command_output || [],
    errorMessage: step.error_message || "",
    selectors: step.selectors || [],
    inputs: step.inputs || [],
    consoleLogs: step.console_logs || [],
    networkLogs: step.network_logs || [],
    domSnapshotUrl: step.dom_snapshot_url || "",
    events: step.events || [],
  };
}

export function buildExecutionListItems(runs: ApiRun[]): ExecutionListItem[] {
  return runs.map((run) => {
    const mode = sourceMode(run.mode);
    return {
      runId: run.id,
      mode,
      modeLabel: modeLabel(mode),
      displayName: run.case_id || run.summary?.display_name || run.id,
      caseId: run.case_id || "--",
      status: run.status === "passed" ? "completed" : run.status,
      statusLabel: statusLabel(run.status === "passed" ? "completed" : run.status),
      startedAtLabel: timeLabel(run.started_at || run.created_at),
      durationLabel: run.summary?.duration_label || "--",
      hasReport: Boolean(run.report_path),
      hasEvidence: run.status !== "queued",
      source: run,
    };
  });
}

export function buildReportListItems(reports: ApiReportListItem[]): ReportListItem[] {
  return reports.map((report) => ({
    runId: report.run_id,
    caseId: report.case_id || "--",
    caseName: report.case_name || report.case_id || report.run_id,
    mode: report.mode,
    modeLabel: modeLabel(report.mode),
    status: report.status,
    operator: report.operator || "admin",
    startedAtLabel: timeLabel(report.started_at),
    finishedAtLabel: timeLabel(report.finished_at),
    hasReport: report.has_report,
    hasEvidence: report.has_evidence,
    source: report,
  }));
}

export function buildRunDetailViewModel(detail: ApiRunDetailView | null): RunDetailViewModel {
  const screenshots = detail?.screenshots || [];
  const steps = (detail?.steps || []).map((step) => mapStep(step, screenshots));
  return {
    runId: detail?.run_id || "",
    caseId: detail?.case_id || "--",
    caseName: detail?.case_name || detail?.case_id || "未命名执行",
    mode: detail?.mode || "worker",
    trigger: detail?.trigger || "manual",
    parentRunId: detail?.parent_run_id || "",
    modeLabel: modeLabel(detail?.mode || "worker"),
    status: detail?.status || "queued",
    statusLabel: statusLabel(detail?.status || "queued"),
    operator: detail?.operator || "admin",
    startedAtLabel: timeLabel(detail?.started_at),
    finishedAtLabel: timeLabel(detail?.finished_at),
    durationLabel: detail?.duration_seconds ? `${detail.duration_seconds}s` : "--",
    summaryText: detail?.summary?.conclusion || detail?.summary?.ai_analysis || "暂无执行摘要",
    failureText: detail?.summary?.failure_reason || "",
    finalUrl: detail?.final_url || "",
    steps,
    screenshots,
    rawReport: detail?.raw_report || "",
    evidence: detail?.evidence,
    agentExplore: detail?.agent_explore,
    analysis: detail?.analysis || undefined,
    artifacts: detail?.artifacts || {},
    logs: detail?.logs || [],
    healingHint: detail?.healing_hint || "",
  };
}
