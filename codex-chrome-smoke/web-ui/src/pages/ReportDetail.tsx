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
import { FlowSteps } from "../components/FlowSteps";
import { ScreenshotLightbox } from "../components/ScreenshotLightbox";
import { StatusPill } from "../components/StatusPill";

type ReportViewMode = "list" | "detail";

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
  return title.replace(/^用例步骤\s*\d+\s*[-－—]\s*/, "").trim() || title;
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

export function ReportDetail({ initialRunId = "" }: { initialRunId?: string }) {
  const [viewMode, setViewMode] = useState<ReportViewMode>("list");
  const [reports, setReports] = useState<ReturnType<typeof buildReportListItems>>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [runDetail, setRunDetail] = useState<ApiRunDetailView | null>(null);
  const [previewShot, setPreviewShot] = useState<ApiScreenshot | null>(null);
  const [analysisVersions, setAnalysisVersions] = useState<ApiReportAnalysisVersion[]>([]);
  const [loadState, setLoadState] = useState("正在加载测试报告...");
  const [detailState, setDetailState] = useState("正在加载执行详情...");
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [expandedStepKey, setExpandedStepKey] = useState("");
  const analysisSectionRef = useRef<HTMLElement | null>(null);

  const filteredReports = useMemo(() => reports.filter((item) => listFilter(item.mode, item.status, statusFilter)), [reports, statusFilter]);
  const detailModel = useMemo(() => buildRunDetailViewModel(runDetail), [runDetail]);
  const selectedReport = useMemo(() => reports.find((item) => item.runId === selectedRunId) || null, [reports, selectedRunId]);
  const currentAnalysis: ApiReportAnalysis | null = detailModel.analysis || analysisVersions[0]?.analysis || null;

  async function loadDetailByRunId(runId: string) {
    const [detail, versions] = await Promise.all([
      api.runDetailView(runId).catch(async () => legacyRunDetailToView(await api.runDetail(runId))),
      api.reportAnalysisVersions(runId).catch(() => []),
    ]);
    setRunDetail(detail);
    setAnalysisVersions(versions);
    setDetailState("已加载执行详情。");
  }

  useEffect(() => {
    async function loadOverview() {
      try {
        const items = buildReportListItems(await api.reports());
        setReports(items);
        const target =
          (initialRunId ? items.find((item) => item.runId === initialRunId) : null) ||
          items.find((item) => item.status === "failed") ||
          items[0] ||
          null;
        setSelectedRunId(target?.runId || "");
        setViewMode(initialRunId && target ? "detail" : "list");
        setLoadState(`已加载 ${items.length} 条测试报告。`);
      } catch {
        setLoadState("无法读取测试报告。");
      }
    }
    void loadOverview();
  }, [initialRunId]);

  useEffect(() => {
    if (!selectedRunId) return;
    let cancelled = false;
    async function loadDetail() {
      try {
        setDetailState("正在加载执行详情...");
        await loadDetailByRunId(selectedRunId);
      } catch {
        if (!cancelled) {
          setRunDetail(null);
          setAnalysisVersions([]);
          setDetailState("无法读取执行详情。");
        }
      }
    }
    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  useEffect(() => {
    if (!detailModel.steps.length) {
      setExpandedStepKey("");
      return;
    }
    const failedStep = detailModel.steps.find((step) => step.status === "failed");
    const fallbackStep = failedStep || detailModel.steps[detailModel.steps.length - 1];
    setExpandedStepKey((current) => (detailModel.steps.some((step) => step.key === current) ? current : fallbackStep.key));
  }, [detailModel.steps]);

  function openDetail(runId: string) {
    setSelectedRunId(runId);
    setViewMode("detail");
  }

  function backToList() {
    setViewMode("list");
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
    if (analysisVersions.length) {
      analysisSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    setAnalysisBusy(true);
    try {
      const analysis = await api.analyzeReport(selectedRunId);
      setRunDetail((current) => (current ? { ...current, analysis } : current));
      setAnalysisVersions(await api.reportAnalysisVersions(selectedRunId).catch(() => []));
      analysisSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch {
      setDetailState("触发分析失败。");
    } finally {
      setAnalysisBusy(false);
    }
  }

  return (
    <div className="page report-center-page">
      <FlowSteps activeIndex={5} />

      {viewMode === "list" ? (
        <Card className="report-list-view-card" title="自动化测试报告" subtitle={loadState}>
          <div className="report-filters">
            {[
              ["all", "全部"],
              ["failed", "失败"],
              ["completed", "通过"],
              ["agent", "智能探索"],
              ["worker", "常规执行"],
            ].map(([key, label]) => (
              <button className={statusFilter === key ? "is-active" : ""} key={key} onClick={() => setStatusFilter(key)} type="button">
                {label}
              </button>
            ))}
          </div>

          <div className="report-table-shell report-table-shell--full">
            <table className="report-table">
              <thead>
                <tr>
                  <th>编号</th>
                  <th>测试用例</th>
                  <th>模式</th>
                  <th>状态</th>
                  <th>执行人</th>
                  <th>开始时间</th>
                  <th>结果时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredReports.map((item) => (
                  <tr className={item.runId === selectedRunId ? "is-selected-row" : ""} key={item.runId}>
                    <td>{item.runId}</td>
                    <td>
                      <div className="report-table__name">
                        <strong>{item.caseName}</strong>
                        <span>{item.caseId}</span>
                      </div>
                    </td>
                    <td>{item.modeLabel}</td>
                    <td>
                      <StatusPill tone={statusTone(item.status)}>{statusText(item.status)}</StatusPill>
                    </td>
                    <td>{item.operator}</td>
                    <td>{item.startedAtLabel}</td>
                    <td>{item.finishedAtLabel}</td>
                    <td>
                      <button className="link-button" onClick={() => openDetail(item.runId)} type="button">
                        详情
                      </button>
                    </td>
                  </tr>
                ))}
                {!filteredReports.length ? (
                  <tr>
                    <td colSpan={8}>
                      <p className="empty-state report-empty">当前筛选条件下暂无测试报告。</p>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <div className="report-detail-view">
          <div className="report-toolbar">
            <button className="btn btn--outline" onClick={backToList} type="button">
              &lt; 返回列表
            </button>
            <button className="btn btn--outline" disabled={exportBusy || !selectedRunId} onClick={exportMarkdown} type="button">
              {exportBusy ? "导出中..." : "导出 MD"}
            </button>
          </div>

          <Card className="report-summary-card" title={reportTitle(detailModel.caseId, detailModel.caseName)} subtitle={detailState}>
            <div className="report-summary-head">
              <div className="report-summary-head__status">
                <div className="report-summary-head__row">
                  <span>状态:</span>
                  <strong>{detailModel.statusLabel}</strong>
                </div>
                <div className="report-summary-head__row">
                  <span>执行人:</span>
                  <strong>{detailModel.operator}</strong>
                </div>
                <div className="report-summary-head__row">
                  <span>开始时间:</span>
                  <strong>{detailModel.startedAtLabel}</strong>
                </div>
                <div className="report-summary-head__row">
                  <span>结束时间:</span>
                  <strong>{detailModel.finishedAtLabel}</strong>
                </div>
              </div>
              <div className="report-summary-tags">
                <StatusPill tone={statusTone(detailModel.status)}>{detailModel.statusLabel}</StatusPill>
                <StatusPill tone="blue">{detailModel.modeLabel}</StatusPill>
                <StatusPill tone="amber">{detailModel.durationLabel}</StatusPill>
                <StatusPill tone="green">{detailModel.screenshots.length} 张截图</StatusPill>
              </div>
            </div>

            <div className="report-summary-panels">
              <section className="report-summary-panel">
                <strong>执行结论</strong>
                <p>{detailModel.summaryText || "暂无执行结论"}</p>
              </section>
              <section className="report-summary-panel">
                <strong>故障描述</strong>
                <p>{detailModel.failureText || "本次执行未记录故障描述"}</p>
              </section>
              <section className="report-summary-panel">
                <strong>AI 分析结论</strong>
                <p>{currentAnalysis?.conclusion || detailModel.summaryText || "暂无 AI 分析结论"}</p>
              </section>
              <section className="report-summary-panel">
                <strong>最终地址</strong>
                <p>{detailModel.finalUrl || "--"}</p>
              </section>
            </div>
          </Card>

          <Card className="report-steps-card" title="执行步骤详情" subtitle="按步骤查看执行截图、AI 说明、错误信息与网络请求">
            <div className="report-step-accordion">
              {detailModel.steps.map((step) => {
                const isOpen = step.key === expandedStepKey;
                const stepNetworkSummary = buildNetworkSummary(detailModel, step);
                return (
                  <section className={`report-step-item report-step-item--${step.status} ${isOpen ? "is-open" : ""}`} key={step.key}>
                    <button className="report-step-item__trigger" onClick={() => setExpandedStepKey((current) => (current === step.key ? "" : step.key))} type="button">
                      <div className="report-step-item__title">
                        <StatusPill tone={statusTone(step.status)}>{statusText(step.status)}</StatusPill>
                        <strong>步骤 {step.index}: {displayStepTitle(step.title)}</strong>
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
                                    <small>{item.count}</small>
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

          <Card className="report-analysis-card" title="分析记录" subtitle="当前分析结果与历史版本">
            <section className="report-analysis-anchor" ref={analysisSectionRef}>
              <div className="report-analysis-toolbar">
                <button className="btn btn--primary" disabled={analysisBusy || !selectedRunId} onClick={handleAnalysisAction} type="button">
                  {analysisBusy ? "AI 分析中..." : analysisVersions.length ? "查看 AI 分析" : "AI 分析"}
                </button>
                <span className="report-analysis-toolbar__hint">
                  基于当前测试报告内容自动生成分析结论、风险提示和复测建议
                </span>
              </div>
              <div className="report-summary-panels">
                <section className="report-summary-panel">
                  <strong>当前分析</strong>
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
                    <div className="analysis-history__item" key={version.id}>
                      <span>{formatSecondTime(version.created_at)}</span>
                      <small>
                        {version.provider} / {version.model}
                      </small>
                    </div>
                  ))
                ) : (
                  <p className="empty-state">暂无分析历史。</p>
                )}
              </div>
            </section>
          </Card>
        </div>
      )}

      <ScreenshotLightbox screenshot={previewShot} onClose={() => setPreviewShot(null)} />
    </div>
  );
}
