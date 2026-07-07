import { useEffect, useMemo, useState } from "react";
import { API_ORIGIN, api, type ApiCase, type ApiRunDetailView, type ApiScreenshot } from "../data/api";
import { buildExecutionListItems, buildRunDetailViewModel, legacyRunDetailToView, type ExecutionListItem, type RunDetailViewModel } from "../data/runViewModels";
import { Card } from "../components/Card";
import { ConsolePanel } from "../components/ConsolePanel";
import { FlowSteps } from "../components/FlowSteps";
import { ScreenshotLightbox } from "../components/ScreenshotLightbox";
import { StatusPill } from "../components/StatusPill";

type ExecutionTab = "worker" | "agent";

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

function assertionTone(status: string): "green" | "red" | "amber" | "blue" {
  if (status === "completed" || status === "passed" || status === "success") return "green";
  if (status === "failed") return "red";
  if (status === "running") return "blue";
  return "amber";
}

function assertionText(status: string) {
  if (status === "completed" || status === "passed" || status === "success") return "已通过";
  if (status === "failed") return "未通过";
  if (status === "running") return "待校验";
  return "待校验";
}

function isLiveStatus(status: string) {
  return status === "running" || status === "queued" || status === "pending";
}

function formatLogTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function latestLine(detail: ApiRunDetailView | null) {
  if (!detail?.logs?.length) return ["暂无真实运行日志。"];
  return detail.logs.map((log) => `[${formatLogTimestamp(log.created_at)}] ${log.line}`);
}

function stepActionText(step: RunDetailViewModel["steps"][number] | null) {
  if (!step) return "";
  const normalized = step.title.replace(/^(?:[^-]*?)\s*\d+\s*[-:?]\s*/u, "").trim();
  return normalized || step.title.trim();
}

function stepHeading(step: RunDetailViewModel["steps"][number]) {
  const actionText = stepActionText(step);
  return `步骤 ${step.index} - ${actionText || step.title}`;
}

function findAutoFocusedStepKey(detailModel: RunDetailViewModel) {
  const { steps } = detailModel;
  if (!steps.length) return "";
  const lastRunning = [...steps].reverse().find((step) => step.status === "running");
  if (lastRunning) return lastRunning.key;
  const lastFailed = [...steps].reverse().find((step) => step.status === "failed");
  if (lastFailed) return lastFailed.key;
  const lastCompleted = [...steps].reverse().find((step) => step.status === "completed" || step.status === "passed" || step.status === "success");
  if (lastCompleted) return lastCompleted.key;
  const firstQueued = steps.find((step) => step.status === "queued");
  return firstQueued?.key || steps[0].key;
}

function tabForItem(item?: ExecutionListItem | null): ExecutionTab {
  return item?.mode === "agent" ? "agent" : "worker";
}

