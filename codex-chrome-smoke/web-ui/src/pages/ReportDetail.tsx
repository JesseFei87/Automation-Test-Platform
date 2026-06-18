import { useEffect, useMemo, useState } from "react";
import { API_ORIGIN, api, type ApiObservedAsset, type ApiReportAnalysisVersion, type ApiRunDetailView, type ApiScreenshot } from "../data/api";
import { buildReportListItems, buildRunDetailViewModel, legacyRunDetailToView } from "../data/runViewModels";
import { Card } from "../components/Card";
import { FlowSteps } from "../components/FlowSteps";
import { ScreenshotLightbox } from "../components/ScreenshotLightbox";
import { StatusPill } from "../components/StatusPill";

function statusTone(status: string): "green" | "red" | "amber" | "blue" {
  if (status === "completed" || status === "passed") return "green";
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

function screenshotLabel(index: number) {
  if (index === 0) return "入口";
  if (index === 1) return "执行";
  return "结果";
}

function listFilter(mode: string, status: string, filter: string) {
  if (filter === "all") return true;
  if (filter === "agent") return mode === "agent";
  if (filter === "worker") return mode === "worker";
  return status === filter;
}

export function ReportDetail({ initialRunId = "" }: { initialRunId?: string }) {
  const [reports, setReports] = useState<ReturnType<typeof buildReportListItems>>([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [statusFilter, setStatusFilter] = useState("failed");
  const [runDetail, setRunDetail] = useState<ApiRunDetailView | null>(null);
  const [previewShot, setPreviewShot] = useState<ApiScreenshot | null>(null);
  const [analysisVersions, setAnalysisVersions] = useState<ApiReportAnalysisVersion[]>([]);
  const [observedAsset, setObservedAsset] = useState<ApiObservedAsset | null>(null);
  const [loadState, setLoadState] = useState("正在加载测试报告...");
  const [assetState, setAssetState] = useState("暂无观测资产");
  const [assetBusy, setAssetBusy] = useState(false);

  const filteredReports = useMemo(() => reports.filter((item) => listFilter(item.mode, item.status, statusFilter)), [reports, statusFilter]);
  const detailModel = useMemo(() => buildRunDetailViewModel(runDetail), [runDetail]);
  const selectedReport = useMemo(() => reports.find((item) => item.runId === selectedRunId) || null, [reports, selectedRunId]);

  useEffect(() => {
    async function loadOverview() {
      try {
        const items = buildReportListItems(await api.reports());
        setReports(items);
        const target = (initialRunId ? items.find((item) => item.runId === initialRunId) : null) || items.find((item) => item.status === "failed") || items[0];
        setSelectedRunId(target?.runId || "");
        setLoadState(`已加载 ${items.length} 条执行结果。`);
      } catch {
        setLoadState("无法读取测试报告。");
      }
    }
    void loadOverview();
  }, [initialRunId]);

  useEffect(() => {
    if (initialRunId) setSelectedRunId(initialRunId);
  }, [initialRunId]);

  useEffect(() => {
    if (!selectedRunId) return;
    let cancelled = false;
    async function loadDetail() {
      try {
        const [detail, versions, asset] = await Promise.all([
          api.runDetailView(selectedRunId).catch(async () => legacyRunDetailToView(await api.runDetail(selectedRunId))),
          api.reportAnalysisVersions(selectedRunId).catch(() => []),
          api.observedAsset(selectedRunId).catch(() => null),
        ]);
        if (cancelled) return;
        setRunDetail(detail);
        setAnalysisVersions(versions);
        setObservedAsset(asset);
        setAssetState(asset ? "观测资产已加载" : "本次运行暂无观测资产");
      } catch {
        if (cancelled) return;
        setRunDetail(null);
        setAnalysisVersions([]);
        setObservedAsset(null);
        setAssetState("本次运行暂无观测资产");
      }
    }
    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  async function mergeObservedAsset() {
    if (!selectedRunId) return;
    setAssetBusy(true);
    setAssetState("正在合并到正式 YAML...");
    try {
      const result = await api.mergeObservedAsset(selectedRunId);
      setObservedAsset(result.automation_asset);
      setAssetState(`已合并 ${result.case_id}`);
    } catch (error) {
      setAssetState(error instanceof Error ? error.message : "合并失败");
    } finally {
      setAssetBusy(false);
    }
  }

  return (
    <div className="page report-center-page">
      <FlowSteps activeIndex={5} />
      <div className="report-center-layout report-center-layout--wide">
        <Card className="report-list-card report-list-card--table" title="自动化测试报告" subtitle={loadState}>
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
          <div className="report-table-shell">
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
                      <button className="link-button" onClick={() => setSelectedRunId(item.runId)} type="button">
                        详情
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="report-center-main">
          <Card className="report-summary report-summary--detailed" title="执行报告" subtitle={detailModel.summaryText}>
            <div className="report-summary__copy">
              <h2>{detailModel.caseName || "请选择一份报告"}</h2>
              <p>
                运行编号 {detailModel.runId || "-"} / 模式 {detailModel.modeLabel} / 状态 {detailModel.statusLabel}
              </p>
              <div className="button-row">
                <StatusPill tone={statusTone(detailModel.status)}>{detailModel.statusLabel}</StatusPill>
                <StatusPill tone="blue">{detailModel.screenshots.length} 张截图</StatusPill>
                <StatusPill tone="amber">{detailModel.durationLabel}</StatusPill>
              </div>
              {detailModel.finalUrl ? <p className="analysis-copy">最终地址：{detailModel.finalUrl}</p> : null}
              {detailModel.failureText ? <p className="failure-callout">{detailModel.failureText}</p> : null}
            </div>
            <div className="report-meta-grid">
              <div>
                <span>执行人</span>
                <strong>{detailModel.operator}</strong>
              </div>
              <div>
                <span>开始时间</span>
                <strong>{detailModel.startedAtLabel}</strong>
              </div>
              <div>
                <span>结束时间</span>
                <strong>{detailModel.finishedAtLabel}</strong>
              </div>
              <div>
                <span>用例</span>
                <strong>{detailModel.caseId}</strong>
              </div>
            </div>
          </Card>

          <Card className="step-detail-card" title="执行步骤详情" subtitle="按步骤查看截图、分析、命令输出和错误信息">
            <div className="step-detail-list">
              {detailModel.steps.map((step) => (
                <div className={`step-detail-item step-detail-item--${step.status}`} key={step.key}>
                  <div className="step-detail-item__head">
                    <div>
                      <span>步骤 {step.index}</span>
                      <strong>{step.title}</strong>
                    </div>
                    <StatusPill tone={statusTone(step.status)}>{statusText(step.status)}</StatusPill>
                  </div>
                  <p>{step.summary}</p>
                  <div className="step-detail-item__body">
                    {step.screenshotUrl ? (
                      <button
                        className="step-shot"
                        onClick={() =>
                          setPreviewShot({
                            case_id: detailModel.caseId,
                            filename: `step-${step.index}.png`,
                            path: step.screenshotUrl,
                            url: step.screenshotUrl,
                          })
                        }
                        type="button"
                      >
                        <img alt={`step-${step.index}`} src={`${API_ORIGIN}${step.screenshotUrl}`} />
                        <small>{screenshotLabel(step.index - 1)}</small>
                      </button>
                    ) : (
                      <div className="empty-state">暂无步骤截图</div>
                    )}
                    <pre className="step-detail-item__code">
                      {[step.aiAnalysis, step.finalUrl, step.commandOutput.join("\n"), step.errorMessage].filter(Boolean).join("\n\n") || "暂无附加信息"}
                    </pre>
                  </div>
                </div>
              ))}
              {!detailModel.steps.length ? <p className="empty-state">当前运行暂无步骤详情。</p> : null}
            </div>
          </Card>

          <div className="report-grid report-grid--evidence">
            <Card title="步骤证据区" subtitle="截图、事件、控制台、网络、页面快照、轨迹">
              <div className="screenshot-gallery">
                {detailModel.screenshots.map((shot, index) => (
                  <button className="screenshot-card-mini" key={`${shot.case_id}-${shot.filename}`} onClick={() => setPreviewShot(shot)} type="button">
                    <img alt={shot.filename} src={`${API_ORIGIN}${shot.url}`} />
                    <strong>{shot.filename}</strong>
                    <span>{screenshotLabel(index)}</span>
                  </button>
                ))}
              </div>
              <div className="evidence-actions">
                {detailModel.artifacts.trace_download_url ? (
                  <a className="btn btn--outline" href={`${API_ORIGIN}${detailModel.artifacts.trace_download_url}`} rel="noreferrer" target="_blank">
                    下载执行轨迹
                  </a>
                ) : null}
                {detailModel.artifacts.candidate_flow_url ? (
                  <a className="btn btn--outline" href={`${API_ORIGIN}${detailModel.artifacts.candidate_flow_url}`} rel="noreferrer" target="_blank">
                    候选脚本
                  </a>
                ) : null}
              </div>
            </Card>

            <Card title="AI 与证据分析" subtitle={detailModel.analysis?.provider || "本地规则"}>
              <p className="analysis-copy">{detailModel.analysis?.conclusion || "暂无 AI 分析结论。"}</p>
              <p className="analysis-copy">风险：{detailModel.analysis?.risks?.[0] || "暂无"}</p>
              <p className="analysis-copy">复测建议：{detailModel.analysis?.retest_suggestions?.[0] || "暂无"}</p>
              <div className="analysis-history">
                <strong>历史版本</strong>
                {analysisVersions.slice(0, 5).map((version) => (
                  <div className="analysis-history__item" key={version.id}>
                    <span>{version.created_at}</span>
                    <small>
                      {version.provider} / {version.model}
                    </small>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          <Card className="markdown-card" title="原始资产区" subtitle="原始报告与观测资产">
            <div className="raw-assets-grid">
              <div>
                <strong className="raw-assets-title">原始报告</strong>
                <pre className="markdown-preview">{detailModel.rawReport || "当前运行没有原始报告。"}</pre>
              </div>
              <div>
                <strong className="raw-assets-title">观测资产</strong>
                <div className="button-row">
                  <button className="btn btn--green" disabled={!selectedReport || selectedReport.mode === "agent" || assetBusy} onClick={mergeObservedAsset} type="button">
                    {assetBusy ? "正在合并..." : "合并为正式代码"}
                  </button>
                </div>
                <p className="muted">{assetState}</p>
                <pre className="observed-asset-preview">{observedAsset ? JSON.stringify(observedAsset, null, 2) : "当前运行没有观测资产。"}</pre>
              </div>
            </div>
          </Card>
        </div>
      </div>
      <ScreenshotLightbox screenshot={previewShot} onClose={() => setPreviewShot(null)} />
    </div>
  );
}
