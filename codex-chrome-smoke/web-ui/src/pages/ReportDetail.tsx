import { useEffect, useMemo, useState } from "react";
import { API_ORIGIN, api, type ApiObservedAsset, type ApiReport, type ApiReportAnalysisVersion, type ApiRunDetail, type ApiScreenshot } from "../data/api";
import { Card } from "../components/Card";
import { FlowSteps } from "../components/FlowSteps";
import { ScreenshotLightbox } from "../components/ScreenshotLightbox";
import { StatusPill } from "../components/StatusPill";

type ReportDetailResponse = {
  run_id: string;
  metadata: { case_id: string; case_name: string; status: string; screenshots: ApiScreenshot[] };
  markdown: string;
  screenshots: ApiScreenshot[];
  evidence?: ApiRunDetail["evidence"];
  analysis: NonNullable<ApiRunDetail["analysis"]>;
};

function statusTone(status: string): "green" | "red" | "amber" | "blue" {
  if (status === "passed") return "green";
  if (status === "failed") return "red";
  if (status === "running") return "blue";
  return "amber";
}

function formatTime(seconds: number) {
  return new Date(seconds * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function screenshotStage(index: number) {
  if (index === 0) return "入口态";
  if (index === 1) return "动作态";
  return "完成态";
}

function evidenceText(value: unknown) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export function ReportDetail({ initialRunId = "" }: { initialRunId?: string }) {
  const [reports, setReports] = useState<ApiReport[]>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [statusFilter, setStatusFilter] = useState("failed");
  const [detail, setDetail] = useState<ReportDetailResponse | null>(null);
  const [loadState, setLoadState] = useState("正在加载报告中心...");
  const [previewShot, setPreviewShot] = useState<ApiScreenshot | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<NonNullable<ApiRunDetail["analysis"]> | null>(null);
  const [analysisVersions, setAnalysisVersions] = useState<ApiReportAnalysisVersion[]>([]);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState("");
  const [observedAsset, setObservedAsset] = useState<ApiObservedAsset | null>(null);
  const [assetState, setAssetState] = useState("暂无 observed asset");
  const [assetBusy, setAssetBusy] = useState(false);

  useEffect(() => {
    api
      .reports()
      .then((items) => {
        setReports(items);
        const priority = initialRunId
          ? items.find((item) => item.run_id === initialRunId)
          : items.find((item) => item.status === "failed");
        setSelectedRunId((current) => current || priority?.run_id || items[0]?.run_id || "");
        setLoadState(items.length ? `已加载 ${items.length} 份历史报告` : "暂无历史报告");
      })
      .catch(() => setLoadState("后端未启动，无法读取真实报告"));
  }, [initialRunId]);

  useEffect(() => {
    if (initialRunId) {
      setSelectedRunId(initialRunId);
    }
  }, [initialRunId]);

  useEffect(() => {
    if (!selectedRunId) return;
    setLoadState(`正在读取 ${selectedRunId}...`);
    api
      .reportDetail(selectedRunId)
      .then((result) => {
        setDetail(result);
        setAiAnalysis(result.analysis);
        loadAnalysisVersions(result.run_id);
        loadObservedAsset(result.run_id);
        setAiError("");
        setLoadState(`当前报告：${result.run_id}`);
      })
      .catch(() => {
        setDetail(null);
        setAiAnalysis(null);
        setAnalysisVersions([]);
        setObservedAsset(null);
        setAssetState("暂无 observed asset");
        setLoadState("报告详情读取失败");
      });
  }, [selectedRunId]);

  async function loadObservedAsset(runId: string) {
    setAssetState("正在读取 observed asset...");
    try {
      const result = await api.observedAsset(runId);
      setObservedAsset(result);
      setAssetState("observed asset 已加载");
    } catch {
      setObservedAsset(null);
      setAssetState("本次运行暂无 observed asset");
    }
  }

  async function loadAnalysisVersions(runId: string) {
    try {
      const result = await api.reportAnalysisVersions(runId);
      setAnalysisVersions(result);
    } catch {
      setAnalysisVersions([]);
    }
  }

  async function runAiAnalysis(force = false) {
    if (!selectedRunId) return;
    setAiBusy(true);
    setAiError("");
    try {
      const result = await api.analyzeReport(selectedRunId, { force });
      setAiAnalysis(result);
      await loadAnalysisVersions(selectedRunId);
    } catch (error) {
      setAiError(error instanceof Error ? error.message : "AI 分析失败");
    } finally {
      setAiBusy(false);
    }
  }

  async function mergeObservedAsset() {
    if (!selectedRunId || !observedAsset) return;
    setAssetBusy(true);
    setAssetState("正在合并到正式 YAML...");
    try {
      const result = await api.mergeObservedAsset(selectedRunId);
      setObservedAsset(result.automation_asset);
      setAssetState(`已合并为 verified automation_asset：${result.case_id}`);
    } catch (error) {
      setAssetState(`合并失败：${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setAssetBusy(false);
    }
  }

  const filteredReports = useMemo(() => {
    if (statusFilter === "all") return reports;
    return reports.filter((report) => report.status === statusFilter);
  }, [reports, statusFilter]);

  const selectedReport =
    reports.find((report) => report.run_id === selectedRunId) ||
    (detail
      ? {
          run_id: detail.run_id,
          case_id: detail.metadata.case_id,
          case_name: detail.metadata.case_name,
          status: detail.metadata.status,
          path: `reports/runs/${detail.run_id}.md`,
          updated_at: Date.now() / 1000,
          screenshot_count: detail.screenshots.length,
        }
      : reports[0]);
  const screenshots = detail?.screenshots || [];
  const evidencePercent = screenshots.length >= 3 ? "100%" : screenshots.length ? `${Math.round((screenshots.length / 3) * 100)}%` : "0%";
  const analysis = aiAnalysis || detail?.analysis;
  const evidence = detail?.evidence;
  const canMergeObservedAsset = Boolean(observedAsset && selectedReport?.status === "passed");
  const observedSelectorCount = Array.isArray(observedAsset?.selectors)
    ? observedAsset?.selectors.length || 0
    : Object.keys(observedAsset?.selectors || {}).length;

  return (
    <div className="page report-center-page">
      <FlowSteps activeIndex={5} />

      <div className="report-center-layout">
        <Card className="report-list-card" title="报告列表" subtitle={loadState}>
          <div className="report-filters">
            {["all", "passed", "failed", "unknown"].map((status) => (
              <button
                className={statusFilter === status ? "is-active" : ""}
                key={status}
                onClick={() => setStatusFilter(status)}
                type="button"
              >
                {status === "all" ? "全部" : status}
              </button>
            ))}
          </div>

          <div className="report-list">
            {filteredReports.map((report) => (
              <button
                className={`report-list__item ${report.run_id === selectedRunId ? "is-active" : ""} ${report.status === "failed" ? "is-failed" : ""}`}
                key={report.run_id}
                onClick={() => setSelectedRunId(report.run_id)}
                type="button"
              >
                <span className="report-list__top">
                  <strong>{report.run_id}</strong>
                  <StatusPill tone={statusTone(report.status)}>{report.status}</StatusPill>
                </span>
                <span>{report.case_name || report.case_id || "未知 case"}</span>
                <small>{formatTime(report.updated_at)} · {report.screenshot_count} 张截图</small>
              </button>
            ))}
          </div>
        </Card>

        <div className="report-center-main">
          <Card className="report-summary">
            <div>
              <h2>{selectedReport?.case_name || "请选择一份报告"}</h2>
              <p>
                Run ID {selectedReport?.run_id || "-"} · 状态 {selectedReport?.status || "-"} ·
                产物完整可追溯
              </p>
              <div className="button-row">
                <StatusPill tone={statusTone(selectedReport?.status || "unknown")}>{selectedReport?.status || "unknown"}</StatusPill>
                <StatusPill tone="blue">{screenshots.length} 张截图</StatusPill>
                <StatusPill tone="purple">AI 已分析</StatusPill>
                <StatusPill tone="amber">Markdown 已归档</StatusPill>
              </div>
              {selectedReport?.status === "failed" ? (
                <p className="failure-callout">失败报告已优先定位：建议先放大查看 action/final 截图，再核对下方 Markdown 失败点。</p>
              ) : null}
            </div>
            <div className="evidence-score">
              <span>证据完整度</span>
              <strong>{evidencePercent}</strong>
              <small>entry / action / final</small>
            </div>
          </Card>

          <div className="report-grid">
            <Card title="截图证据链" subtitle="点击任意截图可放大查看失败现场。">
              <div className="screenshot-gallery">
                {screenshots.length ? (
                  screenshots.map((shot, index) => (
                    <button className="screenshot-card-mini" key={`${shot.case_id}-${shot.filename}`} onClick={() => setPreviewShot(shot)} type="button">
                      <img alt={shot.filename} src={`${API_ORIGIN}${shot.url}`} />
                      <strong>{shot.filename}</strong>
                      <span>{screenshotStage(index)}</span>
                    </button>
                  ))
                ) : (
                  <p className="empty-state">当前报告未解析到截图路径。</p>
                )}
              </div>
            </Card>

            <Card title="AI 报告分析" subtitle={`provider: ${analysis?.provider || "local"} · ${analysis?.source || "rule"}`}>
              <p className="analysis-copy">{analysis?.conclusion || "暂无 AI 分析，请先选择一份报告。"}</p>
              <p className="analysis-copy">风险：{analysis?.risks?.[0] || "暂无风险项。"}</p>
              <p className="analysis-copy">复测建议：{analysis?.retest_suggestions?.[0] || "暂无复测建议。"}</p>
              {aiError ? <p className="failure-callout">AI 分析失败：{aiError}</p> : null}
              <div className="button-row">
                <StatusPill tone={statusTone(analysis?.status || selectedReport?.status || "unknown")}>{analysis?.status || selectedReport?.status || "unknown"}</StatusPill>
                <StatusPill tone="blue">{analysis?.log_count ?? 0} 行日志</StatusPill>
                {analysis?.model ? <StatusPill tone="purple">{analysis.model}</StatusPill> : null}
                {analysis?.source === "ai" ? <StatusPill tone={analysis.cached ? "green" : "amber"}>{analysis.cached ? "已缓存" : "新分析"}</StatusPill> : null}
                <button className="btn btn--primary" disabled={aiBusy || !selectedRunId} onClick={() => runAiAnalysis(false)} type="button">
                  {aiBusy ? "AI 分析中..." : "调用 AI 分析"}
                </button>
                <button className="btn btn--outline" disabled={aiBusy || !selectedRunId} onClick={() => runAiAnalysis(true)} type="button">
                  强制重新分析
                </button>
              </div>
              <div className="analysis-history">
                <strong>历史版本</strong>
                {analysisVersions.length ? (
                  analysisVersions.slice(0, 5).map((version) => (
                    <button className="analysis-history__item" key={version.id} onClick={() => setAiAnalysis(version.analysis)} type="button">
                      <span>{version.created_at}</span>
                      <small>{version.provider} / {version.model}</small>
                    </button>
                  ))
                ) : (
                  <span className="muted">暂无历史版本，强制重新分析后会保留记录。</span>
                )}
              </div>
            </Card>
          </div>

          {evidence ? (
            <Card className="run-evidence-card" title="执行证据链" subtitle="真实执行过程自动采集，供失败归因和 automation_asset 沉淀使用">
              <div className="evidence-summary-grid">
                <StatusPill tone={evidence.trace.exists ? "green" : "amber"}>trace {evidence.trace.exists ? "ready" : "pending"}</StatusPill>
                <StatusPill tone={evidence.events.count ? "green" : "amber"}>{evidence.events.count} events</StatusPill>
                <StatusPill tone={evidence.console.count ? "green" : "amber"}>{evidence.console.count} console</StatusPill>
                <StatusPill tone={evidence.network.count ? "green" : "amber"}>{evidence.network.count} network</StatusPill>
                <StatusPill tone={evidence.dom.count ? "green" : "amber"}>{evidence.dom.count} DOM</StatusPill>
              </div>
              <div className="evidence-actions">
                {evidence.trace.exists ? (
                  <a className="btn btn--outline" href={`${API_ORIGIN}${evidence.trace.url}`} rel="noreferrer" target="_blank">
                    下载 Playwright trace.zip
                  </a>
                ) : null}
                {evidence.events.exists ? (
                  <a className="btn btn--outline" href={`${API_ORIGIN}/api/runs/${evidence.run_id}/evidence/events`} rel="noreferrer" target="_blank">
                    events.jsonl
                  </a>
                ) : null}
                {evidence.console.exists ? (
                  <a className="btn btn--outline" href={`${API_ORIGIN}/api/runs/${evidence.run_id}/evidence/console`} rel="noreferrer" target="_blank">
                    console.jsonl
                  </a>
                ) : null}
                {evidence.network.exists ? (
                  <a className="btn btn--outline" href={`${API_ORIGIN}/api/runs/${evidence.run_id}/evidence/network`} rel="noreferrer" target="_blank">
                    network.jsonl
                  </a>
                ) : null}
              </div>
              <div className="evidence-detail-grid">
                <div className="evidence-panel">
                  <strong>步骤时间线</strong>
                  {evidence.events.latest.length ? (
                    evidence.events.latest.slice(-8).map((item, index) => (
                      <p key={`report-event-${index}`}>
                        <span>{evidenceText(item.kind)}</span>
                        <small>{evidenceText(item.message)}</small>
                      </p>
                    ))
                  ) : (
                    <p className="muted">暂无 events 证据。</p>
                  )}
                </div>
                <div className="evidence-panel">
                  <strong>DOM 快照</strong>
                  {evidence.dom.files.length ? (
                    evidence.dom.files.slice(-8).map((item) => (
                      <a href={`${API_ORIGIN}${item.url}`} key={item.filename} rel="noreferrer" target="_blank">
                        {item.filename}
                      </a>
                    ))
                  ) : (
                    <p className="muted">暂无 DOM 快照。</p>
                  )}
                </div>
                <div className="evidence-panel">
                  <strong>Console / Network 摘要</strong>
                  {evidence.console.latest.slice(-3).map((item, index) => (
                    <p key={`report-console-${index}`}>
                      <span>console {evidenceText(item.level)}</span>
                      <small>{evidenceText(item.text)}</small>
                    </p>
                  ))}
                  {evidence.network.latest.slice(-3).map((item, index) => (
                    <p key={`report-network-${index}`}>
                      <span>{evidenceText(item.method)} {evidenceText(item.status)}</span>
                      <small>{evidenceText(item.url)}</small>
                    </p>
                  ))}
                </div>
              </div>
            </Card>
          ) : null}

          <Card className="markdown-card" title="Markdown 原始报告" subtitle={selectedReport?.path || "reports/runs/*.md"}>
            <pre className="markdown-preview">{detail?.markdown || "请选择一份报告查看原始 Markdown。"}</pre>
          </Card>
          <Card className="observed-asset-card" title="运行沉淀资产 observed asset" subtitle={assetState}>
            <div className="observed-asset-summary">
              <StatusPill tone={observedAsset ? "green" : "amber"}>{observedAsset ? observedAsset.status || "observed" : "暂无"}</StatusPill>
              <StatusPill tone="blue">{observedAsset?.operation_steps?.length || 0} 步骤</StatusPill>
              <StatusPill tone="purple">{observedSelectorCount} selector</StatusPill>
              <StatusPill tone="cyan">{Object.keys(observedAsset?.input_values || {}).length} 输入</StatusPill>
              <StatusPill tone="dark">{observedAsset?.assertions?.length || 0} 断言</StatusPill>
            </div>
            <p className="analysis-copy">
              这份资产来自后台 Playwright 真实执行。只有报告状态为 passed 时，才允许合并为 verified automation_asset。
            </p>
            <div className="button-row">
              <button className="btn btn--green" disabled={!canMergeObservedAsset || assetBusy} onClick={mergeObservedAsset} type="button">
                {assetBusy ? "正在合并..." : "合并为 verified automation_asset"}
              </button>
              <button className="btn btn--outline" disabled={!selectedRunId || assetBusy} onClick={() => loadObservedAsset(selectedRunId)} type="button">
                重新读取
              </button>
              {!canMergeObservedAsset && observedAsset ? <span className="muted">仅 passed 的单 case run 可合并。</span> : null}
            </div>
            <pre className="observed-asset-preview">
              {observedAsset ? JSON.stringify(observedAsset, null, 2) : "当前报告没有 observed asset。请先通过执行中心后台跑一次 case。"}
            </pre>
          </Card>
        </div>
      </div>
      <ScreenshotLightbox screenshot={previewShot} onClose={() => setPreviewShot(null)} />
    </div>
  );
}