export function ExecutionCenter({
  initialRunId = "",
  onOpenReport,
}: {
  initialRunId?: string;
  onOpenReport: (runId: string) => void;
  onOpenCaseDraft?: (draftId: number) => void;
}) {
  const [cases, setCases] = useState<ApiCase[]>([]);
  const [runs, setRuns] = useState<ExecutionListItem[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [message, setMessage] = useState("正在连接本地执行服务...");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runDetail, setRunDetail] = useState<ApiRunDetailView | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [activeExecutionTab, setActiveExecutionTab] = useState<ExecutionTab>("worker");
  const [selectedStepKey, setSelectedStepKey] = useState("");
  const [promoting, setPromoting] = useState(false);
  const [selfHealing, setSelfHealing] = useState(false);
  const [deletingRunId, setDeletingRunId] = useState("");
  const [lastPromotedCaseId, setLastPromotedCaseId] = useState("");
  const [previewShot, setPreviewShot] = useState<ApiScreenshot | null>(null);
  const [overviewExpanded, setOverviewExpanded] = useState(true);

  const workerRuns = useMemo(() => runs.filter((item) => item.mode === "worker"), [runs]);
  const agentRuns = useMemo(() => runs.filter((item) => item.mode === "agent"), [runs]);
  const visibleRuns = useMemo(() => (activeExecutionTab === "agent" ? agentRuns : workerRuns), [activeExecutionTab, agentRuns, workerRuns]);
  const selectedRun = useMemo(() => runs.find((item) => item.runId === selectedRunId) || null, [runs, selectedRunId]);
  const hasLiveRuns = useMemo(() => runs.some((item) => isLiveStatus(item.status)), [runs]);
  const detailModel = useMemo(() => buildRunDetailViewModel(runDetail), [runDetail]);
  const activeStageNumber = useMemo(() => {
    const currentStage = detailModel.stagePlan.find((stage) => stage.isCurrent);
    if (currentStage?.index) return currentStage.index;
    const runningStage = detailModel.stagePlan.find((stage) => stage.status === "running");
    if (runningStage?.index) return runningStage.index;
    const failedStage = detailModel.stagePlan.find((stage) => stage.status === "failed");
    if (failedStage?.index) return failedStage.index;
    const completedStages = detailModel.stagePlan.filter((stage) => stage.status === "completed" || stage.status === "passed" || stage.status === "success");
    return completedStages.at(-1)?.index || 0;
  }, [detailModel.stagePlan]);
  const latestScreenshot = detailModel.screenshots.at(-1) || null;
  const selectedStep = useMemo(() => detailModel.steps.find((step) => step.key === selectedStepKey) || detailModel.steps[0] || null, [detailModel.steps, selectedStepKey]);
  const previewScreenshotUrl = selectedStep?.screenshotUrl || latestScreenshot?.url || "";
  const previewScreenshot = useMemo(() => {
    if (!previewScreenshotUrl) return null;
    return detailModel.screenshots.find((shot) => shot.url === previewScreenshotUrl) || null;
  }, [detailModel.screenshots, previewScreenshotUrl]);
  const canPromoteRegression = detailModel.mode === "agent" && detailModel.status === "completed" && Boolean(detailModel.artifacts.candidate_flow_url);
  const canSelfHeal = detailModel.mode === "agent" && detailModel.status === "failed" && Boolean(detailModel.artifacts.trace_download_url);
  const isProcessInitializing = Boolean(selectedRunId) && !detailModel.steps.length && (runDetail === null || detailModel.status === "queued" || detailModel.status === "running");

  async function loadCases() {
    try {
      const result = await api.cases();
      setCases(result);
      setSelectedCaseId((current) => (result.some((item) => item.id === current) ? current : result[0]?.id || ""));
    } catch {
      setMessage("无法读取正式用例。");
    }
  }

  async function refreshRuns() {
    try {
      const result = buildExecutionListItems(await api.runs());
      setRuns(result);
      const preferred = result.find((item) => item.status === "running") || result.find((item) => item.status === "failed") || result[0];
      setSelectedRunId((current) => (current && result.some((item) => item.runId === current) ? current : preferred?.runId || ""));
      setMessage(`已加载 ${result.length} 条执行任务。`);
    } catch {
      setMessage("无法读取执行队列。");
    }
  }

  async function startRun(mode: "run-case" | "run-batch") {
    if (mode === "run-case" && !selectedCaseId) return;
    setSubmitting(true);
    try {
      const task = await api.createRun(mode, mode === "run-case" ? selectedCaseId : undefined);
      setActiveExecutionTab("worker");
      setSelectedRunId(task.id);
      setMessage(`已入队 ${task.id}`);
      await refreshRuns();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function promoteRegression() {
    const runId = selectedRunId || initialRunId;
    if (!runId) {
      setMessage("请先选择一条执行记录");
      return;
    }
    setPromoting(true);
    try {
      const result = await api.promoteRegression(runId);
      setLastPromotedCaseId(result.case_id);
      await loadCases();
      setSelectedCaseId(result.case_id);
      setMessage(`已沉淀为正式回归用例：${result.case_id}`);
    } catch (error) {
      setLastPromotedCaseId("");
      setMessage(error instanceof Error ? error.message : "沉淀失败");
    } finally {
      setPromoting(false);
    }
  }

  async function selfHealAgentRun() {
    const runId = selectedRunId || initialRunId;
    if (!runId) {
      setMessage("请先选择一条执行记录");
      return;
    }
    setSelfHealing(true);
    try {
      const task = await api.selfHealAgentExplore(runId);
      setActiveExecutionTab("agent");
      setSelectedRunId(task.id);
      setRunDetail(null);
      await refreshRuns();
      setMessage(`已创建自愈任务：${task.id}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Agent 自愈提交失败");
    } finally {
      setSelfHealing(false);
    }
  }

  async function deleteRun(runId: string) {
    if (!window.confirm("是否确认删除？")) return;
    setDeletingRunId(runId);
    try {
      await api.deleteRun(runId);
      if (selectedRunId === runId) {
        setSelectedRunId("");
        setRunDetail(null);
        setSelectedStepKey("");
      }
      await refreshRuns();
      setMessage(`已删除任务 ${runId}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除任务失败");
    } finally {
      setDeletingRunId("");
    }
  }

  useEffect(() => {
    void loadCases();
    void refreshRuns();
  }, []);

  useEffect(() => {
    if (!hasLiveRuns) return;
    const timer = window.setInterval(() => void refreshRuns(), 5000);
    return () => window.clearInterval(timer);
  }, [hasLiveRuns]);

  useEffect(() => {
    if (initialRunId) setSelectedRunId(initialRunId);
  }, [initialRunId]);

  useEffect(() => {
    if (selectedRun) setActiveExecutionTab(tabForItem(selectedRun));
  }, [selectedRun]);

  useEffect(() => {
    setSelectedStepKey("");
  }, [selectedRunId]);

  useEffect(() => {
    if (!detailModel.steps.length) {
      setSelectedStepKey("");
      return;
    }
    const autoFocusedStepKey = findAutoFocusedStepKey(detailModel);
    setSelectedStepKey((current) => {
      if (!detailModel.steps.some((step) => step.key === current)) return autoFocusedStepKey;
      if (detailModel.status === "running") return autoFocusedStepKey;
      if (detailModel.status === "failed" && detailModel.steps.some((step) => step.key === autoFocusedStepKey && step.status === "failed")) return autoFocusedStepKey;
      return current;
    });
  }, [detailModel]);

  useEffect(() => {
    if (!selectedRunId) return;
    let cancelled = false;
    let timer: number | undefined;
    async function loadDetail() {
      try {
        const detail = await api.runDetailView(selectedRunId).catch(async () => legacyRunDetailToView(await api.runDetail(selectedRunId)));
        if (cancelled) return;
        setRunDetail(detail);
        if (isLiveStatus(detail.status)) timer = window.setTimeout(() => void loadDetail(), 2500);
      } catch {
        if (cancelled) return;
        setRunDetail(null);
        if (!selectedRun || isLiveStatus(selectedRun.status)) timer = window.setTimeout(() => void loadDetail(), 2500);
      }
    }
    void loadDetail();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [selectedRunId, selectedRun?.status]);

  return (
    <div className={`page execution-page ${overviewExpanded ? "execution-page--overview-expanded" : "execution-page--overview-collapsed"}`}>
      <FlowSteps activeIndex={5} />
      <div className="execution-sections">
        <section className={`execution-cluster execution-cluster--primary ${overviewExpanded ? "is-expanded" : "is-collapsed"}`}>
          <button
            aria-expanded={overviewExpanded}
            className="execution-cluster__toggle"
            onClick={() => setOverviewExpanded((current) => !current)}
            type="button"
          >
            <span className="execution-cluster__toggle-text">执行入口与执行预览</span>
            <span className="execution-cluster__toggle-icon">{overviewExpanded ? "收起" : "展开"}</span>
          </button>
          <div className="execution-cluster__body">
            <div className="execution-cluster__grid">
          <Card className="execution-entry-card" title="执行入口" subtitle="常规执行与智能探索共用同一调度台">
            <label className="field-label" htmlFor="case-select">
              选择正式用例
            </label>
            <select className="case-select" id="case-select" onChange={(event) => setSelectedCaseId(event.target.value)} value={selectedCaseId}>
              {cases.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.id} {item.title ? `- ${item.title}` : ""}
                </option>
              ))}
            </select>
            <div className="button-row">
              <button className="btn btn--primary" disabled={submitting || !selectedCaseId} onClick={() => startRun("run-case")} type="button">
                执行单条
              </button>
              <button className="btn btn--green" disabled={submitting} onClick={() => startRun("run-batch")} type="button">
                批量执行
              </button>
            </div>
            <p className="muted">
              {message}
              {lastPromotedCaseId ? (
                <>
                  {" "}
                  <span className="muted">已选中 {lastPromotedCaseId}</span>
                </>
              ) : null}
            </p>
          </Card>

          <Card className="execution-preview-card" title="执行预览" subtitle="左侧选中任务后，这里显示过程和结果">
            <div className="run-meta">
              <StatusPill tone={statusTone(detailModel.status)}>{detailModel.statusLabel}</StatusPill>
              <span>{detailModel.runId || "等待选择任务"}</span>
              {detailModel.mode === "agent" ? (
                <StatusPill tone={detailModel.trigger === "self_heal" ? "blue" : "amber"}>{detailModel.trigger === "self_heal" ? "自愈探索" : "普通探索"}</StatusPill>
              ) : null}
              {selectedRun?.hasReport ? (
                <button className="btn btn--outline" onClick={() => onOpenReport(selectedRun.runId)} type="button">
                  查看报告
                </button>
              ) : null}
            </div>
            <div className="execution-preview-head">
              <div className="execution-preview-stat">
                <span>模式</span>
                <strong>{detailModel.modeLabel}</strong>
              </div>
              <div className="execution-preview-stat">
                <span>开始时间</span>
                <strong>{detailModel.startedAtLabel}</strong>
              </div>
              <div className="execution-preview-stat">
                <span>最终地址</span>
                <strong>{detailModel.finalUrl || "--"}</strong>
              </div>
            </div>
            <ConsolePanel lines={latestLine(runDetail)} running={detailModel.status === "running"} />
          </Card>
            </div>
          </div>
        </section>

        <section className="execution-cluster execution-cluster--secondary">
          <div className="execution-cluster__grid">
          <Card className="queue-card" title="任务队列" subtitle="按模式拆分显示执行任务">
            <div className="execution-tabs" role="tablist" aria-label="执行任务类型">
              <button className={activeExecutionTab === "worker" ? "is-active" : ""} onClick={() => setActiveExecutionTab("worker")} role="tab" type="button">
                常规执行 <span>{workerRuns.length}</span>
              </button>
              <button className={activeExecutionTab === "agent" ? "is-active" : ""} onClick={() => setActiveExecutionTab("agent")} role="tab" type="button">
                智能探索 <span>{agentRuns.length}</span>
              </button>
            </div>

            <div className="execution-list">
              {visibleRuns.map((item) => (
                <div
                  className={`execution-list__item ${item.runId === selectedRunId ? "is-active" : ""} ${item.status === "failed" ? "is-failed" : ""}`}
                  key={item.runId}
                  onClick={() => setSelectedRunId(item.runId)}
                >
                  <div className="execution-list__top">
                    <div className="execution-list__select execution-list__select--title">
                      <strong>{item.displayName}</strong>
                    </div>
                    <div className="execution-list__actions">
                      <StatusPill tone={statusTone(item.status)}>{item.statusLabel}</StatusPill>
                      <button
                        aria-label={`删除任务 ${item.runId}`}
                        className="icon-button icon-button--danger"
                        disabled={Boolean(deletingRunId)}
                        onClick={(event) => {
                          event.stopPropagation();
                          void deleteRun(item.runId);
                        }}
                        title="删除任务"
                        type="button"
                      >
                        <svg aria-hidden="true" fill="none" height="16" viewBox="0 0 24 24" width="16">
                          <path d="M4 7h16" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
                          <path d="M9 4h6" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
                          <path d="M7 7l1 12h8l1-12" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
                          <path d="M10 11v5M14 11v5" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
                        </svg>
                      </button>
                    </div>
                  </div>
                  <div className="execution-list__select execution-list__select--body execution-list__timebar">
                    <small>
                      {item.startedAtLabel} / {item.durationLabel}
                    </small>
                  </div>
                  <div className="execution-list__meta">
                    <StatusPill tone={item.hasReport ? "green" : "amber"}>{item.hasReport ? "有报告" : "无报告"}</StatusPill>
                    <StatusPill tone={item.hasEvidence ? "blue" : "amber"}>{item.hasEvidence ? "有证据" : "待证据"}</StatusPill>
                  </div>
                </div>
              ))}
              {!visibleRuns.length ? <p className="empty-state">当前标签下暂无任务。</p> : null}
            </div>
          </Card>
          <Card className="execution-live-card" title={detailModel.mode === "agent" ? "智能探索执行过程" : "执行步骤预览"} subtitle={detailModel.summaryText}>
            {isProcessInitializing && selectedRun?.mode === "agent" ? (
              <div className="execution-stage-strip execution-stage-strip--skeleton" aria-label="正在加载执行阶段">
                {Array.from({ length: 4 }, (_, index) => (
                  <div className="execution-stage-skeleton" key={index}>
                    <span className="execution-skeleton execution-skeleton--node" />
                    <span className="execution-skeleton execution-skeleton--line" />
                  </div>
                ))}
              </div>
            ) : detailModel.mode === "agent" && detailModel.stagePlan.length ? (
              <div className={`execution-stage-strip ${detailModel.status === "running" ? "execution-stage-strip--running" : ""}`}>
                {detailModel.stagePlan.map((stage) => (
                  <div
                    className={`execution-stage-chip execution-stage-chip--${stage.status} ${detailModel.status === "running" && stage.index === activeStageNumber ? "is-current" : ""} ${detailModel.status !== "running" && stage.index === activeStageNumber ? "is-terminal" : ""} ${stage.index < activeStageNumber ? "is-past" : ""}`}
                    key={stage.stageId}
                  >
                    <div className="execution-stage-chip__node" aria-hidden="true">
                      <span>{stage.index}</span>
                    </div>
                    <div className="execution-stage-chip__body">
                      <div className="execution-stage-chip__head">
                        <strong>{stage.name}</strong>
                        <StatusPill tone={statusTone(stage.status)}>{statusText(stage.status)}</StatusPill>
                      </div>
                      <span>{stage.sceneLabel} / {stage.strategyLabel}</span>
                      {stage.fallbackUsed ? <em>{"\u5df2\u56de\u9000"}</em> : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
            <div className={`execution-live-layout ${isProcessInitializing ? "is-initializing" : ""}`}>
              <div className="execution-live-steps">
                {isProcessInitializing
                  ? Array.from({ length: 5 }, (_, index) => (
                      <div className="execution-live-step execution-live-step--skeleton" key={index}>
                        <span className="execution-skeleton execution-skeleton--pill" />
                        <span className="execution-skeleton execution-skeleton--title" />
                        <span className="execution-skeleton execution-skeleton--copy" />
                      </div>
                    ))
                  : detailModel.steps.map((step) => (
                  <button
                    className={`execution-live-step execution-live-step--${step.status} ${selectedStep?.key === step.key ? "is-active" : ""}`}
                    key={step.key}
                    onClick={() => setSelectedStepKey(step.key)}
                    type="button"
                  >
                    <div className="execution-live-step__head">
                      <StatusPill tone={statusTone(step.status)}>{statusText(step.status)}</StatusPill>
                    </div>
                    <strong>{stepHeading(step)}</strong>
                    <span>{step.summary}</span>
                  </button>
                ))}
                {!isProcessInitializing && !detailModel.steps.length ? <p className="empty-state">暂无步骤明细。</p> : null}
              </div>

              <div className="execution-live-preview">
                <div className="execution-live-workspace">
                  <div className="execution-live-workspace__head">
                    <div className="execution-live-workspace__copy">
                      {isProcessInitializing ? (
                        <>
                          <span className="execution-skeleton execution-skeleton--heading" />
                          <span className="execution-skeleton execution-skeleton--copy" />
                        </>
                      ) : (
                        <>
                          <strong>{selectedStep ? `步骤 ${selectedStep.index} - ${stepActionText(selectedStep)}` : "当前步骤"}</strong>
                          <span>{selectedStep?.summary || detailModel.summaryText || "暂无当前步骤说明"}</span>
                        </>
                      )}
                    </div>
                    <span className="execution-live-workspace__tag">{previewScreenshotUrl ? "当前画面" : "等待画面"}</span>
                  </div>
                  <div className={`execution-live-canvas ${previewScreenshotUrl ? "" : "execution-live-canvas--empty"}`}>
                    {previewScreenshotUrl ? (
                      <button className="execution-live-canvas__button" onClick={() => previewScreenshot && setPreviewShot(previewScreenshot)} type="button">
                        <img alt={stepActionText(selectedStep) || latestScreenshot?.filename || "执行截图"} src={`${API_ORIGIN}${previewScreenshotUrl}`} />
                      </button>
                    ) : isProcessInitializing ? (
                      <div className="execution-skeleton execution-skeleton--canvas" aria-label="正在加载执行截图" />
                    ) : (
                      <div className="empty-state">等待截图产物</div>
                    )}
                  </div>
                </div>
                <div className="execution-live-side">
                  {isProcessInitializing ? (
                    <div className="execution-live-side-skeleton">
                      {Array.from({ length: 4 }, (_, index) => (
                        <div className="execution-live-panel execution-live-panel--skeleton" key={index}>
                          <span className="execution-skeleton execution-skeleton--title" />
                          <span className="execution-skeleton execution-skeleton--copy" />
                        </div>
                      ))}
                    </div>
                  ) : null}
                  <div className="execution-live-panel">
                    <strong>{detailModel.mode === "agent" ? "智能探索结果" : "AI 执行说明"}</strong>
                    {detailModel.mode === "agent" && selectedStep?.assertionChecks?.length ? (
                      <div className="execution-live-assertion">
                        {selectedStep.assertionChecks.map((check, index) => (
                          <div className="execution-live-assertion__item" key={`${selectedStep.key}-assert-${index}`}>
                            <div className="execution-live-assertion__head">
                              <strong>{check.label || `断言 ${index + 1}`}</strong>
                              <StatusPill tone={assertionTone(check.status)}>{assertionText(check.status)}</StatusPill>
                            </div>
                            <p><span>预期：</span>{check.expected}</p>
                            <p><span>实际：</span>{check.actual || "暂无实际结果"}</p>
                            <p><span>证据：</span>{check.evidenceSource || "待补充"}</p>
                            <p><span>结论：</span>{check.reason || "待校验"}</p>
                          </div>
                        ))}
                      </div>
                    ) : detailModel.mode === "agent" && selectedStep?.expectedResult ? (
                      <div className="execution-live-assertion">
                        <div className="execution-live-assertion__item">
                          <div className="execution-live-assertion__head">
                            <strong>断言结果</strong>
                            <StatusPill tone={assertionTone(selectedStep.expectedResultStatus)}>{assertionText(selectedStep.expectedResultStatus)}</StatusPill>
                          </div>
                          <p><span>预期：</span>{selectedStep.expectedResult}</p>
                          <p><span>实际：</span>{selectedStep.actualResult || "暂无实际结果"}</p>
                        </div>
                      </div>
                    ) : (
                      <p>{selectedStep?.summary || detailModel.summaryText || "暂无执行摘要"}</p>
                    )}
                  </div>
                  {detailModel.mode === "agent" && detailModel.stagePlan.length ? (
                    <div className="execution-live-panel">
                      <strong>当前阶段</strong>
                      <p>{detailModel.currentStageName || "待进入阶段"}</p>
                      <p>{detailModel.currentStrategy || "通用探索"}</p>
                    </div>
                  ) : null}
                  {detailModel.trigger === "self_heal" ? (
                    <div className="execution-live-panel">
                      <strong>自愈信息</strong>
                      <p>{detailModel.parentRunId ? `来源运行：${detailModel.parentRunId}` : "来源运行：--"}</p>
                      <p>{detailModel.healingHint || "已带入上一轮失败上下文进行重试。"}</p>
                    </div>
                  ) : null}
                  <div className="execution-live-panel">
                    <strong>最终地址</strong>
                    <p>{selectedStep?.finalUrl || detailModel.finalUrl || "--"}</p>
                  </div>
                  <div className="execution-live-panel">
                    <strong>命令输出</strong>
                    <pre>{selectedStep?.commandOutput.join("\n") || "暂无命令输出"}</pre>
                  </div>
                  {selectedStep?.errorMessage || detailModel.failureText ? (
                    <div className="execution-live-panel execution-live-panel--error">
                      <strong>错误信息</strong>
                      <p>{selectedStep?.errorMessage || detailModel.failureText}</p>
                    </div>
                  ) : null}
                  <div className="evidence-actions">
                    {canSelfHeal ? (
                      <button className="btn btn--outline" disabled={selfHealing} onClick={selfHealAgentRun} type="button">
                        {selfHealing ? "自愈中..." : "Agent 自愈"}
                      </button>
                    ) : null}
                    {detailModel.artifacts.trace_download_url ? (
                      <a className="btn btn--outline" href={`${API_ORIGIN}${detailModel.artifacts.trace_download_url}`} rel="noreferrer" target="_blank">
                        执行轨迹
                      </a>
                    ) : null}
                    {detailModel.artifacts.candidate_flow_url ? (
                      <a className="btn btn--outline" href={`${API_ORIGIN}${detailModel.artifacts.candidate_flow_url}`} rel="noreferrer" target="_blank">
                        候选脚本
                      </a>
                    ) : null}
                    {detailModel.artifacts.candidate_flow_url ? (
                      <button className="btn btn--primary" disabled={promoting || !canPromoteRegression} onClick={promoteRegression} type="button">
                        {promoting ? "沉淀中..." : "沉淀为正式回归用例"}
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>
          </Card>
          </div>
        </section>
      </div>
      <ScreenshotLightbox onClose={() => setPreviewShot(null)} screenshot={previewShot} />
    </div>
  );
}
