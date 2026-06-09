import { useEffect, useMemo, useState } from "react";
import { API_ORIGIN, api, type ApiCase, type ApiRun, type ApiRunDetail, type ApiScreenshot } from "../data/api";
import { Card } from "../components/Card";
import { ConsolePanel } from "../components/ConsolePanel";
import { FlowSteps } from "../components/FlowSteps";
import { ScreenshotLightbox } from "../components/ScreenshotLightbox";
import { StatusPill } from "../components/StatusPill";

function statusTone(status: string): "green" | "red" | "amber" | "blue" {
  if (status === "passed") return "green";
  if (status === "failed") return "red";
  if (status === "running") return "blue";
  return "amber";
}

function formatTime(value?: string | null) {
  if (!value) return "--";
  return new Date(value).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function runIdFromReportPath(path?: string | null) {
  if (!path) return "";
  return path.replace(/\\/g, "/").split("/").pop()?.replace(/\.md$/, "") || "";
}

function reportTargetFor(run: ApiRun, detail: ApiRunDetail | null) {
  if (run.mode === "run-case") return run.report_path ? run.id : "";
  const children = detail?.children ?? [];
  const failedChild = children.find((child) => child.status === "failed" && child.run_id);
  const latestChild = [...children].reverse().find((child) => child.run_id);
  return failedChild?.run_id || latestChild?.run_id || runIdFromReportPath(run.report_path);
}

export function ExecutionCenter({ onOpenReport }: { onOpenReport: (runId: string) => void }) {
  const [cases, setCases] = useState<ApiCase[]>([]);
  const [runs, setRuns] = useState<ApiRun[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [runDetail, setRunDetail] = useState<ApiRunDetail | null>(null);
  const [message, setMessage] = useState("正在连接本机执行服务...");
  const [submitting, setSubmitting] = useState(false);
  const [previewShot, setPreviewShot] = useState<ApiScreenshot | null>(null);

  const selectedRun = useMemo(
    () => runs.find((run) => run.id === selectedRunId) || runDetail?.task || null,
    [runDetail, runs, selectedRunId],
  );
  const visibleRuns = useMemo(
    () =>
      [...runs].sort((left, right) => {
        if (left.status === "failed" && right.status !== "failed") return -1;
        if (left.status !== "failed" && right.status === "failed") return 1;
        return right.created_at.localeCompare(left.created_at);
      }),
    [runs],
  );
  const activeCount = runs.filter((run) => run.summary?.is_active || run.status === "queued" || run.status === "running").length;
  const passedCount = runs.filter((run) => run.status === "passed").length;
  const failedCount = runs.filter((run) => run.status === "failed").length;
  const latestScreenshot = runDetail?.screenshots?.at(-1);
  const artifactReady = runDetail?.summary?.artifact_ready ?? Boolean(runDetail?.task?.report_path);
  const screenshotCount = runDetail?.screenshots?.length ?? 0;
  const batchChildren = runDetail?.children ?? [];
  const reportTargetRunId = selectedRun ? reportTargetFor(selectedRun, runDetail) : "";
  const liveLines = runDetail?.logs?.length
    ? runDetail.logs.map((log) => `[${formatTime(log.created_at)}] ${log.line}`)
    : ["暂无真实运行日志；创建或选择一个执行任务后这里会显示 runner 输出。"];

  async function refreshRuns() {
    try {
      const result = await api.runs();
      setRuns(result);
      const priority = result.find((item) => item.status === "failed") || result[0];
      setSelectedRunId((current) => current || priority?.id || "");
      setMessage(`已连接后端队列，共 ${result.length} 条任务`);
    } catch {
      setMessage("后端未启动，暂时无法创建或查看真实执行任务");
    }
  }

  async function loadCases() {
    try {
      const result = await api.cases();
      setCases(result);
      setSelectedCaseId((current) => (result.some((item) => item.id === current) ? current : result[0]?.id || ""));
    } catch {
      setMessage("后端未启动，无法读取 test-cases YAML 列表");
    }
  }

  async function startRun(mode: "run-case" | "run-batch") {
    if (mode === "run-case" && !selectedCaseId) {
      setMessage("请先读取到正式 case 后再执行单条用例");
      return;
    }
    setSubmitting(true);
    setMessage(mode === "run-case" ? `正在提交 ${selectedCaseId}...` : "正在提交全量批跑 001-012...");
    try {
      const task = await api.createRun(mode, mode === "run-case" ? selectedCaseId : undefined);
      setSelectedRunId(task.id);
      setRunDetail(null);
      setMessage(`已入队：${task.id}`);
      await refreshRuns();
    } catch {
      setMessage("提交失败：请确认 FastAPI 后端已启动，且当前没有环境阻塞 runner");
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    loadCases();
    refreshRuns();
    const timer = window.setInterval(refreshRuns, 5000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedRunId) return;
    let cancelled = false;

    async function loadDetail() {
      try {
        const detail = await api.runDetail(selectedRunId);
        if (!cancelled) setRunDetail(detail);
      } catch {
        if (!cancelled) setRunDetail(null);
      }
    }

    loadDetail();
    const timer = window.setInterval(loadDetail, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedRunId]);

  return (
    <div className="page">
      <FlowSteps activeIndex={5} />
      <div className="execution-grid">
        <div className="execution-left">
          <Card title="发起执行" subtitle="前台提交任务，后台 worker 调用本地 Python runner">
            <label className="field-label" htmlFor="case-select">选择用例</label>
            <select
              className="case-select"
              id="case-select"
              onChange={(event) => setSelectedCaseId(event.target.value)}
              value={selectedCaseId}
            >
              {cases.length ? (
                cases.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id} {item.title ? `- ${item.title}` : ""}
                  </option>
                ))
              ) : (
                <option value="">暂无正式 case</option>
              )}
            </select>
            <div className="button-row">
              <button className="btn btn--primary" disabled={submitting || !selectedCaseId} onClick={() => startRun("run-case")} type="button">
                执行单条
              </button>
              <button className="btn btn--green" disabled={submitting} onClick={() => startRun("run-batch")} type="button">
                跑 001-012
              </button>
            </div>
            <button className="btn btn--dark btn--wide" disabled={submitting} onClick={() => startRun("run-batch")} type="button">
              全量批跑 TC-ICM-001~012
            </button>
            <p className="muted">{message}</p>
          </Card>

          <Card className="queue-card" title="任务队列" subtitle="失败任务置顶，便于优先定位">
            <div className="queue-stats">
              <StatusPill tone="green">{passedCount} Passed</StatusPill>
              <StatusPill tone="blue">{activeCount} Active</StatusPill>
              <StatusPill tone={failedCount ? "red" : "amber"}>{failedCount} Failed</StatusPill>
            </div>
            <table className="table">
              <thead>
                <tr><th>Run ID</th><th>状态</th><th>耗时</th><th>报告</th></tr>
              </thead>
              <tbody>
                {visibleRuns.length ? (
                  visibleRuns.map((item) => {
                    const rowReportRunId = item.id === selectedRunId && runDetail ? reportTargetFor(item, runDetail) : runIdFromReportPath(item.report_path) || (item.mode === "run-case" ? item.id : "");
                    const canOpenReport = Boolean(rowReportRunId);
                    return (
                      <tr
                        className={`${item.id === selectedRunId ? "is-selected-row" : ""} ${item.status === "failed" ? "is-failed-row" : ""}`}
                        key={item.id}
                        onClick={() => setSelectedRunId(item.id)}
                      >
                        <td>{item.summary?.display_name || item.id}</td>
                        <td>{item.summary?.status_label || item.status}</td>
                        <td>{item.summary?.duration_label || "--"}</td>
                        <td>
                          <button
                            className="link-button"
                            disabled={!canOpenReport}
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelectedRunId(item.id);
                              if (rowReportRunId) {
                                onOpenReport(rowReportRunId);
                              }
                            }}
                            type="button"
                          >
                            查看
                          </button>
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr><td colSpan={4}>暂无真实任务，点击上方按钮创建第一条执行任务。</td></tr>
                )}
              </tbody>
            </table>
          </Card>
        </div>

        <div className="execution-right">
          <Card title="运行控制台" subtitle="stdout / stderr / 阶段日志实时流式展示">
            <div className="run-meta">
              <StatusPill tone={statusTone(selectedRun?.status || "queued")}>
                {selectedRun?.summary?.status_label || selectedRun?.status || "未选择"}
              </StatusPill>
              <span>{selectedRun?.id || "等待任务"}</span>
              <span>{selectedRun?.command || "python -m runner.main ..."}</span>
            </div>
            <ConsolePanel lines={liveLines} running={selectedRun?.status === "running"} />
          </Card>

          {batchChildren.length ? (
            <Card title="Batch 子 case 进度" subtitle="失败子 case 可直接点击查看对应报告">
              <div className="batch-progress">
                {batchChildren.map((child) => (
                  <button
                    className={`batch-step batch-step--${child.status}`}
                    disabled={!child.run_id}
                    key={child.case_id}
                    onClick={() => child.run_id && onOpenReport(child.run_id)}
                    type="button"
                  >
                    <span>{String(child.order).padStart(2, "0")}</span>
                    <strong>{child.case_id}</strong>
                    <StatusPill tone={statusTone(child.status)}>{child.status}</StatusPill>
                    <small>{child.screenshot_count} 张截图</small>
                  </button>
                ))}
              </div>
            </Card>
          ) : null}

          <Card className="screenshot-card" title="当前截图" subtitle="点击截图可放大查看当前证据。">
            {reportTargetRunId ? (
              <button className="report-jump" onClick={() => onOpenReport(reportTargetRunId)} type="button">
                查看报告详情
              </button>
            ) : null}
            {latestScreenshot ? (
              <button className="screenshot-real" onClick={() => setPreviewShot(latestScreenshot)} type="button">
                <img alt={latestScreenshot.filename} src={`${API_ORIGIN}${latestScreenshot.url}`} />
              </button>
            ) : (
              <div className="screenshot-stage">
                <div className="remote-tile">等待<br />截图产物</div>
              </div>
            )}
            <div className="screenshot-tags">
              <StatusPill tone="blue">{latestScreenshot?.filename || "等待截图"}</StatusPill>
              <StatusPill tone={artifactReady ? "green" : "amber"}>
                {artifactReady ? "report.md 已生成" : "等待报告"}
              </StatusPill>
              <StatusPill tone="purple">{screenshotCount} 张截图</StatusPill>
            </div>
          </Card>
        </div>
      </div>
      <ScreenshotLightbox screenshot={previewShot} onClose={() => setPreviewShot(null)} />
    </div>
  );
}
