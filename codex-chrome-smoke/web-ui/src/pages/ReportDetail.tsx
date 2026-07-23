import { useEffect, useMemo, useRef, useState } from "react";
import {
  API_ORIGIN,
  api,
  type ApiReportAnalysis,
  type ApiReportAnalysisVersion,
  type ApiRunDetailView,
  type ApiScreenshot,
} from "../data/api";
import { buildReportListItems, buildRunDetailViewModel, legacyRunDetailToView, type StepDetailViewModel } from "../data/runViewModels";
import { Card } from "../components/Card";
import { useConfirm } from "../components/ConfirmDialog";
import { ScreenshotLightbox } from "../components/ScreenshotLightbox";
import { StatusPill } from "../components/StatusPill";
import { useToast } from "../components/Toast";

type ReportViewMode = "list" | "detail";
type ReportModeFilter = "all" | "worker" | "agent";

function ReportMetricIcon({ kind }: { kind: "total" | "passed" | "failed" | "agent" }) {
  const paths = {
    total: <><path d="M5 3h9l5 5v13H5z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></>,
    passed: <path d="m5 12 4 4L19 6" />,
    failed: <><path d="M12 3 2.8 20h18.4z" /><path d="M12 9v4M12 17h.01" /></>,
    agent: <><rect x="4" y="7" width="16" height="12" rx="3" /><path d="M9 3h6M12 3v4M8 12h.01M16 12h.01M9 16h6" /></>,
  };
  return <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24">{paths[kind]}</svg>;
}

function statusTone(status: string): "green" | "red" | "amber" | "blue" {
  if (status === "completed" || status === "passed" || status === "success") return "green";
  if (status === "failed") return "red";
  if (status === "running") return "blue";
  return "amber";
}

function statusText(status: string) {
  if (status === "completed" || status === "passed" || status === "success") return "已通过";
  if (status === "failed") return "失败";
  if (status === "running") return "运行中";
  if (status === "queued") return "排队中";
  return status || "未知";
}

function displayStepTitle(title: string) {
  return title.replace(/^用例步骤\s*\d+\s*[-－—:\s]*/, "").trim() || title;
}

function formatSecondTime(value?: string | null) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function listFilter(mode: string, status: string, filter: string) {
  if (filter === "all") return true;
  if (filter === "agent") return mode === "agent";
  if (filter === "worker") return mode === "worker";
  return status === filter;
}

function readStatusCode(entry: Record<string, unknown>) {
  const candidates = [entry.status, entry.status_code, entry.response_status, entry.code];
  for (const candidate of candidates) {
    if (typeof candidate === "number") return String(candidate);
    if (typeof candidate === "string" && candidate.trim()) return candidate.trim();
  }
  return "未知";
}

function readNetworkLabel(entry: Record<string, unknown>) {
  const method = typeof entry.method === "string" ? entry.method : typeof entry.request_method === "string" ? entry.request_method : "";
  const url =
    typeof entry.url === "string"
      ? entry.url
      : typeof entry.request_url === "string"
        ? entry.request_url
        : typeof entry.path === "string"
          ? entry.path
          : "";
  return [method, url].filter(Boolean).join(" ");
}

function buildNetworkSummary(detail: ReturnType<typeof buildRunDetailViewModel>, selectedStep: StepDetailViewModel | null) {
  const entries =
    selectedStep?.networkLogs.length
      ? selectedStep.networkLogs
      : detail.evidence?.network.latest && detail.evidence.network.latest.length
        ? detail.evidence.network.latest
        : [];
  const statusMap = new Map<string, number>();
  const endpointMap = new Map<string, number>();

  entries.forEach((item) => {
    const code = readStatusCode(item);
    statusMap.set(code, (statusMap.get(code) || 0) + 1);
    const label = readNetworkLabel(item);
    if (label) endpointMap.set(label, (endpointMap.get(label) || 0) + 1);
  });

  return {
    total: entries.length,
    statuses: [...statusMap.entries()].map(([code, count]) => ({ code, count })),
    topEndpoints: [...endpointMap.entries()]
      .sort((left, right) => right[1] - left[1])
      .slice(0, 5)
      .map(([label, count]) => ({ label, count })),
  };
}

