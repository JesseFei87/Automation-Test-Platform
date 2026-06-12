import { useEffect, useMemo, useState } from "react";
import {
  api,
  type ApiAdoptionItem,
  type ApiCase,
  type ApiCodegenResponse,
  type ApiObservedAssetDiffResponse,
  type Project,
  type Requirement,
  type ApiStability,
  type CaseDraft,
  type CaseDraftValidation,
} from "../data/api";
import { Card } from "../components/Card";
import { StatusPill } from "../components/StatusPill";

type CaseRunStatus = { hasPassedRun: boolean; runId: string | null };
type AdoptionsByCase = Record<string, ApiAdoptionItem[]>;
type CodegenPhase = "idle" | "running" | "done" | "failure";
type CodegenRollbackAction = "restored" | "removed" | "defensive" | null;
type MergePreviewState = { caseId: string; data: unknown; loading: boolean };
type StabilityByCase = Record<string, ApiStability | null>;
type ScanState = "idle" | "queued" | "running" | "error";
type ScanStateByCase = Record<string, { state: ScanState; message?: string }>;

function draftTone(status: string): "green" | "amber" | "blue" {
  if (status === "promoted") return "green";
  if (status === "draft") return "amber";
  return "blue";
}

function defaultCaseId(draft?: CaseDraft | null) {
  return draft?.promoted_case_id || "TC-ICM-013";
}

function defaultFilename(caseId: string) {
  return `${caseId.toLowerCase()}-generated.yaml`;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "unknown error";
}

