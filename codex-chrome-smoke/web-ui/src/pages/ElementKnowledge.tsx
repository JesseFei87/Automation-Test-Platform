import { useEffect, useMemo, useState } from "react";
import { Card } from "../components/Card";
import { Modal } from "../components/Modal";
import { StatusPill } from "../components/StatusPill";
import { api, type ApiElementKnowledgeElement, type ApiElementKnowledgeEnvironment, type ApiElementKnowledgeRefreshTask, type ApiElementKnowledgeSnapshot } from "../data/api";

const ELEMENT_REFRESH_TASK_STORAGE_KEY = "qa-platform.element-knowledge.current-refresh-task-id";
const ACTIVE_TASK_STATUSES = new Set(["queued", "running"]);

const EMPTY_SNAPSHOT: ApiElementKnowledgeSnapshot = {
  summary: {
    page_count: 0,
    element_count: 0,
    feedback_record_count: 0,
    feedback_stat_count: 0,
    healing_suggestion_count: 0,
    elements_with_feedback: 0,
    elements_with_healing: 0,
  },
  elements: [],
  hotspots: [],
  report_paths: {},
  source_paths: {},
  exists: { library: false, summary: false },
};

type RiskFilter = "all" | "low" | "medium" | "high";
type HealingFilter = "all" | "with-healing" | "without-healing";
type BrowserScanTargetMode = "environment" | "single-target";
type ElementViewMode = "list" | "tree";

type DisplayElement = ApiElementKnowledgeElement & {
  duplicate_count: number;
  states: string[];
  source_element_ids: string[];
  source_records: ApiElementKnowledgeElement[];
};

function rateLabel(value: unknown) {
  if (typeof value !== "number") return "-";
  return `${Math.round(value * 100)}%`;
}

function textOf(value: unknown) {
  if (Array.isArray(value)) return value.join(" / ");
  return String(value ?? "");
}