function createShotFromStep(step: StepDetailViewModel, caseId: string): ApiScreenshot {
  return {
    case_id: caseId,
    filename: `step-${step.index}.png`,
    path: step.screenshotUrl,
    url: step.screenshotUrl,
  };
}

function reportTitle(caseId: string, caseName: string) {
  const normalizedCaseId = (caseId || "--").trim();
  const escapedCaseId = normalizedCaseId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const cleanedName = (caseName || "")
    .replace(new RegExp(`^${escapedCaseId}\\s*[-:：]?\\s*`, "i"), "")
    .replace(/\s*[-:：]?\s*执行报告\s*$/i, "")
    .trim();
  return `${normalizedCaseId}: ${cleanedName || "执行报告"} - 执行报告`;
}

export function ReportDetail({ initialRunId = "", onRouteChange }: { initialRunId?: string; onRouteChange?: (runId: string) => void }) {
  const confirm = useConfirm();
  const toast = useToast();
  const [viewMode, setViewMode] = useState<ReportViewMode>("list");
  const [reports, setReports] = useState<ReturnType<typeof buildReportListItems>>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [selectedReportIds, setSelectedReportIds] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [modeFilter, setModeFilter] = useState<ReportModeFilter>("all");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pageSize, setPageSize] = useState(20);
  const [currentPage, setCurrentPage] = useState(1);
  const [runDetail, setRunDetail] = useState<ApiRunDetailView | null>(null);
  const [previewShot, setPreviewShot] = useState<ApiScreenshot | null>(null);
  const [analysisVersions, setAnalysisVersions] = useState<ApiReportAnalysisVersion[]>([]);
  const [selectedAnalysisVersionId, setSelectedAnalysisVersionId] = useState<number | null>(null);
  const [loadState, setLoadState] = useState("正在加载测试报告...");
  const [detailState, setDetailState] = useState("正在加载执行详情...");
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [listBusy, setListBusy] = useState(false);
  const [expandedStepKey, setExpandedStepKey] = useState("");
  const analysisSectionRef = useRef<HTMLElement | null>(null);

  const filteredReports = useMemo(() => {
    const keyword = searchKeyword.trim().toLocaleLowerCase();
    return reports.filter((item) => {
      const matchesKeyword = !keyword || [item.runId, item.caseId, item.caseName].some((value) => value.toLocaleLowerCase().includes(keyword));
      const matchesMode = modeFilter === "all" || item.mode === modeFilter;
      return matchesKeyword && matchesMode && listFilter(item.mode, item.status, statusFilter);
    });
  }, [modeFilter, reports, searchKeyword, statusFilter]);
  const reportMetrics = useMemo(() => ({
    total: reports.length,
    passed: reports.filter((item) => ["completed", "passed", "success"].includes(item.status)).length,
    failed: reports.filter((item) => item.status === "failed").length,
    agent: reports.filter((item) => item.mode === "agent").length,
  }), [reports]);
  const totalPages = useMemo(() => Math.max(1, Math.ceil(filteredReports.length / pageSize)), [filteredReports.length, pageSize]);
  const pagedReports = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredReports.slice(start, start + pageSize);
  }, [currentPage, filteredReports, pageSize]);
  const allPagedSelected = pagedReports.length > 0 && pagedReports.every((item) => selectedReportIds.includes(item.runId));
  const detailModel = useMemo(() => buildRunDetailViewModel(runDetail), [runDetail]);
  const selectedAnalysisVersion = analysisVersions.find((version) => version.id === selectedAnalysisVersionId) || analysisVersions[0] || null;
  const currentAnalysis: ApiReportAnalysis | null = selectedAnalysisVersion?.analysis || detailModel.analysis || null;

  async function loadOverview(preferredRunId = "", preferredViewMode: ReportViewMode = "list") {
    setListBusy(true);
    try {
      const items = buildReportListItems(await api.reports());
      setReports(items);
      setSelectedReportIds((current) => current.filter((runId) => items.some((item) => item.runId === runId)));
      const target =
        (preferredRunId ? items.find((item) => item.runId === preferredRunId) : null) ||
        (selectedRunId ? items.find((item) => item.runId === selectedRunId) : null) ||
        items.find((item) => item.status === "failed") ||
        items[0] ||
        null;
      setSelectedRunId(target?.runId || "");
      setViewMode(target && preferredViewMode === "detail" ? "detail" : "list");
      setLoadState(`已加载 ${items.length} 条测试报告。`);
    } catch {
      setLoadState("无法读取测试报告。");
    } finally {
      setListBusy(false);
    }
  }

  async function loadDetailByRunId(runId: string) {
    const [detail, versions] = await Promise.all([
      api.runDetailView(runId).catch(async () => legacyRunDetailToView(await api.runDetail(runId))),
      api.reportAnalysisVersions(runId).catch(() => []),
    ]);
    setRunDetail(detail);
    setAnalysisVersions(versions);
    setSelectedAnalysisVersionId(versions[0]?.id ?? null);
    setDetailState("已加载执行详情。");
  }

  useEffect(() => {
    void loadOverview(initialRunId, initialRunId ? "detail" : "list");
  }, [initialRunId]);

  useEffect(() => {
    if (viewMode !== "detail" || !selectedRunId) return;
    let cancelled = false;
    async function loadDetail() {
      try {
        setDetailState("正在加载执行详情...");
        await loadDetailByRunId(selectedRunId);
      } catch {
        if (!cancelled) {
          setRunDetail(null);
          setAnalysisVersions([]);
          setSelectedAnalysisVersionId(null);
          setDetailState("无法读取执行详情。");
        }
      }
    }
    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedRunId, viewMode]);

  useEffect(() => {
    if (!detailModel.steps.length) {
      setExpandedStepKey("");
      return;
    }
    const failedStep = detailModel.steps.find((step) => step.status === "failed");
    const fallbackStep = failedStep || detailModel.steps[detailModel.steps.length - 1];
    setExpandedStepKey((current) => (detailModel.steps.some((step) => step.key === current) ? current : fallbackStep.key));
  }, [detailModel.steps]);

  useEffect(() => {
    setCurrentPage(1);
  }, [modeFilter, pageSize, searchKeyword, statusFilter]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  function openDetail(runId: string) {
    setSelectedRunId(runId);
    setViewMode("detail");
    onRouteChange?.(runId);
  }

  function backToList() {
    setViewMode("list");
    onRouteChange?.("");
  }

  async function exportMarkdown() {
    if (!selectedRunId) return;
    setExportBusy(true);
    try {
      const markdown = detailModel.rawReport || (await api.reportDetail(selectedRunId)).markdown || "";
      const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
      const filename = `${detailModel.caseId !== "--" ? detailModel.caseId : detailModel.runId || "report"}-report.md`;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } finally {
      setExportBusy(false);
    }
  }

  async function handleAnalysisAction() {
    if (!selectedRunId) return;
    setAnalysisBusy(true);
    try {
      const analysis = await api.analyzeReport(selectedRunId, { force: true });
      setRunDetail((current) => (current ? { ...current, analysis } : current));
      const versions = await api.reportAnalysisVersions(selectedRunId).catch(() => []);
      setAnalysisVersions(versions);
      setSelectedAnalysisVersionId(versions[0]?.id ?? null);
      analysisSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch {
      setDetailState("触发分析失败。");
    } finally {
      setAnalysisBusy(false);
    }
  }

  function toggleReportSelection(runId: string) {
    setSelectedReportIds((current) => (current.includes(runId) ? current.filter((item) => item !== runId) : [...current, runId]));
  }

  function togglePageSelection() {
    if (allPagedSelected) {
      const pageIds = new Set(pagedReports.map((item) => item.runId));
      setSelectedReportIds((current) => current.filter((item) => !pageIds.has(item)));
      return;
    }
    const merged = new Set(selectedReportIds);
    pagedReports.forEach((item) => merged.add(item.runId));
    setSelectedReportIds([...merged]);
  }

  function applyQuickFilter(filter: string) {
    if (filter === "all") {
      setStatusFilter("all");
      setModeFilter("all");
      return;
    }
    if (filter === "agent" || filter === "worker") {
      setStatusFilter("all");
      setModeFilter(filter);
      return;
    }
    setStatusFilter(filter);
  }

  async function handleDeleteReport(runId: string) {
    const confirmed = await confirm({
      title: `确认删除测试报告“${runId}”？`,
      description: "删除后将无法在报告中心继续查看该次执行的步骤、日志、截图和其他证据。",
      danger: true,
      confirmText: "确认删除",
    });
    if (!confirmed) return;
    setDeleteBusy(true);
    try {
      await api.deleteReport(runId);
      if (selectedRunId === runId) {
        setRunDetail(null);
        setAnalysisVersions([]);
        setSelectedAnalysisVersionId(null);
        onRouteChange?.("");
      }
      await loadOverview("", "list");
      toast.show({ kind: "success", message: "报告删除成功" });
    } finally {
      setDeleteBusy(false);
    }
  }

  async function handleBatchDeleteReports() {
    if (!selectedReportIds.length) return;
    const confirmed = await confirm({
      title: `确认删除选中的 ${selectedReportIds.length} 份测试报告？`,
      description: "删除后将无法在报告中心继续查看这些执行记录对应的步骤、日志、截图和其他证据。",
      danger: true,
      confirmText: "确认删除",
    });
    if (!confirmed) return;
    setDeleteBusy(true);
    try {
      await api.batchDeleteReports(selectedReportIds);
      setSelectedReportIds([]);
      setRunDetail(null);
      setAnalysisVersions([]);
      setSelectedAnalysisVersionId(null);
      await loadOverview("", "list");
      toast.show({ kind: "success", message: "报告删除成功" });
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <div className="page report-center-page report-center-redesign">
      {viewMode === "list" ? (
        <div className="report-redesign-list">
          <section className="report-metric-grid" aria-label="报告概览">
            {[
              { key: "total", label: "报告总数", value: reportMetrics.total, note: "全部执行记录" },
              { key: "passed", label: "执行通过", value: reportMetrics.passed, note: reportMetrics.total ? `通过率 ${Math.round((reportMetrics.passed / reportMetrics.total) * 100)}%` : "暂无报告" },
              { key: "failed", label: "执行失败", value: reportMetrics.failed, note: reportMetrics.failed ? "建议优先复盘" : "当前无失败" },
              { key: "agent", label: "智能探索", value: reportMetrics.agent, note: "Browser Harness / Agent" },
            ].map((metric) => (
              <article className={`report-metric-card report-metric-card--${metric.key}`} key={metric.key}>
                <div>
                  <span>{metric.label}</span>
                  <strong>{metric.value}</strong>
                  <small>{metric.note}</small>
                </div>
                <span className="report-metric-card__icon"><ReportMetricIcon kind={metric.key as "total" | "passed" | "failed" | "agent"} /></span>
              </article>
            ))}
          </section>

          <section className="card report-search-card">
            <form className="report-search-grid" onSubmit={(event) => { event.preventDefault(); setCurrentPage(1); }}>
              <label className="report-search-field">
                <span>搜索报告</span>
                <div>
                  <svg aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
                  <input aria-label="搜索报告编号、测试用例 ID 或用例名称" onChange={(event) => setSearchKeyword(event.target.value)} placeholder="输入报告编号、测试用例 ID 或用例名称" type="search" value={searchKeyword} />
                </div>
              </label>
              <label className="report-mode-filter">
                <span>执行模式</span>
                <select onChange={(event) => setModeFilter(event.target.value as ReportModeFilter)} value={modeFilter}>
                  <option value="all">全部模式</option>
                  <option value="worker">常规执行</option>
                  <option value="agent">智能探索</option>
                </select>
              </label>
              <button className="btn btn--primary report-search-button" type="submit">搜索</button>
            </form>
            <div className="report-filter-strip">
              <div className="report-filters">
                {[
                  ["all", `全部 ${reports.length}`],
                  ["completed", `已通过 ${reportMetrics.passed}`],
                  ["failed", `失败 ${reportMetrics.failed}`],
                  ["agent", `智能探索 ${reportMetrics.agent}`],
                  ["worker", `常规执行 ${reports.length - reportMetrics.agent}`],
                ].map(([key, label]) => (
                  <button
                    className={statusFilter === key || ((key === "agent" || key === "worker") && statusFilter === "all" && modeFilter === key) ? "is-active" : ""}
                    key={key}
                    onClick={() => applyQuickFilter(key)}
                    type="button"
                  >
                    {label}
                  </button>
                ))}
              </div>
              <span aria-live="polite" title={loadState}>当前展示 {filteredReports.length} 条报告</span>
            </div>
          </section>

          <section className="card report-list-view-card">
            <div className="report-batch-bar">
              <label className="report-select-all">
                <input checked={allPagedSelected} onChange={togglePageSelection} type="checkbox" />
                <span>全选当前结果</span>
              </label>
              <strong>已选 {selectedReportIds.length} 条</strong>
              <div className="report-list-actions">
                <label className="report-page-size">
                  <span>每页</span>
                  <select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>
                    {[20, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
                  </select>
                </label>
                <button className="btn btn--outline btn--danger-soft" disabled={!selectedReportIds.length || deleteBusy} onClick={handleBatchDeleteReports} type="button">
                  {deleteBusy ? "删除中..." : "批量删除"}
                </button>
                <button className="btn btn--outline" disabled={listBusy} onClick={() => void loadOverview("", "list")} type="button">
                  {listBusy ? "刷新中..." : "刷新报告"}
                </button>
              </div>
            </div>

            <div className="report-table-shell report-table-shell--full">
              <table className="report-table">
                <thead><tr><th className="report-table__check">选择</th><th>报告编号</th><th>测试用例</th><th>执行模式</th><th>状态</th><th>执行人</th><th>开始时间</th><th>结果时间</th><th>操作</th></tr></thead>
                <tbody>
                  {pagedReports.map((item) => (
                    <tr className={item.runId === selectedRunId ? "is-selected-row" : ""} key={item.runId}>
                      <td className="report-table__check"><input aria-label={`选择报告 ${item.runId}`} checked={selectedReportIds.includes(item.runId)} onChange={() => toggleReportSelection(item.runId)} type="checkbox" /></td>
                      <td><button className="report-id-link" onClick={() => openDetail(item.runId)} type="button">{item.runId}</button></td>
                      <td><div className="report-table__name"><strong>{item.caseName}</strong><span>{item.caseId}</span></div></td>
                      <td><span className={`report-mode-badge report-mode-badge--${item.mode}`}>{item.modeLabel}</span></td>
                      <td><StatusPill tone={statusTone(item.status)}>{statusText(item.status)}</StatusPill></td>
                      <td>{item.operator}</td><td>{item.startedAtLabel}</td><td>{item.finishedAtLabel}</td>
                      <td className="report-table__actions">
                        <div className="report-table__action-buttons">
                          <button className="report-row-action report-row-action--detail" onClick={() => openDetail(item.runId)} type="button">查看详情</button>
                          <button className="report-row-action report-row-action--delete" disabled={deleteBusy} onClick={() => handleDeleteReport(item.runId)} type="button">删除</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!pagedReports.length ? <tr><td colSpan={9}><p className="empty-state report-empty">当前搜索和筛选条件下暂无测试报告。</p></td></tr> : null}
                </tbody>
              </table>
            </div>
            <div className="report-pagination">
              <span>第 {currentPage} / {totalPages} 页，共 {filteredReports.length} 条</span>
              <div className="report-pagination__actions">
                <button className="btn btn--outline" disabled={currentPage <= 1} onClick={() => setCurrentPage((page) => Math.max(1, page - 1))} type="button">上一页</button>
                <button className="btn btn--outline" disabled={currentPage >= totalPages} onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))} type="button">下一页</button>
              </div>
            </div>
          </section>
        </div>
      ) : (
        <div className="report-detail-view">
          <div className="report-toolbar">
            <button className="btn btn--outline" onClick={backToList} type="button">← 返回报告列表</button>
            <div>
              <button className="btn btn--outline" disabled={exportBusy || !selectedRunId} onClick={exportMarkdown} type="button">{exportBusy ? "导出中..." : "导出 MD"}</button>
              <button className="btn btn--outline btn--danger-soft" disabled={deleteBusy || !selectedRunId} onClick={() => void handleDeleteReport(selectedRunId)} type="button">删除报告</button>
            </div>
          </div>

          <section className="card report-summary-card report-redesign-summary">
            <div className="report-redesign-summary__header">
              <div><span className="report-redesign-eyebrow">REPORT OVERVIEW</span><h2>{reportTitle(detailModel.caseId, detailModel.caseName)}</h2><p>{detailState}</p></div>
              <div className="report-summary-tags">
                <StatusPill tone={statusTone(detailModel.status)}>{detailModel.statusLabel}</StatusPill>
                <StatusPill tone="blue">{detailModel.modeLabel}</StatusPill>
                <StatusPill tone="amber">{detailModel.durationLabel}</StatusPill>
                <StatusPill tone="green">{detailModel.screenshots.length} 张截图</StatusPill>
              </div>
            </div>
            <div className="report-summary-head__status">
              <div className="report-summary-head__row"><span>报告编号</span><strong>{detailModel.runId}</strong></div>
              <div className="report-summary-head__row"><span>执行人</span><strong>{detailModel.operator}</strong></div>
              <div className="report-summary-head__row"><span>开始时间</span><strong>{detailModel.startedAtLabel}</strong></div>
              <div className="report-summary-head__row"><span>结束时间</span><strong>{detailModel.finishedAtLabel}</strong></div>
            </div>
            <div className="report-summary-panels">
              <section className="report-summary-panel"><strong>执行结论</strong><p>{detailModel.summaryText || "暂无执行结论"}</p></section>
              <section className="report-summary-panel"><strong>故障描述</strong><p>{detailModel.failureText || "本次执行未记录故障描述"}</p></section>
              <section className="report-summary-panel"><strong>AI 分析结论</strong><p>{currentAnalysis?.conclusion || detailModel.summaryText || "暂无 AI 分析结论"}</p></section>
              <section className="report-summary-panel"><strong>最终地址</strong><p>{detailModel.finalUrl || "--"}</p></section>
            </div>
          </section>

          <div className="report-redesign-detail-grid">
            <Card className="report-steps-card" title="执行步骤与证据" subtitle="按步骤查看截图、AI 说明、错误信息、运行日志与网络请求">
            <div className="report-step-accordion">
              {detailModel.steps.map((step) => {
                const isOpen = step.key === expandedStepKey;
                const stepNetworkSummary = buildNetworkSummary(detailModel, step);
                return (
                  <section className={`report-step-item report-step-item--${step.status} ${isOpen ? "is-open" : ""}`} key={step.key}>
                    <button aria-expanded={isOpen} className="report-step-item__trigger" onClick={() => setExpandedStepKey((current) => (current === step.key ? "" : step.key))} type="button">
                      <div className="report-step-item__title">
                        <StatusPill tone={statusTone(step.status)}>{statusText(step.status)}</StatusPill>
                        <strong>
                          步骤 {step.index}: {displayStepTitle(step.title)}
                        </strong>
                      </div>
                      <span>{isOpen ? "收起" : "展开"}</span>
                    </button>

                    {isOpen ? (
                      <div className="report-step-item__content">
                        <div className="report-step-shot">
                          <strong>执行截图</strong>
                          {step.screenshotUrl ? (
                            <button className="step-shot" onClick={() => setPreviewShot(createShotFromStep(step, detailModel.caseId))} type="button">
                              <img alt={`step-${step.index}`} src={`${API_ORIGIN}${step.screenshotUrl}`} />
                            </button>
                          ) : (
                            <p className="empty-state">当前步骤暂无截图。</p>
                          )}
                        </div>

                        <div className="report-step-side">
                          <section className="report-step-side__panel">
                            <strong>AI 执行详情</strong>
                            <p>{step.aiAnalysis || step.summary || "暂无 AI 执行详情"}</p>
                          </section>
                          <section className="report-step-side__panel">
                            <strong>错误信息</strong>
                            <p>{step.errorMessage || "当前步骤未记录错误信息"}</p>
                          </section>
                          <section className="report-step-side__panel">
                            <strong>执行日志</strong>
                            <pre>{step.commandOutput.join("\n") || "暂无执行日志信息"}</pre>
                          </section>
                          <section className="report-step-side__panel">
                            <strong>网络请求</strong>
                            {stepNetworkSummary.topEndpoints.length ? (
                              <div className="severity-endpoints">
                                {stepNetworkSummary.topEndpoints.map((item) => (
                                  <div className="severity-endpoint-row" key={`${step.key}-${item.label}`}>
                                    <span>{item.label}</span>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p>当前步骤暂无网络请求证据。</p>
                            )}
                          </section>
                        </div>
                      </div>
                    ) : null}
                  </section>
                );
              })}

              {!detailModel.steps.length ? <p className="empty-state">当前运行暂无步骤详情。</p> : null}
            </div>
            </Card>

            <Card className="report-analysis-card" title="AI 复盘分析" subtitle="当前分析结果与历史版本">
            <section className="report-analysis-anchor" ref={analysisSectionRef}>
              <div className="report-analysis-toolbar">
                <button className="btn btn--primary" disabled={analysisBusy || !selectedRunId} onClick={handleAnalysisAction} type="button">
                  {analysisBusy ? "AI 分析中..." : analysisVersions.length ? "重新分析" : "开始 AI 分析"}
                </button>
                <span className="report-analysis-toolbar__hint">基于当前测试报告内容自动生成分析结论、风险提示和复测建议</span>
              </div>
              <div className="report-summary-panels">
                <section className="report-summary-panel">
                  <strong>{selectedAnalysisVersion ? `分析版本 · ${formatSecondTime(selectedAnalysisVersion.created_at)}` : "当前分析"}</strong>
                  <p>{currentAnalysis?.conclusion || "暂无分析结果"}</p>
                </section>
                <section className="report-summary-panel">
                  <strong>风险提示</strong>
                  <p>{currentAnalysis?.risks?.[0] || "暂无风险提示"}</p>
                </section>
                <section className="report-summary-panel">
                  <strong>复测建议</strong>
                  <p>{currentAnalysis?.retest_suggestions?.[0] || "暂无复测建议"}</p>
                </section>
              </div>
              <div className="analysis-history">
                <strong>历史版本</strong>
                {analysisVersions.length ? (
                  analysisVersions.slice(0, 5).map((version) => (
                    <button
                      aria-pressed={version.id === selectedAnalysisVersion?.id}
                      className={`analysis-history__item ${version.id === selectedAnalysisVersion?.id ? "is-active" : ""}`}
                      key={version.id}
                      onClick={() => setSelectedAnalysisVersionId(version.id)}
                      type="button"
                    >
                      <span>{formatSecondTime(version.created_at)}</span>
                      <small>{version.provider} / {version.model}</small>
                    </button>
                  ))
                ) : (
                  <p className="empty-state">暂无分析历史。</p>
                )}
              </div>
            </section>
            </Card>
          </div>
        </div>
      )}

      <ScreenshotLightbox screenshot={previewShot} onClose={() => setPreviewShot(null)} />
    </div>
  );
}