function readYamlScalar(yaml: string, key: string) {
  const pattern = new RegExp(`^${key}:\\s*(.+)$`, "mi");
  const match = pattern.exec(yaml);
  if (!match) return "";
  return match[1].trim().replace(/^['"]|['"]$/g, "");
}

function extractDraftMeta(draft: CaseDraft) {
  return {
    type: readYamlScalar(draft.yaml, "type") || "功能",
    priority: readYamlScalar(draft.yaml, "priority") || "P1",
    author: readYamlScalar(draft.yaml, "author") || "AI",
  };
}

function formatTime(iso?: string | null) {
  if (!iso) return "";
  try {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    const pad = (n: number) => n.toString().padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  } catch {
    return iso;
  }
}

export function CaseToolbox({ onRunCreated }: { onRunCreated?: (runId: string) => void }) {
  const [cases, setCases] = useState<ApiCase[]>([]);
  const [drafts, setDrafts] = useState<CaseDraft[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedDraftId, setSelectedDraftId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [yaml, setYaml] = useState("");
  const [caseId, setCaseId] = useState("TC-ICM-013");
  const [filename, setFilename] = useState("tc-icm-013-generated.yaml");
  const [status, setStatus] = useState("正在读取用例资产...");
  const [busy, setBusy] = useState(false);
  const [validation, setValidation] = useState<CaseDraftValidation | null>(null);

  const [runStatus, setRunStatus] = useState<Record<string, CaseRunStatus>>({});
  const [adoptions, setAdoptions] = useState<AdoptionsByCase>({});
  const [openCaseId, setOpenCaseId] = useState<string | null>(null);
  const [diff, setDiff] = useState<ApiObservedAssetDiffResponse | null>(null);
  const [diffBusy, setDiffBusy] = useState(false);
  const [adoptBusy, setAdoptBusy] = useState(false);
  const [confirming, setConfirming] = useState<"accept" | "reject" | null>(null);

  const [stabilityByCase, setStabilityByCase] = useState<StabilityByCase>({});
  const [scanStateByCase, setScanStateByCase] = useState<ScanStateByCase>({});

  const [codegenResult, setCodegenResult] = useState<ApiCodegenResponse | null>(null);
  const [codegenBusy, setCodegenBusy] = useState(false);
  const [codegenWriteBusy, setCodegenWriteBusy] = useState(false);
  const [codegenConfirming, setCodegenConfirming] = useState(false);
  const [codegenPhase, setCodegenPhase] = useState<CodegenPhase>("idle");
  const [codegenRollbackAction, setCodegenRollbackAction] = useState<CodegenRollbackAction>(null);
  const [rollbackDialogOpen, setRollbackDialogOpen] = useState(false);

  const [mergePreview, setMergePreview] = useState<MergePreviewState | null>(null);
  const [mergePreviewBusy, setMergePreviewBusy] = useState(false);
  const [mergePreviewDialogOpen, setMergePreviewDialogOpen] = useState(false);

  const [keyword, setKeyword] = useState("");
  const [draftFilter, setDraftFilter] = useState<"all" | "draft" | "promoted">("all");
  const [selectedProjectId, setSelectedProjectId] = useState("all");
  const [selectedRequirementId, setSelectedRequirementId] = useState("all");
  const [startedDate, setStartedDate] = useState("");
  const [selectedDraftIds, setSelectedDraftIds] = useState<number[]>([]);
  const [batchBusy, setBatchBusy] = useState(false);
  const [idleTimer, setIdleTimer] = useState<number | null>(null);

  const selectedDraft = drafts.find((draft) => draft.id === selectedDraftId) || null;

  async function refresh() {
    setBusy(true);
    try {
      const [caseResult, draftResult, runsResult] = await Promise.allSettled([
        api.cases(),
        api.caseDrafts(),
        api.runs(),
      ]);
      const [requirementsResult, projectsResult] = await Promise.allSettled([
        api.requirements(),
        api.listProjects(),
      ]);
      const messages: string[] = [];

      if (caseResult.status === "fulfilled") {
        setCases(caseResult.value);
        messages.push(`已读取 ${caseResult.value.length} 条正式 case`);
      } else {
        setCases([]);
        messages.push(`正式 case 读取失败：${errorMessage(caseResult.reason)}`);
      }

      if (draftResult.status === "fulfilled") {
        setDrafts(draftResult.value);
        const active = selectedDraftId
          ? draftResult.value.find((item) => item.id === selectedDraftId)
          : draftResult.value[0];
        if (active) {
          selectDraft(active);
        } else {
          setSelectedDraftId(null);
          setTitle("");
          setYaml("");
        }
        messages.push(`${draftResult.value.length} 条 YAML 草稿`);
      } else {
        setDrafts([]);
        messages.push(`YAML 草稿读取失败：${errorMessage(draftResult.reason)}`);
      }

      if (requirementsResult.status === "fulfilled") {
        setRequirements(requirementsResult.value);
      } else {
        setRequirements([]);
      }

      if (projectsResult.status === "fulfilled") {
        setProjects(projectsResult.value);
      } else {
        setProjects([]);
      }

      if (runsResult.status === "fulfilled") {
        const map: Record<string, CaseRunStatus> = {};
        for (const item of runsResult.value) {
          if (!item.case_id) continue;
          if (!map[item.case_id]) map[item.case_id] = { hasPassedRun: false, runId: null };
          if (item.status === "passed" && !map[item.case_id].hasPassedRun) {
            map[item.case_id] = { hasPassedRun: true, runId: item.id };
          }
        }
        setRunStatus(map);
      } else {
        setRunStatus({});
      }

      setStatus(messages.join("；"));
    } catch (error) {
      setStatus(`读取用例资产失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function loadAdoptionsFor(caseIdValue: string) {
    try {
      const items = await api.getAdoptions(caseIdValue, 3);
      setAdoptions((prev) => ({ ...prev, [caseIdValue]: items }));
    } catch {
      setAdoptions((prev) => ({ ...prev, [caseIdValue]: [] }));
    }
  }

  async function loadStabilityFor(caseIdValue: string) {
    try {
      const next = await api.getCaseStability(caseIdValue, 20);
      setStabilityByCase((prev) => ({ ...prev, [caseIdValue]: next }));
    } catch {
      setStabilityByCase((prev) => ({ ...prev, [caseIdValue]: null }));
    }
  }

  async function recomputeStabilityFor(caseIdValue: string) {
    setScanStateByCase((prev) => ({ ...prev, [caseIdValue]: { state: "queued" } }));
    try {
      await api.postRecomputeStability(caseIdValue);
      setScanStateByCase((prev) => ({ ...prev, [caseIdValue]: { state: "running" } }));
      setStatus(`已触发 ${caseIdValue} 连跑 10 次，后台正在刷新稳定分`);
      setTimeout(() => {
        void loadStabilityFor(caseIdValue);
        setScanStateByCase((prev) => ({ ...prev, [caseIdValue]: { state: "idle" } }));
      }, 5000);
    } catch (error) {
      setScanStateByCase((prev) => ({
        ...prev,
        [caseIdValue]: { state: "error", message: errorMessage(error) },
      }));
      setStatus(`重算稳定分失败：${errorMessage(error)}`);
    }
  }

  function extractRollbackAction(result: ApiCodegenResponse): CodegenRollbackAction {
    const text = `${result.errors.join("\n")}\n${result.message ?? ""}\n${result.warnings.join("\n")}`;
    if (/defensive/i.test(text)) return "defensive";
    if (/restored/i.test(text)) return "restored";
    if (/removed/i.test(text)) return "removed";
    return null;
  }

  async function loadMergePreview(caseIdValue: string) {
    setMergePreviewBusy(true);
    setMergePreview({ caseId: caseIdValue, data: null, loading: true });
    try {
      const candidate = (api as unknown as { getMergePreview?: (id: string) => Promise<unknown> }).getMergePreview;
      if (typeof candidate === "function") {
        const data = await candidate(caseIdValue);
        setMergePreview({ caseId: caseIdValue, data, loading: false });
      } else {
        setMergePreview({ caseId: caseIdValue, data: null, loading: false });
      }
    } catch {
      setMergePreview({ caseId: caseIdValue, data: null, loading: false });
    } finally {
      setMergePreviewBusy(false);
    }
  }

  async function runCodegenDryRun() {
    setCodegenBusy(true);
    setCodegenConfirming(false);
    setCodegenResult(null);
    setCodegenPhase("running");
    setCodegenRollbackAction(null);
    if (idleTimer) {
      clearTimeout(idleTimer);
      setIdleTimer(null);
    }
    try {
      const result = await api.caseCodegen(caseId, false, "functional");
      setCodegenResult(result);
      if (result.ok) {
        setCodegenPhase("done");
        setStatus(`脚本 dry-run 通过：${result.target_path}`);
        const timer = window.setTimeout(() => setCodegenPhase("idle"), 5000);
        setIdleTimer(timer);
      } else {
        setCodegenPhase("failure");
        setCodegenRollbackAction(extractRollbackAction(result));
        setStatus(`脚本 dry-run 失败：${result.errors.join("；")}`);
      }
    } catch (error) {
      setCodegenResult({
        ok: false,
        code: "",
        target_path: "",
        errors: [errorMessage(error)],
        warnings: [],
      });
      setCodegenPhase("failure");
      setStatus(`脚本 dry-run 失败：${errorMessage(error)}`);
    } finally {
      setCodegenBusy(false);
    }
  }

  async function runCodegenWrite() {
    setCodegenWriteBusy(true);
    setCodegenPhase("running");
    setCodegenRollbackAction(null);
    if (idleTimer) {
      clearTimeout(idleTimer);
      setIdleTimer(null);
    }
    try {
      const result = await api.caseCodegen(caseId, true, "functional");
      setCodegenResult(result);
      if (result.ok && result.written) {
        setCodegenPhase("done");
        setStatus(`脚本已落盘：${result.target_path}`);
        const timer = window.setTimeout(() => setCodegenPhase("idle"), 5000);
        setIdleTimer(timer);
      } else {
        setCodegenPhase("failure");
        setCodegenRollbackAction(extractRollbackAction(result));
        setStatus(`脚本落盘失败：${result.errors.join("；")}`);
      }
    } catch (error) {
      setCodegenPhase("failure");
      setStatus(`脚本落盘失败：${errorMessage(error)}`);
    } finally {
      setCodegenWriteBusy(false);
      setCodegenConfirming(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    cases.forEach((item) => {
      if (!adoptions[item.id]) {
        void loadAdoptionsFor(item.id);
      }
    });
  }, [adoptions, cases]);

  useEffect(() => {
    cases.forEach((item) => {
      if (!(item.id in stabilityByCase)) {
        void loadStabilityFor(item.id);
      }
    });
  }, [cases, stabilityByCase]);

  function selectDraft(draft: CaseDraft) {
    const nextCaseId = defaultCaseId(draft);
    setSelectedDraftId(draft.id);
    setTitle(draft.title);
    setYaml(draft.yaml);
    setCaseId(nextCaseId);
    setFilename(
      draft.promoted_path
        ? draft.promoted_path.split(/[\\/]/).pop() || defaultFilename(nextCaseId)
        : defaultFilename(nextCaseId),
    );
    setValidation(null);
  }

  async function saveDraft() {
    if (!selectedDraft) {
      setStatus("请先选择一条 YAML 草稿");
      return;
    }
    setBusy(true);
    try {
      const updated = await api.updateCaseDraft(selectedDraft.id, { title, yaml });
      setDrafts((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      selectDraft(updated);
      setStatus(`草稿已保存：draft #${updated.id}`);
    } catch (error) {
      setStatus(`保存草稿失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function validateDraft() {
    if (!selectedDraft) {
      setStatus("请先选择一条 YAML 草稿");
      return null;
    }
    setBusy(true);
    try {
      const result = await api.validateCaseDraft(selectedDraft.id, { yaml, case_id: caseId });
      setValidation(result);
      setStatus(result.valid ? "YAML 校验通过，可以转正式 case" : `YAML 校验失败：${result.errors.join("；")}`);
      return result;
    } catch (error) {
      setValidation(null);
      setStatus(`YAML 校验失败：${errorMessage(error)}`);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function promoteDraft() {
    if (!selectedDraft) {
      setStatus("请先选择一条 YAML 草稿");
      return;
    }
    setBusy(true);
    try {
      const updated = await api.updateCaseDraft(selectedDraft.id, { title, yaml });
      setDrafts((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      const result = await api.validateCaseDraft(selectedDraft.id, { yaml, case_id: caseId });
      setValidation(result);
      if (!result.valid) {
        setStatus(`YAML 校验失败，已阻止转正式：${result.errors.join("；")}`);
        return;
      }
      const promoted = await api.promoteCaseDraft(selectedDraft.id, { case_id: caseId, filename });
      setDrafts((items) => items.map((item) => (item.id === promoted.id ? promoted : item)));
      selectDraft(promoted);
      setCases(await api.cases());
      setStatus(`已转正式 case：${promoted.promoted_case_id}`);
    } catch (error) {
      setStatus(`转正式 case 失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function openAdoptionPanel(caseIdValue: string) {
    setOpenCaseId(caseIdValue);
    setDiff(null);
    setConfirming(null);
    setDiffBusy(true);
    try {
      const nextDiff = await api.observedAssetDiff(caseIdValue);
      setDiff(nextDiff);
    } catch (error) {
      setDiff(null);
      setStatus(`加载 diff 失败：${errorMessage(error)}`);
    } finally {
      setDiffBusy(false);
    }
  }

  function closeAdoptionPanel() {
    setOpenCaseId(null);
    setDiff(null);
    setConfirming(null);
  }

  async function commitAdoption(mode: "accept" | "reject") {
    if (!openCaseId || !diff) return;
    setAdoptBusy(true);
    try {
      const result = await api.postAdoption(openCaseId, { run_id: diff.run_id, mode });
      setStatus(
        mode === "accept"
          ? `已采纳观察值：${openCaseId}（asset_adoption #${result.asset_adoption_id}）`
          : `已拒绝观察值：${openCaseId}（asset_adoption #${result.asset_adoption_id}）`,
      );
      await loadAdoptionsFor(openCaseId);
      if (mode === "accept") {
        setCases(await api.cases());
      }
      closeAdoptionPanel();
    } catch (error) {
      setStatus(`${mode === "accept" ? "采纳" : "拒绝"}失败：${errorMessage(error)}`);
    } finally {
      setAdoptBusy(false);
      setConfirming(null);
    }
  }

  const adoptionSummary = useMemo(() => {
    const map: Record<string, ApiAdoptionItem | null> = {};
    for (const item of cases) {
      const list = adoptions[item.id] || [];
      map[item.id] = list.length ? list[0] : null;
    }
    return map;
  }, [adoptions, cases]);

  const requirementById = useMemo(() => {
    const map = new Map<number, Requirement>();
    requirements.forEach((item) => map.set(item.id, item));
    return map;
  }, [requirements]);

  const projectById = useMemo(() => {
    const map = new Map<string, Project>();
    projects.forEach((item) => map.set(item.id, item));
    return map;
  }, [projects]);

  const filteredDrafts = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    return drafts.filter((draft) => {
      const requirement = requirementById.get(draft.requirement_id);
      const requirementProjectId = String((requirement as Requirement & { project_id?: string | number | null }).project_id ?? "unassigned");
      if (draftFilter === "draft" && draft.promoted_case_id) return false;
      if (draftFilter === "promoted" && !draft.promoted_case_id) return false;
      if (selectedRequirementId !== "all" && String(draft.requirement_id) !== selectedRequirementId) return false;
      if (selectedProjectId !== "all" && requirementProjectId !== selectedProjectId) return false;
      if (startedDate) {
        const created = draft.created_at?.slice(0, 10) || "";
        if (created < startedDate) return false;
      }
      if (!q) return true;
      return [draft.title, draft.promoted_case_id || "", draft.requirement_title || "", draft.status, requirement?.title || ""]
        .join(" ")
        .toLowerCase()
        .includes(q);
    });
  }, [draftFilter, drafts, keyword, requirementById, selectedProjectId, selectedRequirementId, startedDate]);

  const selectedDraftIdSet = useMemo(() => new Set(selectedDraftIds), [selectedDraftIds]);
  const allVisibleSelected = filteredDrafts.length > 0 && filteredDrafts.every((draft) => selectedDraftIdSet.has(draft.id));

  function toggleDraftSelection(draftId: number) {
    setSelectedDraftIds((prev) => (prev.includes(draftId) ? prev.filter((id) => id !== draftId) : [...prev, draftId]));
  }

  function toggleSelectAllVisible() {
    setSelectedDraftIds((prev) => {
      if (allVisibleSelected) {
        return prev.filter((id) => !filteredDrafts.some((draft) => draft.id === id));
      }
      const next = new Set(prev);
      filteredDrafts.forEach((draft) => next.add(draft.id));
      return Array.from(next);
    });
  }

  function resetFilters() {
    setKeyword("");
    setDraftFilter("all");
    setSelectedProjectId("all");
    setSelectedRequirementId("all");
    setStartedDate("");
  }

  async function batchValidateSelected() {
    if (!selectedDraftIds.length) {
      setStatus("请先勾选至少一条用例");
      return;
    }
    setBatchBusy(true);
    try {
      let passed = 0;
      let failed = 0;
      for (const draftId of selectedDraftIds) {
        const draft = drafts.find((item) => item.id === draftId);
        if (!draft) continue;
        const nextCaseId = draft.promoted_case_id || defaultCaseId(draft);
        const result = await api.validateCaseDraft(draftId, { yaml: draft.yaml, case_id: nextCaseId });
        if (selectedDraftId === draftId) {
          setValidation(result);
        }
        if (result.valid) passed += 1;
        else failed += 1;
      }
      setStatus(`批量校验完成：通过 ${passed} 条，失败 ${failed} 条`);
    } catch (error) {
      setStatus(`批量校验失败：${errorMessage(error)}`);
    } finally {
      setBatchBusy(false);
    }
  }

  async function batchCodegenPreview() {
    if (!selectedDraftIds.length) {
      setStatus("请先勾选至少一条用例");
      return;
    }
    setBatchBusy(true);
    try {
      let passed = 0;
      let failed = 0;
      for (const draftId of selectedDraftIds) {
        const draft = drafts.find((item) => item.id === draftId);
        if (!draft) continue;
        const targetCaseId = draft.promoted_case_id || defaultCaseId(draft);
        const result = await api.caseCodegen(targetCaseId, false, "functional");
        if (result.ok) passed += 1;
        else failed += 1;
      }
      setStatus(`批量脚本预检完成：通过 ${passed} 条，失败 ${failed} 条`);
    } catch (error) {
      setStatus(`批量脚本预检失败：${errorMessage(error)}`);
    } finally {
      setBatchBusy(false);
    }
  }

  async function runAiExecution(draft: CaseDraft) {
    const caseId = draft.promoted_case_id || defaultCaseId(draft);
    setBusy(true);
    setStatus(draft.promoted_case_id ? `正在提交 AI真实执行：${caseId}...` : `正在提交草稿临时 AI真实执行：${draft.title || `draft #${draft.id}`}...`);
    try {
      const task = draft.promoted_case_id
        ? await api.createRun("run-case", draft.promoted_case_id)
        : await api.runCaseDraft(draft.id);
      setStatus(`已创建 AI真实执行任务：${task.id}，可到 AI测试 / 报告中心查看证据链。`);
      onRunCreated?.(task.id);
    } catch (error) {
      const message = error instanceof Error ? error.message : "unknown error";
      setStatus(
        message.includes("422") || message.includes("Not Found")
          ? "AI真实执行提交失败：后端服务仍是旧版本，请重启 FastAPI 后端并刷新页面。"
          : `AI真实执行提交失败：${message}`,
      );
    } finally {
      setBusy(false);
    }
  }

  const selectedPromotedCaseId = selectedDraft?.promoted_case_id || null;
  const selectedFormalCase = selectedPromotedCaseId
    ? cases.find((item) => item.id === selectedPromotedCaseId) || null
    : null;
  const selectedAdoption = selectedPromotedCaseId ? adoptionSummary[selectedPromotedCaseId] : null;
  const selectedStability = selectedPromotedCaseId ? stabilityByCase[selectedPromotedCaseId] ?? null : null;
  const promotedDraftCount = drafts.filter((draft) => !!draft.promoted_case_id).length;
  const automationAssetCount = cases.filter((item) => item.has_automation_asset).length;

  return (
    <div className="page case-page">
      <div className="case-manager-stats">
        <Card className="case-stat-card">
          <span className="case-stat-card__label">YAML 草稿</span>
          <strong>{drafts.length}</strong>
          <small>当前草稿库总量</small>
        </Card>
        <Card className="case-stat-card">
          <span className="case-stat-card__label">正式用例</span>
          <strong>{cases.length}</strong>
          <small>test-cases/icm/*.yaml</small>
        </Card>
        <Card className="case-stat-card">
          <span className="case-stat-card__label">已转正式</span>
          <strong>{promotedDraftCount}</strong>
          <small>草稿已完成落盘</small>
        </Card>
        <Card className="case-stat-card">
          <span className="case-stat-card__label">已沉淀资产</span>
          <strong>{automationAssetCount}</strong>
          <small>带 automation_asset</small>
        </Card>
      </div>

      <div className="case-manager-layout">
        <Card
          className="case-table-card"
          title="用例管理"
          subtitle="表格化浏览草稿与正式 case 的衔接状态，点击任意一行可在右侧查看 YAML 详情。"
        >
          <div className="case-filter-grid">
            <label className="case-filter-field">
              <span>关键词</span>
              <input
                className="text-input"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索用例标题或 ID"
              />
            </label>
            <label className="case-filter-field">
              <span>项目</span>
              <select
                className="case-filter-select"
                value={selectedProjectId}
                onChange={(event) => setSelectedProjectId(event.target.value)}
              >
                <option value="all">所有项目</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>{project.name}</option>
                ))}
              </select>
            </label>
            <label className="case-filter-field">
              <span>需求</span>
              <select
                className="case-filter-select"
                value={selectedRequirementId}
                onChange={(event) => setSelectedRequirementId(event.target.value)}
              >
                <option value="all">所有需求</option>
                {requirements.map((requirement) => (
                  <option key={requirement.id} value={String(requirement.id)}>{requirement.title}</option>
                ))}
              </select>
            </label>
            <label className="case-filter-field">
              <span>开始时间</span>
              <input
                className="text-input"
                type="date"
                value={startedDate}
                onChange={(event) => setStartedDate(event.target.value)}
              />
            </label>
            <div className="case-filter-actions">
              <button className="btn btn--primary" type="button" onClick={refresh} disabled={busy || batchBusy}>
                搜索
              </button>
              <button className="btn btn--outline" type="button" onClick={resetFilters} disabled={busy || batchBusy}>
                重置
              </button>
            </div>
          </div>

          <div className="case-batch-bar">
            <label className="case-batch-check">
              <input type="checkbox" checked={allVisibleSelected} onChange={toggleSelectAllVisible} />
              <span>全选本页</span>
            </label>
            <span className="case-batch-count">已选 {selectedDraftIds.length} 条</span>
            <button className="btn btn--outline" type="button" disabled={batchBusy || busy || !selectedDraftIds.length} onClick={batchValidateSelected}>
              批量校验
            </button>
            <button className="btn btn--outline" type="button" disabled={batchBusy || busy || !selectedDraftIds.length} onClick={batchCodegenPreview}>
              批量脚本预检
            </button>
            <button className="btn btn--outline" type="button" disabled={!selectedDraftIds.length} onClick={() => setSelectedDraftIds([])}>
              清空选择
            </button>
          </div>

          <div className="case-table-shell">
            <table className="table case-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>标题</th>
                  <th>项目</th>
                  <th>类型</th>
                  <th>优先级</th>
                  <th>状态</th>
                  <th>创建人</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredDrafts.map((draft, index) => {
                  const meta = extractDraftMeta(draft);
                  const requirement = requirementById.get(draft.requirement_id) as (Requirement & { project_id?: string | null }) | undefined;
                  const projectName = requirement?.project_id ? projectById.get(String(requirement.project_id))?.name || "未匹配项目" : "未分配项目";
                  const formalCase = draft.promoted_case_id
                    ? cases.find((item) => item.id === draft.promoted_case_id) || null
                    : null;
                  const latestAdoption = draft.promoted_case_id ? adoptionSummary[draft.promoted_case_id] : null;
                  const stability = draft.promoted_case_id ? stabilityByCase[draft.promoted_case_id] ?? null : null;
                  const scan = draft.promoted_case_id
                    ? scanStateByCase[draft.promoted_case_id] ?? { state: "idle" as const }
                    : { state: "idle" as const };
                  const passedRunReady = draft.promoted_case_id ? !!runStatus[draft.promoted_case_id]?.hasPassedRun : false;

                  return (
                    <tr
                      key={draft.id}
                      className={draft.id === selectedDraftId ? "is-selected-row" : undefined}
                      onClick={() => selectDraft(draft)}
                    >
                      <td onClick={(event) => event.stopPropagation()}>
                        <label className="case-row-check">
                          <input
                            type="checkbox"
                            checked={selectedDraftIdSet.has(draft.id)}
                            onChange={() => toggleDraftSelection(draft.id)}
                          />
                          <span>{index + 1}</span>
                        </label>
                      </td>
                      <td>
                        <div className="case-title-cell">
                          <strong>{draft.title || `未命名草稿 #${draft.id}`}</strong>
                          <span>{draft.promoted_case_id || `draft #${draft.id}`}</span>
                        </div>
                      </td>
                      <td>
                        <div className="case-id-stack">
                          <strong>{projectName}</strong>
                          <span>{draft.requirement_title || "未关联需求"}</span>
                        </div>
                      </td>
                      <td>
                        <div className="case-status-stack">
                          <StatusPill tone="blue">{meta.type}</StatusPill>
                        </div>
                      </td>
                      <td>
                        <div className="case-status-stack">
                          <StatusPill tone={meta.priority === "P0" ? "red" : meta.priority === "P1" ? "amber" : "blue"}>
                            {meta.priority}
                          </StatusPill>
                        </div>
                      </td>
                      <td>
                        <div className="case-status-stack">
                          <StatusPill tone={draftTone(draft.status)}>{draft.status}</StatusPill>
                          <span className="muted">{formalCase ? (formalCase.has_automation_asset ? "已沉淀" : formalCase.status) : "待转正式"}</span>
                        </div>
                      </td>
                      <td>{meta.author}</td>
                      <td>{formatTime(draft.created_at)}</td>
                      <td>
                        <div className="case-row-actions" onClick={(event) => event.stopPropagation()}>
                          <button
                            className="case-row-action case-row-action--primary"
                            type="button"
                            title="查看 YAML 详情"
                            onClick={() => selectDraft(draft)}
                          >
                            看
                          </button>
                          <button
                            className="case-row-action"
                            type="button"
                            title="校验 YAML"
                            disabled={busy}
                            onClick={() => {
                              selectDraft(draft);
                              setTimeout(() => {
                                void validateDraft();
                              }, 0);
                            }}
                          >
                            验
                          </button>
                          <button
                            className="case-row-action"
                            type="button"
                            title="查看 observed asset"
                            disabled={busy || !draft.promoted_case_id || !passedRunReady}
                            onClick={() => {
                              if (draft.promoted_case_id) {
                                void openAdoptionPanel(draft.promoted_case_id);
                              }
                            }}
                          >
                            资
                          </button>
                          <button
                            className="case-row-action case-row-action--primary"
                            type="button"
                            title={draft.promoted_case_id ? "AI真实执行正式 case" : "AI真实执行草稿临时 YAML"}
                            disabled={busy}
                            onClick={() => {
                              void runAiExecution(draft);
                            }}
                          >
                            AI
                          </button>
                          <button
                            className="case-row-action"
                            type="button"
                            title="重算稳定分"
                            disabled={busy || !draft.promoted_case_id || scan.state === "queued" || scan.state === "running"}
                            onClick={() => {
                              if (draft.promoted_case_id) {
                                void recomputeStabilityFor(draft.promoted_case_id);
                              }
                            }}
                          >
                            10
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {!filteredDrafts.length ? (
                  <tr>
                    <td colSpan={9}>当前筛选条件下没有用例，请先到需求管理 / AI生成生成草稿。</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>

          <div className="case-table-caption">{status}</div>
        </Card>

        <div className="case-detail-rail">
          <Card
            className="case-detail-card"
            title="YAML 详情侧栏"
            subtitle="这里聚焦单条用例的 YAML 内容、质量门禁、正式落盘和脚本化入口。"
          >
            <div className="case-drawer-handle" aria-hidden="true" />
            <label className="field-label" htmlFor="case-draft-title-select">草稿标题</label>
            <select
              id="case-draft-title-select"
              className="text-input"
              value={selectedDraftId ?? ""}
              onChange={(event) => {
                const nextId = Number(event.target.value);
                const next = drafts.find((item) => item.id === nextId);
                if (next) {
                  selectDraft(next);
                }
              }}
            >
              {drafts.length ? (
                drafts.map((draft) => (
                  <option key={draft.id} value={draft.id}>
                    {`#${draft.id} · ${draft.title || "未命名草稿"}`}
                  </option>
                ))
              ) : (
                <option value="">暂无草稿，请先到需求管理或 AI生成页面创建</option>
              )}
            </select>

            {selectedDraft ? (
              <div className="selected-summary">
                <span><strong>需求：</strong>{selectedDraft.requirement_title || "未关联需求"}</span>
                <span><strong>正式 Case：</strong>{selectedDraft.promoted_case_id || "未转正式"}</span>
                <span><strong>模板：</strong>{selectedDraft.template || "functional"}</span>
                <span><strong>更新时间：</strong>{formatTime(selectedDraft.updated_at)}</span>
              </div>
            ) : (
              <p className="empty-state">还没有选中的 YAML 草稿。</p>
            )}

            {selectedFormalCase ? (
              <div className="selected-summary">
                <span><strong>正式文件：</strong>{selectedFormalCase.path}</span>
                <span><strong>资产状态：</strong>{selectedFormalCase.has_automation_asset ? "已沉淀 automation_asset" : "待补齐"}</span>
                <span><strong>观察值采纳：</strong>{selectedAdoption ? `${selectedAdoption.mode} · ${formatTime(selectedAdoption.adopted_at)}` : "暂无"}</span>
                <span><strong>稳定度：</strong>{selectedStability ? `${Math.round(selectedStability.pass_rate * 100)}%` : "暂无"}</span>
              </div>
            ) : null}

            <label className="field-label">YAML 内容</label>
            <textarea
              className="code-block code-block--editor case-detail-editor"
              value={yaml}
              onChange={(event) => setYaml(event.target.value)}
              placeholder="请选择一条草稿，或从需求管理 / AI生成页面创建 YAML 草稿。"
            />

            <div className="button-row">
              <button className="btn btn--primary" disabled={busy || !selectedDraft} onClick={saveDraft} type="button">
                保存草稿
              </button>
              <button className="btn btn--outline" disabled={busy || !selectedDraft} onClick={validateDraft} type="button">
                校验 YAML
              </button>
            </div>

            <div className={`validation-panel ${validation?.valid ? "validation-panel--ok" : validation ? "validation-panel--error" : ""}`}>
              <div className="validation-panel__header">
                <strong>YAML 质量门禁</strong>
                {validation ? (
                  <StatusPill tone={validation.valid ? "green" : "red"}>{validation.valid ? "通过" : "未通过"}</StatusPill>
                ) : (
                  <StatusPill tone="blue">待校验</StatusPill>
                )}
              </div>
              <p>正式落盘前会检查 YAML 语法、基础字段、操作步骤、页面 selector、输入值和断言点。</p>
              {validation?.errors.length ? (
                <ul className="validation-list validation-list--error">
                  {validation.errors.map((item) => <li key={item}>{item}</li>)}
                </ul>
              ) : null}
              {validation?.warnings.length ? (
                <ul className="validation-list validation-list--warning">
                  {validation.warnings.map((item) => <li key={item}>{item}</li>)}
                </ul>
              ) : null}
            </div>

            <div className="promote-grid">
              <label>
                <span className="field-label">正式 Case ID</span>
                <input
                  className="text-input"
                  value={caseId}
                  onChange={(event) => {
                    const value = event.target.value;
                    setCaseId(value);
                    setFilename(defaultFilename(value));
                  }}
                />
              </label>
              <label>
                <span className="field-label">文件名</span>
                <input className="text-input" value={filename} onChange={(event) => setFilename(event.target.value)} />
              </label>
            </div>

            {selectedDraft?.promoted_path ? (
              <div className="promoted-note">
                <StatusPill tone="green">已转正式</StatusPill>
                <span>{selectedDraft.promoted_path}</span>
              </div>
            ) : null}

            <div className="button-row">
              <button className="btn btn--green" disabled={busy || !selectedDraft} onClick={promoteDraft} type="button">
                转正式 case 文件
              </button>
              {selectedPromotedCaseId ? (
                <button
                  className="btn btn--outline"
                  type="button"
                  disabled={busy || !runStatus[selectedPromotedCaseId]?.hasPassedRun}
                  onClick={() => void openAdoptionPanel(selectedPromotedCaseId)}
                >
                  查看 observed asset
                </button>
              ) : null}
              {selectedPromotedCaseId ? (
                <button
                  className="link-button"
                  type="button"
                  disabled={busy || mergePreviewBusy}
                  onClick={async () => {
                    await loadMergePreview(selectedPromotedCaseId);
                    setMergePreviewDialogOpen(true);
                  }}
                >
                  {mergePreviewBusy && mergePreview?.caseId === selectedPromotedCaseId && mergePreview.loading ? "加载 diff…" : "查看 YAML diff"}
                </button>
              ) : null}
            </div>
          </Card>

          <Card
            className="codegen-card"
            title="生成 Python 脚本"
            subtitle="按 YAML 模板渲染；先 dry-run 预览，确认后再落盘到 runner/flows/。"
          >
            <div className="button-row" style={{ alignItems: "center" }}>
              <button
                className={
                  codegenPhase === "failure"
                    ? "btn btn--danger"
                    : codegenPhase === "done"
                    ? "btn btn--green"
                    : "btn btn--primary"
                }
                disabled={codegenBusy || codegenWriteBusy || !caseId || codegenPhase === "running"}
                type="button"
                onClick={runCodegenDryRun}
              >
                {codegenPhase === "running"
                  ? "编译中…"
                  : codegenPhase === "done"
                  ? `已生成 ${codegenResult?.target_path || ""}`
                  : codegenPhase === "failure"
                  ? "编译失败"
                  : "生成 Python 脚本"}
              </button>
              {codegenPhase === "failure" && codegenResult ? (
                <button className="btn btn--outline" type="button" onClick={() => setRollbackDialogOpen(true)}>
                  查看 rollback 详情
                </button>
              ) : null}
              <span className="muted">模板：functional · 目标：runner/flows/icm_case_xxx.py</span>
            </div>

            {codegenResult ? (
              <div className="codegen-result" style={{ marginTop: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <StatusPill tone={codegenResult.ok ? "green" : "red"}>
                    {codegenResult.ok ? "可落盘" : "无法生成"}
                  </StatusPill>
                  <code className="muted">{codegenResult.target_path}</code>
                  {codegenResult.written ? <StatusPill tone="blue">已落盘</StatusPill> : null}
                </div>
                {codegenResult.errors.length ? (
                  <ul className="validation-list validation-list--error" style={{ marginTop: 8 }}>
                    {codegenResult.errors.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {codegenResult.warnings.length ? (
                  <ul className="validation-list validation-list--warning" style={{ marginTop: 8 }}>
                    {codegenResult.warnings.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                <label className="field-label" style={{ marginTop: 8 }}>代码预览</label>
                <textarea
                  className="code-block code-block--editor case-codegen-editor"
                  readOnly
                  value={codegenResult.code || "(无代码)"}
                  placeholder="dry-run 结果会显示在这里"
                />
                {codegenResult.message ? (
                  <p className="muted" style={{ marginTop: 6 }}>{codegenResult.message}</p>
                ) : null}
                <div className="button-row" style={{ marginTop: 8 }}>
                  {codegenConfirming ? (
                    <>
                      <span style={{ color: "#c0392b" }}>确认将代码写入 {codegenResult.target_path} ？</span>
                      <button
                        className="btn btn--green"
                        type="button"
                        disabled={codegenWriteBusy}
                        onClick={runCodegenWrite}
                      >
                        确认落盘
                      </button>
                      <button
                        className="btn btn--outline"
                        type="button"
                        disabled={codegenWriteBusy}
                        onClick={() => setCodegenConfirming(false)}
                      >
                        取消
                      </button>
                    </>
                  ) : (
                    <button
                      className="btn btn--green"
                      type="button"
                      disabled={!codegenResult.ok || codegenBusy || codegenWriteBusy}
                      onClick={() => setCodegenConfirming(true)}
                    >
                      落盘到 runner/flows/
                    </button>
                  )}
                </div>
              </div>
            ) : null}

            {rollbackDialogOpen && codegenResult ? (
              <RollbackDialog
                result={codegenResult}
                rollbackAction={codegenRollbackAction}
                onClose={() => setRollbackDialogOpen(false)}
              />
            ) : null}
          </Card>

          {selectedPromotedCaseId && openCaseId === selectedPromotedCaseId ? (
            <Card
              className="asset-card"
              title="Observed Asset / YAML Diff"
              subtitle="用于将真实跑通后的观察值合并为更可靠的 automation_asset。"
            >
              <DiffPreviewPanel
                diff={diff}
                loading={diffBusy}
                confirming={confirming}
                adoptBusy={adoptBusy}
                onClose={closeAdoptionPanel}
                onConfirmStart={setConfirming}
                onConfirmCommit={commitAdoption}
              />
              <div className="button-row" style={{ marginTop: 12 }}>
                <button
                  className="btn btn--outline"
                  type="button"
                  disabled={busy || mergePreviewBusy}
                  onClick={async () => {
                    await loadMergePreview(selectedPromotedCaseId);
                    setMergePreviewDialogOpen(true);
                  }}
                >
                  字段级 diff 预览
                </button>
                <button
                  className="btn btn--outline"
                  type="button"
                  disabled={busy || scanStateByCase[selectedPromotedCaseId]?.state === "queued" || scanStateByCase[selectedPromotedCaseId]?.state === "running"}
                  onClick={() => void recomputeStabilityFor(selectedPromotedCaseId)}
                >
                  {scanStateByCase[selectedPromotedCaseId]?.state === "queued" || scanStateByCase[selectedPromotedCaseId]?.state === "running"
                    ? "跑 10 次中…"
                    : "重算稳定分"}
                </button>
              </div>
            </Card>
          ) : null}

          {mergePreviewDialogOpen && mergePreview && !mergePreview.loading ? (
            <MergePreviewDialog data={mergePreview.data} onClose={() => setMergePreviewDialogOpen(false)} />
          ) : null}
        </div>
      </div>
    </div>
  );
}

function RollbackDialog({
  result,
  rollbackAction,
  onClose,
}: {
  result: ApiCodegenResponse;
  rollbackAction: CodegenRollbackAction;
  onClose: () => void;
}) {
  const actionLabel: Record<NonNullable<CodegenRollbackAction>, string> = {
    restored: "已从 backup 恢复旧内容",
    removed: "已删除新创建文件",
    defensive: "已做防御性清理",
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        style={{
          background: "var(--card, #fff)",
          color: "var(--text, #222)",
          borderRadius: 8,
          padding: 20,
          minWidth: 420,
          maxWidth: 640,
          maxHeight: "80vh",
          overflow: "auto",
          boxShadow: "0 10px 30px rgba(0,0,0,0.25)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <strong style={{ fontSize: "1.05em" }}>codegen 失败 · rollback 详情</strong>
          <button className="btn btn--outline" type="button" onClick={onClose}>关闭</button>
        </div>
        <div style={{ marginBottom: 12 }}>
          <span className="muted">目标文件：</span>
          <code>{result.target_path || "(空)"}</code>
        </div>
        <div style={{ marginBottom: 12 }}>
          <span className="muted">rollback.action：</span>
          {rollbackAction ? (
            <StatusPill tone={rollbackAction === "restored" ? "green" : "amber"}>
              {actionLabel[rollbackAction]}
            </StatusPill>
          ) : (
            <StatusPill tone="dark">未触发</StatusPill>
          )}
        </div>
        <div style={{ marginBottom: 8 }}>
          <strong>errors</strong>
          {result.errors.length ? (
            <ul className="validation-list validation-list--error" style={{ marginTop: 4 }}>
              {result.errors.map((item) => (
                <li key={item}><code style={{ whiteSpace: "pre-wrap" }}>{item}</code></li>
              ))}
            </ul>
          ) : (
            <p className="muted" style={{ marginTop: 4 }}>无 errors</p>
          )}
        </div>
        {result.warnings.length ? (
          <div style={{ marginBottom: 8 }}>
            <strong>warnings</strong>
            <ul className="validation-list validation-list--warning" style={{ marginTop: 4 }}>
              {result.warnings.map((item) => (
                <li key={item}><code style={{ whiteSpace: "pre-wrap" }}>{item}</code></li>
              ))}
            </ul>
          </div>
        ) : null}
        {result.message ? (
          <p className="muted" style={{ marginTop: 6 }}>
            <strong>message：</strong>
            <code style={{ whiteSpace: "pre-wrap" }}>{result.message}</code>
          </p>
        ) : null}
      </div>
    </div>
  );
}

function MergePreviewDialog({
  data,
  onClose,
}: {
  data: unknown;
  onClose: () => void;
}) {
  const rows = formatMergePreviewRows(data);
  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        style={{
          background: "var(--card, #fff)",
          color: "var(--text, #222)",
          borderRadius: 8,
          padding: 20,
          minWidth: 480,
          maxWidth: 720,
          maxHeight: "80vh",
          overflow: "auto",
          boxShadow: "0 10px 30px rgba(0,0,0,0.25)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <strong>采纳预览（字段级 diff）</strong>
          <button className="btn btn--outline" type="button" onClick={onClose}>关闭</button>
        </div>
        {rows.length === 0 ? (
          <p className="muted">后端暂未提供字段级 diff 预览端点，当前仅保留弹窗入口。</p>
        ) : (
          <table className="table">
            <thead>
              <tr><th>key</th><th>current</th><th>proposed</th></tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key}>
                  <td><code>{row.key}</code></td>
                  <td><code style={{ whiteSpace: "pre-wrap" }}>{row.current}</code></td>
                  <td><code style={{ whiteSpace: "pre-wrap" }}>{row.proposed}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function formatMergePreviewRows(data: unknown): { key: string; current: string; proposed: string }[] {
  if (!data || typeof data !== "object") return [];
  const obj = data as Record<string, unknown>;
  if ("current" in obj && "proposed" in obj) {
    const current = obj.current as Record<string, unknown> | null;
    const proposed = obj.proposed as Record<string, unknown> | null;
    const keys = Array.from(new Set([...Object.keys(current ?? {}), ...Object.keys(proposed ?? {})]));
    return keys.map((key) => ({
      key,
      current: JSON.stringify(current?.[key] ?? ""),
      proposed: JSON.stringify(proposed?.[key] ?? ""),
    }));
  }
  if ("diff" in obj && obj.diff && typeof obj.diff === "object") {
    const diff = obj.diff as { kept?: Record<string, unknown>; added?: Record<string, unknown> };
    return [
      ...Object.entries(diff.kept ?? {}).map(([key, value]) => ({
        key,
        current: JSON.stringify(value),
        proposed: "(kept)",
      })),
      ...Object.entries(diff.added ?? {}).map(([key, value]) => ({
        key,
        current: "(missing)",
        proposed: JSON.stringify(value),
      })),
    ];
  }
  return Object.entries(obj).map(([key, value]) => ({
    key,
    current: "—",
    proposed: JSON.stringify(value),
  }));
}

function DiffPreviewPanel({
  diff,
  loading,
  confirming,
  adoptBusy,
  onClose,
  onConfirmStart,
  onConfirmCommit,
}: {
  diff: ApiObservedAssetDiffResponse | null;
  loading: boolean;
  confirming: "accept" | "reject" | null;
  adoptBusy: boolean;
  onClose: () => void;
  onConfirmStart: (mode: "accept" | "reject" | null) => void;
  onConfirmCommit: (mode: "accept" | "reject") => void;
}) {
  if (loading) {
    return <div className="adoption-panel"><span className="muted">正在加载 diff…</span></div>;
  }
  if (!diff) {
    return (
      <div className="adoption-panel">
        <span className="muted">暂无 diff 数据，请先确认该 case 有 passed run 和 observed 资产。</span>
        <button className="btn btn--outline" type="button" onClick={onClose}>关闭</button>
      </div>
    );
  }

  const { kept, added, missing } = diff.diff;
  return (
    <div className="adoption-panel" style={{ padding: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div>
          <strong>Diff 预览</strong>
          <span className="muted" style={{ marginLeft: 8 }}>
            run: {diff.run_id} · observed_at: {diff.observed_at || "—"}
          </span>
        </div>
        <button className="btn btn--outline" type="button" onClick={onClose} disabled={adoptBusy}>关闭</button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
        <DiffSection title="保留 (kept)" tone="green" data={kept} />
        <DiffSection title="新增 (added)" tone="blue" data={added} />
        <div>
          <strong>缺失 (missing)</strong>
          {missing.length ? (
            <ul style={{ color: "#c0392b", marginTop: 4 }}>
              {missing.map((item) => <li key={item}>{item}</li>)}
            </ul>
          ) : (
            <p className="muted" style={{ marginTop: 4 }}>无</p>
          )}
        </div>
      </div>
      <div className="button-row" style={{ marginTop: 12 }}>
        {confirming === "accept" ? (
          <>
            <span style={{ color: "#c0392b" }}>确认采纳？将覆盖 YAML 并写入 asset_adoptions。</span>
            <button className="btn btn--green" type="button" disabled={adoptBusy} onClick={() => onConfirmCommit("accept")}>
              确认采纳
            </button>
            <button className="btn btn--outline" type="button" disabled={adoptBusy} onClick={() => onConfirmStart(null)}>
              取消
            </button>
          </>
        ) : confirming === "reject" ? (
          <>
            <span style={{ color: "#c0392b" }}>确认拒绝？将只记录拒绝痕迹，不改 YAML。</span>
            <button className="btn btn--outline" type="button" disabled={adoptBusy} onClick={() => onConfirmCommit("reject")}>
              确认拒绝
            </button>
            <button className="btn btn--outline" type="button" disabled={adoptBusy} onClick={() => onConfirmStart(null)}>
              取消
            </button>
          </>
        ) : (
          <>
            <button className="btn btn--green" type="button" disabled={adoptBusy} onClick={() => onConfirmStart("accept")}>
              采纳
            </button>
            <button className="btn btn--outline" type="button" disabled={adoptBusy} onClick={() => onConfirmStart("reject")}>
              拒绝
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function DiffSection({
  title,
  tone,
  data,
}: {
  title: string;
  tone: "green" | "blue";
  data: Record<string, unknown> | undefined;
}) {
  const safeData = data ?? {};
  const keys = Object.keys(safeData);
  return (
    <div>
      <StatusPill tone={tone}>{title}</StatusPill>
      {keys.length === 0 ? (
        <p className="muted" style={{ marginTop: 4 }}>无</p>
      ) : (
        <ul style={{ marginTop: 4, paddingLeft: 16 }}>
          {keys.map((key) => (
            <li key={key}>
              <code>{key}</code>: <pre style={{ display: "inline", whiteSpace: "pre-wrap" }}>{JSON.stringify(safeData[key], null, 0)}</pre>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StabilityBadge({ stability }: { stability: ApiStability | null }) {
  if (!stability) {
    return <span className="muted">—</span>;
  }
  const { status, total, passed, pass_rate, last_passed_at, thresholds, window } = stability;
  const ratePercent = `${Math.round(pass_rate * 100)}%`;
  let label = "";
  let tone: "green" | "amber" | "red" | "dark" = "dark";
  if (status === "stable") {
    label = `稳定 ${ratePercent}`;
    tone = "green";
  } else if (status === "flaky") {
    label = `偶发 ${ratePercent}`;
    tone = "amber";
  } else if (status === "unstable") {
    label = `不稳 ${ratePercent}`;
    tone = "red";
  } else {
    label = "数据不足";
  }
  const tooltip =
    `基于最近 ${window} 次执行：${passed}/${total} passed (pass_rate=${ratePercent})\n` +
    `阈值：稳定 >= ${Math.round(thresholds.stable * 100)}% / 不稳 < ${Math.round(thresholds.unstable * 100)}%\n` +
    `最近一次通过：${last_passed_at || "—"}`;
  return (
    <span title={tooltip} style={{ cursor: "help" }}>
      <StatusPill tone={tone}>{label}</StatusPill>
    </span>
  );
}