function matchesSearch(item: ApiElementKnowledgeElement, query: string) {
  if (!query.trim()) return true;
  const q = query.trim().toLowerCase();
  return [
    item.element_id,
    item.page_id,
    item.name,
    item.human_en,
    item.human_zh?.join(" "),
    item.text,
    item.placeholder,
    item.healing_issue,
    item.healing_suggestion,
    item.last_error,
    item.selectors?.join(" "),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .includes(q);
}

function filterElements(elements: ApiElementKnowledgeElement[], query: string, risk: RiskFilter, healing: HealingFilter) {
  return elements.filter((item) => {
    if (!matchesSearch(item, query)) return false;
    if (risk !== "all" && (item.risk_level || "low") !== risk) return false;
    const hasHealing = Boolean(item.healing_issue || item.healing_suggestion);
    if (healing === "with-healing" && !hasHealing) return false;
    if (healing === "without-healing" && hasHealing) return false;
    return true;
  });
}

function elementIdentity(item: ApiElementKnowledgeElement) {
  const selectors = (item.selectors || []).map((value) => value.trim().toLowerCase()).filter(Boolean).sort().join("|");
  const actions = (item.actions || []).map((value) => value.trim().toLowerCase()).filter(Boolean).sort().join("|");
  const fallback = [item.tag, item.role, item.type, item.text, item.placeholder].map((value) => String(value || "").trim().toLowerCase()).join("|");
  return [item.page_id || "unknown", selectors || fallback, actions].join("::");
}

function riskWeight(value?: string) {
  return ({ low: 1, medium: 2, high: 3 } as Record<string, number>)[value || "low"] || 0;
}

function dedupeElements(elements: ApiElementKnowledgeElement[]): DisplayElement[] {
  const groups = new Map<string, ApiElementKnowledgeElement[]>();
  for (const item of elements) {
    const key = elementIdentity(item);
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  return [...groups.values()].map((records) => {
    const representative = [...records].sort((left, right) => {
      const stateOrder = (value?: string) => value === "default" ? 0 : 1;
      return stateOrder(left.state) - stateOrder(right.state) || riskWeight(right.risk_level) - riskWeight(left.risk_level);
    })[0];
    const highestRisk = records.reduce((current, item) => riskWeight(item.risk_level) > riskWeight(current) ? item.risk_level || "low" : current, representative.risk_level || "low");
    return {
      ...representative,
      risk_level: highestRisk,
      duplicate_count: records.length,
      states: [...new Set(records.flatMap((item) => item.states?.length ? item.states : [item.state || "default"]))],
      source_element_ids: records.map((item) => item.element_id || item.name || "unknown"),
      source_records: records,
    };
  }).sort((left, right) => (left.page_id || "").localeCompare(right.page_id || "") || (left.element_id || left.name || "").localeCompare(right.element_id || right.name || ""));
}

function groupElementsByPage(elements: DisplayElement[]) {
  const pages = new Map<string, DisplayElement[]>();
  for (const item of elements) {
    const pageId = item.page_id || "unknown";
    pages.set(pageId, [...(pages.get(pageId) || []), item]);
  }
  return [...pages.entries()].map(([pageId, items]) => ({ pageId, items }));
}

function formatStage(stage?: string) {
  const map: Record<string, string> = {
    refresh_started: "刷新开始",
    loading_existing_library: "读取已有知识库",
    launching_browser: "启动浏览器",
    browser_launched: "浏览器已启动",
    explicit_target_loaded: "已加载指定扫描页面",
    scanning_page: "正在扫描页面",
    page_scanned: "页面扫描完成",
    page_failed: "页面扫描失败",
    library_built: "生成元素库",
    merging_feedback_and_healing: "合并反馈与 Healing",
    closing_browser: "关闭浏览器",
    refresh_completed: "刷新完成",
  };
  return stage ? map[stage] || stage : "-";
}

function formatDuration(ms?: number) {
  if (typeof ms !== "number") return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatDateTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  const datePart = [date.getFullYear(), pad(date.getMonth() + 1), pad(date.getDate())].join("-");
  return `${datePart} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function refreshPageProgress(task: ApiElementKnowledgeRefreshTask, snapshotPageCount: number) {
  const progress = task.progress || {};
  const fallbackPageCount = task.snapshot?.summary?.page_count || snapshotPageCount || 0;
  const total = progress.page_total || fallbackPageCount;
  const current = progress.page_index || progress.scanned_page_count || (task.status === "done" || task.status === "passed" ? fallbackPageCount : 0);
  return { current, total };
}

function targetMetadataFromUrl(value: string) {
  try {
    const url = new URL(value.trim());
    const route = (url.hash ? url.hash.slice(1).split("?")[0] : url.pathname).replace(/^\/+/, "");
    const pageId = route
      .split("/")
      .filter(Boolean)
      .join("-")
      .replace(/[^a-zA-Z0-9_\-\u4e00-\u9fff]/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "") || "page";
    return { pageId, name: pageId === "login" ? "登录页" : route ? `页面：${route}` : url.hostname };
  } catch {
    return { pageId: "page", name: "目标页面" };
  }
}

function ElementRow({ item, onViewDetails }: { item: DisplayElement; onViewDetails: (item: DisplayElement) => void }) {
  const risk = item.risk_level || "low";
  const riskKind = risk === "high" ? "red" : risk === "medium" ? "amber" : "green";
  return (
    <tr>
      <td>
        <strong>{item.element_id || item.name || "unknown"}</strong>
        <small>{item.page_id || "-"} / {item.states.join(" · ")}{item.duplicate_count > 1 ? ` / merged ${item.duplicate_count}` : ""}</small>
      </td>
      <td>{textOf(item.human_zh) || item.human_en || item.text || item.placeholder || "-"}</td>
      <td><StatusPill tone={riskKind}>{risk}</StatusPill></td>
      <td>{item.actions?.join(" / ") || "-"}</td>
      <td>{item.execution_count ?? 0}</td>
      <td>{item.failed_count ?? 0}</td>
      <td>{rateLabel(item.success_rate)}</td>
      <td>
        {item.healing_issue ? <strong>{item.healing_issue}</strong> : <span className="muted">无</span>}
        {item.healing_suggestion ? <small>{item.healing_suggestion}</small> : null}
      </td>
      <td><button type="button" className="element-knowledge-detail-button" onClick={() => onViewDetails(item)}>详情 JSON</button></td>
    </tr>
  );
}

function HotspotCard({ item }: { item: ApiElementKnowledgeElement }) {
  return (
    <article className="element-knowledge-hotspot">
      <div>
        <strong>{item.element_id || item.name || "unknown"}</strong>
        <span>{item.page_id || "-"} / failed {item.failed_count ?? 0} / success {rateLabel(item.success_rate)}</span>
      </div>
      {item.healing_issue ? <StatusPill tone="amber">{item.healing_issue}</StatusPill> : null}
      <p>{item.healing_suggestion || item.last_error || "暂无建议"}</p>
    </article>
  );
}

export function ElementKnowledge() {
  const [snapshot, setSnapshot] = useState<ApiElementKnowledgeSnapshot>(EMPTY_SNAPSHOT);
  const [query, setQuery] = useState("");
  const [risk, setRisk] = useState<RiskFilter>("all");
  const [healing, setHealing] = useState<HealingFilter>("all");
  const [status, setStatus] = useState("正在读取元素知识库...");
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshTask, setRefreshTask] = useState<ApiElementKnowledgeRefreshTask | null>(null);
  const [browserScanTargetMode, setBrowserScanTargetMode] = useState<BrowserScanTargetMode>("single-target");
  const [environments, setEnvironments] = useState<ApiElementKnowledgeEnvironment[]>([]);
  const [environmentId, setEnvironmentId] = useState("");
  const [baseUrl, setBaseUrl] = useState("http://localhost:5173");
  const [targetUrl, setTargetUrl] = useState("https://192.168.16.203:49187/#/login");
  const [includeStates, setIncludeStates] = useState(true);
  const [headless, setHeadless] = useState(true);
  const [elementViewMode, setElementViewMode] = useState<ElementViewMode>("list");
  const [selectedElement, setSelectedElement] = useState<DisplayElement | null>(null);

  useEffect(() => {
    void loadKnowledge();
    void loadEnvironments();
    void restoreRefreshTask();
  }, []);

  useEffect(() => {
    if (!refreshTask?.id || !ACTIVE_TASK_STATUSES.has(refreshTask.status)) return;
    const timer = window.setTimeout(() => {
      void pollRefreshTask(refreshTask.id);
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [refreshTask?.id, refreshTask?.status]);

  useEffect(() => {
    const resume = () => {
      if (document.visibilityState === "visible") void restoreRefreshTask();
    };
    window.addEventListener("focus", restoreRefreshTask);
    document.addEventListener("visibilitychange", resume);
    return () => {
      window.removeEventListener("focus", restoreRefreshTask);
      document.removeEventListener("visibilitychange", resume);
    };
  }, []);

  async function loadEnvironments() {
    try {
      const result = (await api.elementKnowledgeEnvironments()).filter((environment) => environment.element_knowledge_scan_enabled && (environment.pages?.length || 0) > 0);
      setEnvironments(result);
      const selected = result.find((environment) => environment.id === environmentId) || result[0];
      if (selected?.id) {
        setEnvironmentId(selected.id);
        if (selected.base_url) setBaseUrl(selected.base_url);
        if (typeof selected.headless === "boolean") setHeadless(selected.headless);
      } else {
        setEnvironmentId("");
      }
    } catch {
      setEnvironments([]);
    }
  }

  async function loadKnowledge() {
    setLoading(true);
    try {
      const result = await api.elementKnowledge();
      setSnapshot(result);
      setStatus("元素知识库已加载");
    } catch (error) {
      setStatus(`读取失败：${error instanceof Error ? error.message : "unknown error"}`);
      setSnapshot(EMPTY_SNAPSHOT);
    } finally {
      setLoading(false);
    }
  }

  function applyRefreshTask(task: ApiElementKnowledgeRefreshTask) {
    const isValidation = task.mode === "element-knowledge-validation";
    setRefreshTask(task);
    if (task.id) window.localStorage.setItem(ELEMENT_REFRESH_TASK_STORAGE_KEY, task.id);
    if (ACTIVE_TASK_STATUSES.has(task.status)) {
      setRefreshing(true);
      setStatus(task.status === "queued" ? `${isValidation ? "校验" : "刷新"}任务已排队` : `${isValidation ? "校验" : "刷新"}任务运行中`);
      return;
    }
    setRefreshing(false);
    if (task.status === "done" || task.status === "passed") {
      if (task.snapshot) setSnapshot(task.snapshot);
      setStatus(isValidation ? "元素知识库校验完成" : "元素知识库刷新完成");
      return;
    }
    if (task.status === "failed") {
      setStatus(`${isValidation ? "校验" : "刷新"}失败：${task.error || "unknown error"}`);
      return;
    }
    setStatus(`刷新任务状态：${task.status}`);
  }

  async function pollRefreshTask(taskId: string) {
    try {
      const task = await api.elementKnowledgeRefreshTask(taskId);
      applyRefreshTask(task);
    } catch (error) {
      setRefreshing(false);
      setStatus(`刷新任务查询失败：${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  async function restoreRefreshTask() {
    try {
      const storedTaskId = window.localStorage.getItem(ELEMENT_REFRESH_TASK_STORAGE_KEY);
      if (storedTaskId) {
        const task = await api.elementKnowledgeRefreshTask(storedTaskId);
        applyRefreshTask(task);
        return;
      }
      const tasks = await api.elementKnowledgeRefreshTasks();
      const latestTask = tasks.find((item) => ACTIVE_TASK_STATUSES.has(item.status)) || tasks[0];
      if (latestTask?.id) applyRefreshTask(await api.elementKnowledgeRefreshTask(latestTask.id));
    } catch {
      // Restore failure should not block the main library snapshot.
    }
  }

  function chooseEnvironment(id: string) {
    setEnvironmentId(id);
    const env = environments.find((item) => item.id === id);
    if (env?.base_url) setBaseUrl(env.base_url);
    if (typeof env?.headless === "boolean") setHeadless(env.headless);
  }

  async function refreshKnowledge(scan: boolean) {
    const isSingleTargetScan = scan && browserScanTargetMode === "single-target";
    if (isSingleTargetScan && !targetUrl.trim()) {
      setStatus("刷新失败：指定页面扫描必须填写 target_url");
      return;
    }
    if (scan && browserScanTargetMode === "environment" && !environmentId && !baseUrl.trim()) {
      setStatus("刷新失败：环境页面清单扫描必须选择环境或填写 base_url");
      return;
    }
    setRefreshing(true);
    setStatus(scan ? "正在创建重新扫描任务..." : "正在创建反馈更新任务...");
    try {
      const targetMetadata = targetMetadataFromUrl(targetUrl);
      const task = await api.refreshElementKnowledge({
        no_scan: !scan,
        min_healing_failures: 1,
        base_url: scan && browserScanTargetMode === "environment" && !environmentId ? baseUrl.trim() : undefined,
        environment_id: scan && browserScanTargetMode === "environment" && environmentId ? environmentId : undefined,
        target_url: isSingleTargetScan ? targetUrl.trim() : undefined,
        target_page_id: isSingleTargetScan ? targetMetadata.pageId : undefined,
        target_name: isSingleTargetScan ? targetMetadata.name : undefined,
        include_states: scan ? includeStates : false,
        headless,
      });
      applyRefreshTask(task);
    } catch (error) {
      setStatus(`刷新失败：${error instanceof Error ? error.message : "unknown error"}`);
      setRefreshing(false);
    }
  }

  async function validateKnowledge() {
    if (!environmentId) {
      setStatus("校验失败：请选择 CDP 环境");
      return;
    }
    setRefreshing(true);
    setStatus("正在创建只读校验任务...");
    try {
      applyRefreshTask(await api.validateElementKnowledge(environmentId));
    } catch (error) {
      setStatus(`校验失败：${error instanceof Error ? error.message : "unknown error"}`);
      setRefreshing(false);
    }
  }

  const uniqueElements = useMemo(() => dedupeElements(snapshot.elements), [snapshot.elements]);
  const filtered = useMemo(() => filterElements(uniqueElements, query, risk, healing) as DisplayElement[], [uniqueElements, query, risk, healing]);
  const pageGroups = useMemo(() => groupElementsByPage(filtered), [filtered]);
  const summary = snapshot.summary || EMPTY_SNAPSHOT.summary;
  const taskPageProgress = refreshTask ? refreshPageProgress(refreshTask, summary.page_count) : { current: 0, total: 0 };
  const headlessManagedByEnvironment = browserScanTargetMode === "environment" && Boolean(environmentId);

  return (
    <section className="element-knowledge-page element-knowledge-console">
      <div className="page-heading element-knowledge-heading element-knowledge-heading--console">
        <div>
          <p className="eyebrow">AI Element Knowledge</p>
          <h1>元素知识库管理</h1>
          <p>查看页面元素、执行反馈、失败热点和 Self-Healing 建议。</p>
        </div>
        <div className="element-knowledge-actions">
          <button type="button" className="btn-secondary" onClick={loadKnowledge} disabled={loading || refreshing}>重新加载</button>
          <button type="button" className="btn-secondary" onClick={validateKnowledge} disabled={refreshing || !environmentId}>校验元素库</button>
          <button type="button" className="btn-secondary" onClick={() => void refreshKnowledge(false)} disabled={refreshing}>仅更新反馈</button>
          <button type="button" className="btn-primary" onClick={() => void refreshKnowledge(true)} disabled={refreshing}>{refreshing ? "刷新中..." : "扫描元素库"}</button>
        </div>
      </div>

      <div className="element-knowledge-status element-knowledge-status--console" role="status" aria-live="polite">
        <StatusPill tone={status.includes("失败") ? "red" : refreshing ? "amber" : "blue"}>{status}</StatusPill>
        <span>最近刷新：{formatDateTime(summary.refreshed_at)}</span>
        {refreshTask ? <span>任务：{refreshTask.id} / {refreshTask.status}</span> : null}
        {refreshTask?.id ? <button type="button" className="btn-secondary" onClick={() => void pollRefreshTask(refreshTask.id)} disabled={loading}>刷新任务状态</button> : null}
      </div>

      <Card title="扫描设置" subtitle="选择要访问的页面和扫描选项。仅更新反馈不会使用这里的设置。">
        <div className="element-knowledge-refresh-settings element-knowledge-refresh-settings--panel">
          <label className="element-knowledge-setting-field element-knowledge-setting-field--scope">
            <span>扫描范围</span>
            <select value={browserScanTargetMode} onChange={(event) => setBrowserScanTargetMode(event.target.value as BrowserScanTargetMode)}>
              <option value="single-target">只扫描一个页面</option>
              <option value="environment">扫描环境中的全部页面</option>
            </select>
          </label>
          {browserScanTargetMode === "environment" ? (
            <>
              <label className="element-knowledge-setting-field">
                <span>选择环境</span>
                <select value={environmentId} onChange={(event) => chooseEnvironment(event.target.value)}>
                  <option value="">手动填写系统地址</option>
                  {environments.map((env) => <option key={env.id} value={env.id}>{env.name || env.id}</option>)}
                </select>
              </label>
              <label className="element-knowledge-setting-field element-knowledge-setting-field--address">
                <span>系统地址</span>
                <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} disabled={Boolean(environmentId)} placeholder="例如 http://localhost:5173" />
              </label>
            </>
          ) : (
            <>
              <label className="element-knowledge-setting-field element-knowledge-setting-field--wide">
                <span>页面地址</span>
                <input value={targetUrl} onChange={(event) => setTargetUrl(event.target.value)} placeholder="例如 https://host/#/login" />
              </label>
            </>
          )}
          <div className="element-knowledge-inline-options">
            <label><input type="checkbox" checked={includeStates} onChange={(event) => setIncludeStates(event.target.checked)} /> 记录展开菜单和弹窗</label>
            <label className={headlessManagedByEnvironment ? "is-managed" : ""}>
              <input type="checkbox" checked={headless} onChange={(event) => setHeadless(event.target.checked)} disabled={headlessManagedByEnvironment} /> 后台运行
              {headlessManagedByEnvironment ? <small>由环境配置控制</small> : null}
            </label>
          </div>
        </div>
      </Card>

      {refreshTask ? (
        <Card title="刷新任务详情" subtitle="后台任务状态、进度、日志和报告路径。">
          <div className="element-knowledge-task-progress element-knowledge-task-progress--console">
            <div><span>阶段</span><strong>{formatStage(refreshTask.progress?.stage)}</strong></div>
            <div><span>当前页面</span><strong>{refreshTask.progress?.current_page || "-"}</strong></div>
            <div><span>页面进度</span><strong>{taskPageProgress.current}/{taskPageProgress.total}</strong></div>
            <div><span>元素数</span><strong>{refreshTask.progress?.element_count ?? refreshTask.progress?.library_element_count ?? 0}</strong></div>
            <div><span>高风险</span><strong>{refreshTask.progress?.high_risk_count ?? 0}</strong></div>
            <div><span>耗时</span><strong>{formatDuration(refreshTask.progress?.duration_ms)}</strong></div>
          </div>
          <div className="element-knowledge-task element-knowledge-task--console">
            <dl className="element-knowledge-paths">
              <dt>状态</dt><dd>{refreshTask.status}</dd>
              <dt>进度更新时间</dt><dd>{formatDateTime(refreshTask.progress?.updated_at)}</dd>
              <dt>创建</dt><dd>{formatDateTime(refreshTask.created_at)}</dd>
              <dt>开始</dt><dd>{formatDateTime(refreshTask.started_at)}</dd>
              <dt>完成</dt><dd>{formatDateTime(refreshTask.finished_at)}</dd>
              <dt>报告</dt><dd>{refreshTask.report_path || refreshTask.progress?.report_path || "-"}</dd>
              <dt>错误</dt><dd>{refreshTask.error || refreshTask.progress?.error || "-"}</dd>
            </dl>
            <div className="element-knowledge-task-log">
              {(refreshTask.logs || []).length ? <p><span>日志</span>显示最近 {Math.min((refreshTask.logs || []).length, 80)} / {(refreshTask.logs || []).length} 条</p> : null}
              {(refreshTask.logs || []).slice(-80).map((log, index) => (
                <p key={`${log.id || index}-${log.created_at || ""}`}><span>{formatDateTime(log.created_at)}</span>{log.line}</p>
              ))}
              {!(refreshTask.logs || []).length ? <p><span>-</span>暂无日志</p> : null}
            </div>
          </div>
        </Card>
      ) : null}

      <div className="element-knowledge-metrics element-knowledge-metrics--console">
        <Card><span>元素总数</span><strong>{summary.element_count}</strong></Card>
        <Card><span>页面数</span><strong>{summary.page_count}</strong></Card>
        <Card><span>反馈记录</span><strong>{summary.feedback_record_count}</strong></Card>
        <Card><span>Healing 建议</span><strong>{summary.healing_suggestion_count}</strong></Card>
      </div>

      <div className="element-knowledge-grid element-knowledge-grid--console">
        <Card title="失败热点" subtitle="优先展示失败次数高、有 healing 建议的元素。">
          <div className="element-knowledge-hotspots">
            {snapshot.hotspots.length ? snapshot.hotspots.slice(0, 6).map((item) => <HotspotCard key={item.element_id || item.name} item={item} />) : <p className="muted">暂无失败热点。</p>}
          </div>
        </Card>
        <Card title="报告与数据源" subtitle="P9 静态报告和当前数据文件路径。">
          <dl className="element-knowledge-paths">
            <dt>library</dt><dd>{snapshot.source_paths.library || "-"}</dd>
            <dt>summary</dt><dd>{snapshot.source_paths.summary || "-"}</dd>
            <dt>Markdown 报告</dt><dd>{snapshot.report_paths.markdown || "-"}</dd>
            <dt>HTML 报告</dt><dd>{snapshot.report_paths.html || "-"}</dd>
          </dl>
        </Card>
      </div>

      <Card title="元素列表" subtitle="支持按元素名、页面、文本、selector、错误和 healing 建议搜索。">
        <div className="element-knowledge-toolbar element-knowledge-toolbar--console">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 element_id / 页面 / 文案 / selector / 错误" />
          <select value={risk} onChange={(event) => setRisk(event.target.value as RiskFilter)}>
            <option value="all">全部风险</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
          </select>
          <select value={healing} onChange={(event) => setHealing(event.target.value as HealingFilter)}>
            <option value="all">全部 Healing</option>
            <option value="with-healing">有建议</option>
            <option value="without-healing">无建议</option>
          </select>
          <div className="element-knowledge-view-toggle" role="group" aria-label="元素展示方式">
            <button type="button" className={elementViewMode === "list" ? "is-active" : ""} onClick={() => setElementViewMode("list")}>列表</button>
            <button type="button" className={elementViewMode === "tree" ? "is-active" : ""} onClick={() => setElementViewMode("tree")}>页面树</button>
          </div>
          <span>{filtered.length} / {uniqueElements.length}（原始 {snapshot.elements.length}）</span>
        </div>
        {elementViewMode === "list" ? (
        <div className="element-knowledge-table-wrap element-knowledge-table-wrap--console">
          <table className="element-knowledge-table">
            <thead>
              <tr>
                <th>元素</th>
                <th>语义</th>
                <th>风险</th>
                <th>动作</th>
                <th>执行</th>
                <th>失败</th>
                <th>成功率</th>
                <th>Healing</th>
                <th>详情</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 200).map((item) => <ElementRow key={elementIdentity(item)} item={item} onViewDetails={setSelectedElement} />)}
              {!filtered.length ? <tr><td colSpan={8}>暂无匹配元素。</td></tr> : null}
            </tbody>
          </table>
        </div>
        ) : (
          <div className="element-knowledge-tree" role="tree" aria-label="按页面归类的元素树">
            {pageGroups.map(({ pageId, items }) => (
              <details key={pageId} className="element-knowledge-tree-page" open>
                <summary><strong>{pageId}</strong><span>{items.length} 个元素</span></summary>
                <div className="element-knowledge-tree-children" role="group">
                  {items.map((item) => (
                    <div key={elementIdentity(item)} className="element-knowledge-tree-item" role="treeitem">
                      <div>
                        <strong>{item.element_id || item.name || "unknown"}</strong>
                        <small>{textOf(item.human_zh) || item.human_en || item.text || item.placeholder || "-"} / {item.states.join(" · ")}</small>
                      </div>
                      <div className="element-knowledge-tree-item-actions">
                        <StatusPill tone={item.risk_level === "high" ? "red" : item.risk_level === "medium" ? "amber" : "green"}>{item.risk_level || "low"}</StatusPill>
                        <button type="button" className="element-knowledge-detail-button" onClick={() => setSelectedElement(item)}>详情 JSON</button>
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            ))}
            {!pageGroups.length ? <p className="muted">暂无匹配元素。</p> : null}
          </div>
        )}
      </Card>
      <Modal open={Boolean(selectedElement)} onClose={() => setSelectedElement(null)} title="元素详情 JSON" size="lg">
        <pre className="element-knowledge-json-detail">{selectedElement ? JSON.stringify({
          ...selectedElement,
          deduplication: {
            key: elementIdentity(selectedElement),
            merged_record_count: selectedElement.duplicate_count,
            states: selectedElement.states,
            source_element_ids: selectedElement.source_element_ids,
          },
        }, null, 2) : ""}</pre>
      </Modal>
    </section>
  );
}
