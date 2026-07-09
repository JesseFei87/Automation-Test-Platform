import type { PageId } from "../types";

const browserHost = typeof window === "undefined" ? "127.0.0.1" : window.location.hostname || "127.0.0.1";
export const API_ORIGIN = `http://${browserHost}:8000`;
const API_BASE = `${API_ORIGIN}/api`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    throw new Error(readError(await response.text()));
  }
  return response.json() as Promise<T>;
}

async function requestBlob(path: string, init?: RequestInit): Promise<{ blob: Blob; filename: string | null; contentType: string }> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    throw new Error(readError(await response.text()));
  }
  const disposition = response.headers.get("content-disposition") || "";
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const basicMatch = /filename="?([^\";]+)"?/i.exec(disposition);
  const filename = utf8Match?.[1] ? decodeURIComponent(utf8Match[1]) : basicMatch?.[1] ?? null;
  return {
    blob: await response.blob(),
    filename,
    contentType: response.headers.get("content-type") || "application/octet-stream",
  };
}

function readError(text: string) {
  try {
    const data = JSON.parse(text) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (data.detail) return JSON.stringify(data.detail);
    return text;
  } catch {
    return text;
  }
}

export type ApiCase = {
  id: string;
  title: string;
  status: string;
  path: string;
  has_automation_asset: boolean;
};

export type ApiCaseDetail = ApiCase & {
  yaml: string;
};

export type AISettings = {
  provider: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
  api_key_masked: string;
  updated_at?: string | null;
};

export type PlatformSettings = {
  runner: {
    browser_mode: string;
    queue_mode: string;
    batch_range: string;
    screenshot_policy: string;
    headless: boolean;
  };
  asset_policy: {
    observed_asset_enabled: boolean;
    allow_passed_run_merge: boolean;
    merge_strategy: string;
    require_verified_before_regression: boolean;
  };
  environment: {
    icm_base_url: string;
    icm_login_url: string;
    dev_portal_base_url: string;
    dev_login_url: string;
    remote_help_url: string;
  };
  accounts: Record<
    "labo" | "jesse" | "tester" | "admin",
    {
      username: string;
      has_password?: boolean;
      password_masked?: string;
      password?: string;
    }
  >;
  updated_at?: string | null;
};

export type SystemHealth = {
  api: { status: string; version: string };
  runner: { status: string; entry: string; path: string };
  playwright: { available: boolean; chrome_available: boolean; chrome_path: string };
  paths: Record<string, { path: string; exists: boolean; is_dir: boolean; updated_at?: string | null }>;
  sqlite: { path: string; exists: boolean; size_bytes: number; updated_at?: string | null };
};

export type OllamaModel = {
  name: string;
  model: string;
  modified_at?: string | null;
  size?: number | null;
  digest?: string | null;
  details?: {
    family?: string;
    parameter_size?: string;
    quantization_level?: string;
    [key: string]: unknown;
  };
};

export type Requirement = {
  id: number;
  title: string;
  document: string;
  status: string;
  project_id?: string | null;
  analysis_summary?: string | null;
  risk_summary?: string | null;
  case_count?: number | null;
  created_at: string;
  updated_at: string;
  test_point_count?: number;
  draft_count?: number;
};

export type TestPoint = {
  id: number;
  requirement_id: number;
  parent_id?: number | null;
  requirement_title?: string | null;
  name: string;
  category: string;
  priority: string;
  status: string;
  description?: string | null;
  module?: string | null;
  source?: string | null;
  sort_order?: number | null;
  created_at: string;
  updated_at?: string | null;
};

export type CaseDraft = {
  id: number;
  requirement_id: number;
  requirement_title?: string | null;
  title: string;
  yaml: string;
  status: string;
  template?: string | null;
  source_test_point_ids?: number[];
  promoted_case_id?: string | null;
  promoted_path?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type CaseDraftDeleteResult = {
  ok: boolean;
  draft_id: number;
  promoted_case_id?: string | null;
  deleted_files: number;
  deleted_rows: number;
};

export type CaseDraftBatchDeleteResult = {
  deleted: number;
  failed: number;
  results: Array<CaseDraftDeleteResult | { ok: false; draft_id: number; error: string }>;
};

export type CaseDraftValidation = {
  draft_id: number;
  valid: boolean;
  errors: string[];
  warnings: string[];
  parsed_id?: string | null;
};

export type RequirementDetail = {
  requirement: Requirement;
  test_points: TestPoint[];
  drafts: CaseDraft[];
  provider?: string;
};

export type ApiRunSummary = {
  display_name: string;
  status_label: string;
  is_active: boolean;
  artifact_ready: boolean;
  duration_seconds: number | null;
  duration_label: string;
};

export type ApiRun = {
  id: string;
  mode: "run-case" | "run-batch" | "run-draft" | "agent-explore";
  case_id: string | null;
  parent_run_id?: string | null;
  trigger?: "manual" | "self_heal" | string | null;
  healing_context_path?: string | null;
  status: string;
  command: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  report_path?: string | null;
  error?: string | null;
  summary?: ApiRunSummary;
};

export type ApiScreenshot = {
  case_id: string;
  filename: string;
  path: string;
  url: string;
};

export type ApiBatchChild = {
  order: number;
  case_id: string;
  case_name: string;
  run_id: string | null;
  status: string;
  report_path: string | null;
  screenshot_count: number;
  updated_at: number | null;
};

export type ApiEvidenceSummary = {
  run_id: string;
  root: string;
  trace: { exists: boolean; path: string; url: string };
  events: { exists: boolean; path: string; count: number; latest: Array<Record<string, unknown>> };
  console: { exists: boolean; path: string; count: number; latest: Array<Record<string, unknown>> };
  network: { exists: boolean; path: string; count: number; latest: Array<Record<string, unknown>> };
  dom: { count: number; files: Array<{ filename: string; path: string; url: string }> };
};

export type ApiAgentExploreDetail = {
  trace_path: string;
  candidate_flow_path: string;
  trace: {
    ok?: boolean;
    status?: string;
    run_id?: string;
    case_id?: string;
    case_arg?: string;
    finalUrl?: string;
    final_url?: string;
    summary?: string;
    error?: string;
    history?: Array<Record<string, unknown>>;
    evidence?: ApiEvidenceSummary;
    [key: string]: unknown;
  };
};

export type ApiRunDetail = {
  task: ApiRun;
  summary: ApiRunSummary;
  logs: Array<{ id: number; run_id: string; stream: string; line: string; created_at: string }>;
  children: ApiBatchChild[];
  report: string;
  screenshots: ApiScreenshot[];
  evidence?: ApiEvidenceSummary;
  agent_explore?: ApiAgentExploreDetail | null;
  analysis: null | {
    provider: string;
    model?: string;
    source?: string;
    cached?: boolean;
    cached_at?: string;
    status: string;
    conclusion: string;
    risks: string[];
    retest_suggestions: string[];
    screenshot_count: number;
    log_count: number;
  };
};

export type ApiReport = {
  run_id: string;
  case_id: string;
  case_name: string;
  status: string;
  path: string;
  updated_at: number;
  screenshot_count: number;
};

export type ApiStructuredStep = {
  step_index: number;
  step_code: string;
  title: string;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_seconds?: number | null;
  summary?: string;
  error_message?: string;
  screenshot_url?: string;
  ai_analysis?: string;
  final_url?: string;
  command_output?: string[];
  selectors?: string[];
  inputs?: Array<{ name?: string; value?: string }>;
  console_logs?: Array<Record<string, unknown>>;
  network_logs?: Array<Record<string, unknown>>;
  dom_snapshot_url?: string;
  events?: Array<Record<string, unknown>>;
  expected_result?: string;
  expected_result_status?: string;
  actual_result?: string;
  assertion_checks?: Array<{
    type: string;
    label?: string;
    expected: string;
    actual?: string;
    status: string;
    evidence_source?: string;
    reason?: string;
    field?: string;
    terms?: string[];
  }>;
};

export type ApiRunDetailView = {
  run_id: string;
  case_id?: string | null;
  case_name: string;
  mode: "worker" | "agent";
  trigger?: "manual" | "self_heal" | string;
  parent_run_id?: string | null;
  status: string;
  operator?: string;
  started_at?: string | null;
  finished_at?: string | null;
  duration_seconds?: number | null;
  final_url?: string;
  summary?: {
    title?: string;
    conclusion?: string;
    failure_reason?: string;
    ai_analysis?: string;
  };
  steps: ApiStructuredStep[];
  artifacts: {
    report_markdown_url?: string;
    observed_asset_path?: string;
    observed_asset_merge_url?: string;
    trace_download_url?: string;
    candidate_flow_url?: string;
  };
  raw_report?: string;
  logs?: Array<{ id: number; run_id: string; stream: string; line: string; created_at: string }>;
  screenshots?: ApiScreenshot[];
  evidence?: ApiEvidenceSummary;
  agent_explore?: ApiAgentExploreDetail | null;
  analysis?: ApiRunDetail["analysis"];
  healing_hint?: string;
  agent_plan?: {
    planner_version?: string;
    case_id?: string;
    stages?: Array<{
      stage_id: string;
      index: number;
      name: string;
      scene_type: string;
      target_route?: string;
      strategy: string;
      fallback?: string;
    }>;
  };
  agent_stage_runs?: Array<{
    stage_id: string;
    index?: number;
    name: string;
    scene_type: string;
    scene_label?: string;
    strategy: string;
    strategy_label?: string;
    fallback_used: boolean;
    status: string;
    started_at?: string | null;
    finished_at?: string | null;
    error?: string;
    target_route?: string;
  }>;
  current_stage_id?: string;
  current_stage_name?: string;
  current_strategy?: string;
};

export type ApiReportListItem = {
  id: string;
  run_id: string;
  case_id?: string | null;
  case_name: string;
  mode: "worker" | "agent";
  status: string;
  operator?: string;
  started_at?: string | null;
  finished_at?: string | null;
  has_report: boolean;
  has_evidence: boolean;
};

export type ApiReportDeleteResult = {
  ok: boolean;
  run_id: string;
  deleted_at: string;
  mode: "worker" | "agent";
};

export type ApiReportBatchDeleteResult = {
  ok: boolean;
  deleted_count: number;
  run_ids: string[];
  deleted_at: string;
};

export type ApiReportAnalysis = NonNullable<ApiRunDetail["analysis"]>;

export type ApiReportAnalysisVersion = {
  id: number;
  run_id: string;
  provider: string;
  model: string;
  created_at: string;
  analysis: ApiReportAnalysis;
};

export type ApiObservedAsset = {
  status?: string;
  source?: string;
  observed_at?: string;
  evidence?: {
    run_id?: string;
    report_path?: string;
    screenshots?: string[];
    [key: string]: unknown;
  };
  operation_steps?: string[];
  selectors?: Record<string, string[]> | string[];
  input_values?: Record<string, string>;
  assertions?: string[];
};

export type ApiObservedAssetDiffResponse = {
  case_id: string;
  run_id: string;
  diff: {
    kept: {
      operation_steps?: string[];
      selectors?: Record<string, string[]> | string[];
      input_values?: Record<string, string>;
      assertions?: string[];
    };
    added: {
      operation_steps?: string[];
      selectors?: Record<string, string[]> | string[];
      input_values?: Record<string, string>;
      assertions?: string[];
    };
    missing: string[];
  };
  observed_at?: string | null;
};

export type ApiAdoptionResponse = {
  case_id: string;
  run_id: string;
  mode: "accept" | "reject";
  asset_adoption_id: number;
  diff_summary?: { kept: number; added: number; missing: number; rejected?: boolean } | null;
  yaml_path?: string;
};

export type ApiAdoptionItem = {
  id: number;
  case_id: string;
  run_id: string;
  mode: "accept" | "reject";
  adopted_by: string | null;
  adopted_at: string;
  diff_summary?: { kept: number; added: number; missing: number; rejected?: boolean } | null;
};

// 路线 B · T7 / T8 / T9：稳定性 + scan 响应类型
export type ApiStability = {
  case_id: string;
  total: number;
  passed: number;
  pass_rate: number;
  status: "stable" | "flaky" | "unstable" | "insufficient";
  last_passed_at: string | null;
  last_failed_at: string | null;
  thresholds: { stable: number; unstable: number };
  insufficient_threshold: number;
  window: number;
};

export type ApiStabilityScanResponse = {
  scan_id: string;
  case_id: string;
  status: "queued" | "running" | "done" | "failed";
  times?: number;
  started_at?: string;
};

// 路线 C · T13：codegen 响应类型
export type ApiCodegenResponse = {
  ok: boolean;
  code: string;
  target_path: string;
  errors: string[];
  warnings: string[];
  written?: boolean;
  backup_path?: string | null;
  message?: string;
};

export type ApiMergeObservedAssetResult = {
  case_id: string;
  path: string;
  automation_asset: ApiObservedAsset;
};

// P0 · 所属项目下拉化（增量 2026-06-10）
export type Project = {
  id: string;
  name: string;
  base_url: string | null;
  description: string | null;
  created_at: string;
  updated_at: string;
};

// P1 · 上下文信息结构化（增量 2026-06-10）
// 4 子字段均可空；前端 JSON.stringify 后写入 cases.spec_yaml 顶层 context_info
export type ContextInfo = {
  env_url?: string;
  test_account?: string;
  excluded?: string;
  refs?: string;
};

async function testPointsWithFallback(status?: "confirmed") {
  try {
    return await request<TestPoint[]>(`/test-points${status ? `?status=${status}` : ""}`);
  } catch (error) {
    if (!(error instanceof Error) || !error.message.toLowerCase().includes("not found")) {
      throw error;
    }
    const requirements = await request<Requirement[]>("/requirements");
    const details = await Promise.allSettled(requirements.map((item) => request<RequirementDetail>(`/requirements/${item.id}`)));
    const points = details.flatMap((result) => (result.status === "fulfilled" ? result.value.test_points : []));
    const normalized = points.map((point, index) => ({
      ...point,
      parent_id: point.parent_id ?? null,
      sort_order: point.sort_order ?? index + 1,
      module: point.module || point.requirement_title || "",
      source: point.source || "legacy_requirement_detail",
      updated_at: point.updated_at || point.created_at,
    }));
    if (status !== "confirmed") {
      return normalized;
    }
    const confirmed = normalized.filter((point) => isConfirmedStatus(point.status));
    return confirmed.length ? confirmed : normalized;
  }
}

function isConfirmedStatus(status: string) {
  const value = status.trim().toLowerCase();
  return value === "confirmed" || value === "passed" || status.includes("确认") || status.includes("通过");
}

export const api = {
  health: () => request<{ status: string; runner: string; api_version?: string }>("/health"),
  aiSettings: () => request<AISettings>("/ai/settings"),
  saveAISettings: (payload: { provider?: string; api_key?: string; base_url?: string; model?: string }) =>
    request<AISettings>("/ai/settings", { method: "PUT", body: JSON.stringify(payload) }),
  platformSettings: () => request<PlatformSettings>("/platform/settings"),
  savePlatformSettings: (payload: Partial<Pick<PlatformSettings, "runner" | "asset_policy" | "environment" | "accounts">>) =>
    request<PlatformSettings>("/platform/settings", { method: "PUT", body: JSON.stringify(payload) }),
  systemHealth: () => request<SystemHealth>("/system/health"),
  testAIConnection: () => request<{ status: string; provider: string; model: string }>("/ai/test-connection", { method: "POST" }),
  ollamaModels: (baseUrl?: string) =>
    request<{ base_url: string; tags_url: string; models: OllamaModel[] }>(
      `/ai/ollama/models${baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : ""}`,
    ),
  cases: () => request<ApiCase[]>("/cases"),
  caseDetail: (caseId: string) => request<ApiCaseDetail>(`/cases/${encodeURIComponent(caseId)}`),
  requirements: () => request<Requirement[]>("/requirements"),
  createRequirement: (payload: Pick<Requirement, "title" | "document"> & { project_id?: string | null }) =>
    request<RequirementDetail>("/requirements", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  requirementDetail: (id: number) => request<RequirementDetail>(`/requirements/${id}`),
  updateRequirement: (id: number, payload: Partial<Pick<Requirement, "title" | "document" | "status" | "project_id">>) =>
    request<RequirementDetail>(`/requirements/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteRequirement: (id: number) =>
    request<{ status: string; id: number; title: string; deleted_test_points: number; deleted_case_drafts: number }>(
      `/requirements/${id}`,
      { method: "DELETE" },
    ),
  analyzeRequirement: (title: string, document: string) =>
    request<RequirementDetail>("/requirements/analyze", {
      method: "POST",
      body: JSON.stringify({ title, document }),
    }),
  analyzeRequirementSpec: (payload: { title: string; document: string; context_info?: ContextInfo; project_id?: string | null }) =>
    request<RequirementDetail>("/requirements/analyze-spec", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateTestPoint: (id: number, payload: Partial<Pick<TestPoint, "parent_id" | "name" | "category" | "priority" | "status" | "description" | "module" | "source" | "sort_order">>) =>
    request<RequirementDetail>(`/test-points/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  generateRequirementCases: (requirementId: number) =>
    request<{ draft_id: number; yaml: string; status: string }>(`/requirements/${requirementId}/generate-cases`, { method: "POST" }),
  generateCases: (testPoints: Array<{ name: string; category?: string; priority?: string; status?: string }>) =>
    request<{ yaml: string }>("/cases/generate", {
      method: "POST",
      body: JSON.stringify({ test_points: testPoints }),
    }),
  reports: () => request<ApiReportListItem[]>("/reports"),
  deleteReport: (runId: string) => request<ApiReportDeleteResult>(`/reports/${runId}`, { method: "DELETE" }),
  batchDeleteReports: (runIds: string[]) =>
    request<ApiReportBatchDeleteResult>("/reports/batch-delete", {
      method: "POST",
      body: JSON.stringify({ run_ids: runIds }),
    }),
  testPoints: (status?: "confirmed") => testPointsWithFallback(status),
  createTestPoint: (payload: Partial<Pick<TestPoint, "requirement_id" | "parent_id" | "category" | "priority" | "status" | "description" | "module" | "source" | "sort_order">> & { name: string }) =>
    request<{ id: number; requirement_id: number }>("/test-points", { method: "POST", body: JSON.stringify(payload) }),
  deleteTestPoint: (id: number) => request<{ status: string }>(`/test-points/${id}`, { method: "DELETE" }),
  reorderTestPoints: (updates: Array<{ id: number; parent_id: number | null; sort_order: number; module?: string | null; category?: string | null }>) =>
    request<{ updated: number }>("/test-points/reorder", {
      method: "PATCH",
      body: JSON.stringify({ updates }),
    }),
  caseDrafts: () => request<CaseDraft[]>("/case-drafts"),
  createCaseDraft: (payload: { requirement_id?: number | null; title?: string; yaml?: string; template?: string }) =>
    request<CaseDraft>("/case-drafts", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  caseDraftDetail: (id: number) => request<CaseDraft>(`/case-drafts/${id}`),
  updateCaseDraft: (id: number, payload: Partial<Pick<CaseDraft, "title" | "yaml" | "status">>) =>
    request<CaseDraft>(`/case-drafts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  validateCaseDraft: (id: number, payload?: { yaml?: string; case_id?: string }) =>
    request<CaseDraftValidation>(`/case-drafts/${id}/validate`, {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    }),
  promoteCaseDraft: (id: number, payload: { case_id: string; filename?: string }) =>
    request<CaseDraft>(`/case-drafts/${id}/promote`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteCaseDraft: (id: number) => request<CaseDraftDeleteResult>(`/case-drafts/${id}`, { method: "DELETE" }),
  batchDeleteCaseDrafts: (draftIds: number[]) =>
    request<CaseDraftBatchDeleteResult>("/case-drafts/batch-delete", {
      method: "POST",
      body: JSON.stringify({ draft_ids: draftIds }),
    }),
  generateCasesFromTestPoints: (
    testPointIds: number[],
    options?: { template?: string; title?: string; generator?: "rule" | "ai" },
  ) =>
    request<{ draft_id: number; yaml: string; status: string }>("/test-points/generate-cases", {
      method: "POST",
      body: JSON.stringify({ test_point_ids: testPointIds, ...(options ?? {}) }),
    }),
  exportRequirementCases: (requirementId: number, format: "xlsx" | "yaml") =>
    requestBlob(`/requirements/${requirementId}/export?format=${format}`, { method: "GET" }),
  createRun: (mode: "run-case" | "run-batch" | "run-draft" | "agent-explore", caseId?: string, draftId?: number) =>
    request<{ id: string; mode: "run-case" | "run-batch" | "run-draft" | "agent-explore"; case_id: string | null; status: string }>("/runs", {
      method: "POST",
      body: JSON.stringify({ mode, case_id: caseId, draft_id: draftId }),
    }),
  runCaseDraft: (draftId: number) =>
    request<{ id: string; mode: "run-draft"; case_id: string | null; status: string }>(`/case-drafts/${draftId}/run`, {
      method: "POST",
    }),
  runs: () => request<ApiRun[]>("/runs"),
  deleteRun: (runId: string) =>
    request<{ ok: boolean; run_id: string; deleted_files: number; deleted_dirs: number; deleted_rows: number }>(`/runs/${runId}`, {
      method: "DELETE",
    }),
  runDetail: (runId: string) => request<ApiRunDetail>(`/runs/${runId}`),
  runDetailView: (runId: string) => request<ApiRunDetailView>(`/runs/${runId}/detail`),
  promoteRegression: (runId: string) =>
    request<{ case_id: string; case_path: string; flow_path: string; draft_id?: number | null; status: string }>(`/runs/${runId}/agent-explore/promote-regression`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  selfHealAgentExplore: (runId: string) =>
    request<{ id: string; mode: "agent-explore"; case_id: string | null; status: string; parent_run_id: string; trigger: "self_heal" }>(`/runs/${runId}/agent-explore/self-heal`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  // 资产流通 · 增量：把 agent-explore 的 candidate_flow.py 提升为 case_draft
  promoteCandidate: (runId: string) =>
    request<CaseDraft>(`/runs/${runId}/agent-explore/promote-candidate`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  reportDetail: (runId: string) =>
    request<{
      run_id: string;
      metadata: { case_id: string; case_name: string; status: string; screenshots: ApiScreenshot[] };
      markdown: string;
      screenshots: ApiScreenshot[];
      evidence?: ApiEvidenceSummary;
      analysis: NonNullable<ApiRunDetail["analysis"]>;
    }>(`/reports/${runId}`),
  analyzeReport: (runId: string, options?: { force?: boolean }) =>
    request<ApiReportAnalysis>(`/reports/${runId}/analyze`, {
      method: "POST",
      body: JSON.stringify(options ?? {}),
    }),
  reportAnalysisVersions: (runId: string) => request<ApiReportAnalysisVersion[]>(`/reports/${runId}/analyses`),
  observedAsset: (runId: string) => request<ApiObservedAsset>(`/runs/${runId}/observed-asset`),
  mergeObservedAsset: (runId: string) =>
    request<ApiMergeObservedAssetResult>(`/runs/${runId}/merge-observed-asset`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  // 路线 A · 资产采纳
  observedAssetDiff: (caseId: string) =>
    request<ApiObservedAssetDiffResponse>(`/cases/${encodeURIComponent(caseId)}/observed-asset-diff`),
  postAdoption: (caseId: string, body: { run_id: string; mode: "accept" | "reject"; adopted_by?: string }) =>
    request<ApiAdoptionResponse>(`/cases/${encodeURIComponent(caseId)}/adoptions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getAdoptions: (caseId: string, limit = 3) =>
    request<ApiAdoptionItem[]>(
      `/cases/${encodeURIComponent(caseId)}/adoptions?limit=${limit}`,
    ),
  // 路线 B · T7 / T8 / T9：稳定性计算 + scan / recompute
  getCaseStability: (caseId: string, window = 20) =>
    request<ApiStability>(`/cases/${encodeURIComponent(caseId)}/stability?window=${window}`),
  postStabilityScan: (caseId: string, times = 10) =>
    request<ApiStabilityScanResponse>(`/cases/${encodeURIComponent(caseId)}/stability-scan`, {
      method: "POST",
      body: JSON.stringify({ times }),
    }),
  postRecomputeStability: (caseId: string) =>
    request<ApiStabilityScanResponse>(`/cases/${encodeURIComponent(caseId)}/recompute-stability`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  getStabilityScan: (scanId: string) =>
    request<ApiStabilityScanResponse>(`/stability-scans/${encodeURIComponent(scanId)}`),
  // 路线 C · T13：YAML → Python codegen（dry-run / 落盘）
  caseCodegen: (caseId: string, write = false, template: "functional" | "negative" | "regression" = "functional") =>
    request<ApiCodegenResponse>(`/cases/${encodeURIComponent(caseId)}/codegen`, {
      method: "POST",
      body: JSON.stringify({ write, template }),
    }),
  // P0 · 所属项目下拉化（增量 2026-06-10）：4 包装
  listProjects: () => request<Project[]>("/projects"),
  createProject: (payload: { name: string; base_url?: string | null; description?: string | null }) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (id: string, payload: { name?: string; base_url?: string | null; description?: string | null }) =>
    request<Project>(`/projects/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteProject: (id: string) =>
    request<{ ok: boolean }>(`/projects/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

export const pageFromApiStatus: Record<string, PageId> = {
  analyzed: "requirements",
  queued: "execution",
  running: "execution",
  passed: "reports",
  failed: "reports",
};
