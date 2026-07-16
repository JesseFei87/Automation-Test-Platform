import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Card } from "../components/Card";
import { StatusPill } from "../components/StatusPill";
import {
  api,
  type ApiCase,
  type ApiCaseDetail,
  type CaseDraft,
  type CaseDraftValidation,
  type PlatformSettings,
  type Project,
  type Requirement,
} from "../data/api";

type DetailMode = "draft" | "formal";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "unknown error";
}

function readYamlScalar(yaml: string, key: string) {
  const pattern = new RegExp(`^${key}:\\s*(.+)$`, "mi");
  const match = pattern.exec(yaml);
  return match ? match[1].trim().replace(/^['"]|['"]$/g, "") : "";
}

function draftTone(status: string): "green" | "amber" | "blue" {
  const tones: Record<string, "green" | "amber" | "blue"> = {
    promoted: "green",
    draft: "amber",
  };
  return tones[status] || "blue";
}

function defaultCaseId(draft?: CaseDraft | null) {
  return draft?.promoted_case_id || readYamlScalar(draft?.yaml || "", "id") || "TC-ICM-013";
}

function defaultFilename(caseId: string) {
  return `${caseId.toLowerCase()}-generated.yaml`;
}

function formatTime(iso?: string | null) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function extractDraftMeta(draft: CaseDraft) {
  return {
    caseId: draft.promoted_case_id || readYamlScalar(draft.yaml, "id") || `draft #${draft.id}`,
    type: readYamlScalar(draft.yaml, "type") || "功能",
    priority: readYamlScalar(draft.yaml, "priority") || "P1",
    author: readYamlScalar(draft.yaml, "author") || "AI",
  };
}

function searchableDraftCaseId(draft: CaseDraft) {
  return draft.promoted_case_id || readYamlScalar(draft.yaml, "id");
}

type CaseActionIcon = "agent" | "mode" | "copy" | "delete";

function CaseActionSvg({ icon }: { icon: CaseActionIcon }) {
  const paths: Record<CaseActionIcon, ReactNode> = {
    agent: (
      <>
        <path d="M12 3v3" />
        <path d="M7 8h10a3 3 0 0 1 3 3v5a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4v-5a3 3 0 0 1 3-3Z" />
        <path d="M9 13h.01M15 13h.01M10 17h4" />
      </>
    ),
    mode: (
      <>
        <path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6Z" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
    copy: (
      <>
        <rect x="8" y="8" width="11" height="11" rx="2" />
        <path d="M5 15H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1" />
      </>
    ),
    delete: (
      <>
        <path d="M4 7h16" />
        <path d="M10 11v6M14 11v6" />
        <path d="M6 7l1 14h10l1-14" />
        <path d="M9 7V4h6v3" />
      </>
    ),
  };
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      {paths[icon]}
    </svg>
  );
}

export function CaseToolbox({ onRunCreated }: { onRunCreated?: (runId: string) => void }) {
  const [cases, setCases] = useState<ApiCase[]>([]);
  const [drafts, setDrafts] = useState<CaseDraft[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedDraftId, setSelectedDraftId] = useState<number | null>(null);
  const [selectedDraftIds, setSelectedDraftIds] = useState<number[]>([]);
  const [detailMode, setDetailMode] = useState<DetailMode>("draft");
  const [title, setTitle] = useState("");
  const [yaml, setYaml] = useState("");
  const [caseId, setCaseId] = useState("TC-ICM-013");
  const [filename, setFilename] = useState("tc-icm-013-generated.yaml");
  const [validation, setValidation] = useState<CaseDraftValidation | null>(null);
  const [keyword, setKeyword] = useState("");
  const [draftFilter, setDraftFilter] = useState<"all" | "draft" | "promoted">("all");
  const [selectedProjectId, setSelectedProjectId] = useState("all");
  const [selectedRequirementId, setSelectedRequirementId] = useState("all");
  const [startedDate, setStartedDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const [browserMode, setBrowserModeState] = useState<PlatformSettings["runner"]["browser_mode"]>("background");
  const [status, setStatus] = useState("正在读取用例资产...");

  const selectedDraft = useMemo(() => drafts.find((draft) => draft.id === selectedDraftId) || null, [drafts, selectedDraftId]);

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

  const selectedDraftIdSet = useMemo(() => new Set(selectedDraftIds), [selectedDraftIds]);

  const filteredDrafts = useMemo(() => {
    const query = keyword.trim().toLowerCase();
    return drafts.filter((draft) => {
      const requirement = requirementById.get(draft.requirement_id);
      const requirementProjectId = String(requirement?.project_id ?? "unassigned");
      const filters = [
        draftFilter === "all" || (draftFilter === "draft" ? !draft.promoted_case_id : Boolean(draft.promoted_case_id)),
        selectedRequirementId === "all" || String(draft.requirement_id) === selectedRequirementId,
        selectedProjectId === "all" || requirementProjectId === selectedProjectId,
        !startedDate || (draft.created_at?.slice(0, 10) || "") >= startedDate,
      ];
      const searchable = [searchableDraftCaseId(draft), draft.title]
        .join(" ")
        .toLowerCase();
      return filters.every(Boolean) && (!query || searchable.includes(query));
    });
  }, [draftFilter, drafts, keyword, requirementById, selectedProjectId, selectedRequirementId, startedDate]);

  const allVisibleSelected = filteredDrafts.length > 0 && filteredDrafts.every((draft) => selectedDraftIdSet.has(draft.id));

  function clearDetail() {
    setSelectedDraftId(null);
    setDetailMode("draft");
    setTitle("");
    setYaml("");
    setCaseId("TC-ICM-013");
    setFilename("tc-icm-013-generated.yaml");
    setValidation(null);
  }

  async function loadFormalCaseDetail(draft: CaseDraft) {
    if (!draft.promoted_case_id) return;
    const nextCaseId = draft.promoted_case_id;
    setDetailMode("formal");
    setTitle(draft.title);
    setYaml("正在读取正式用例故事...");
    setCaseId(nextCaseId);
    setFilename(draft.promoted_path ? draft.promoted_path.split(/[\\/]/).pop() || defaultFilename(nextCaseId) : defaultFilename(nextCaseId));
    try {
      const detail: ApiCaseDetail = await api.caseDetail(nextCaseId);
      setTitle(detail.title || draft.title);
      setYaml(detail.yaml);
      setCaseId(detail.id || nextCaseId);
      setFilename(detail.path.split(/[\\/]/).pop() || defaultFilename(detail.id || nextCaseId));
    } catch (error) {
      const fallbackCaseId = defaultCaseId(draft);
      setDetailMode("draft");
      setTitle(draft.title);
      setYaml(draft.yaml);
      setCaseId(fallbackCaseId);
      setFilename(defaultFilename(fallbackCaseId));
      setStatus(`读取正式用例失败，已回到草稿内容：${errorMessage(error)}`);
    }
  }

  function selectDraft(draft: CaseDraft) {
    setSelectedDraftId(draft.id);
    setValidation(null);
    if (draft.promoted_case_id) {
      void loadFormalCaseDetail(draft);
      return;
    }
    const nextCaseId = defaultCaseId(draft);
    setDetailMode("draft");
    setTitle(draft.title);
    setYaml(draft.yaml);
    setCaseId(nextCaseId);
    setFilename(draft.promoted_path ? draft.promoted_path.split(/[\\/]/).pop() || defaultFilename(nextCaseId) : defaultFilename(nextCaseId));
  }

  async function refresh(preferredDraftId?: number | null) {
    setBusy(true);
    try {
      const [caseResult, draftResult, requirementResult, projectResult, platformResult] = await Promise.all([
        api.cases(),
        api.caseDrafts(),
        api.requirements(),
        api.listProjects(),
        api.platformSettings(),
      ]);
      setCases(caseResult);
      setDrafts(draftResult);
      setRequirements(requirementResult);
      setProjects(projectResult);
      setBrowserModeState(platformResult.runner.browser_mode || "background");
      const next =
        (preferredDraftId ? draftResult.find((item) => item.id === preferredDraftId) : null) ||
        (selectedDraftId ? draftResult.find((item) => item.id === selectedDraftId) : null) ||
        draftResult[0] ||
        null;
      next ? selectDraft(next) : clearDetail();
      setStatus(`已加载 ${draftResult.length} 条用例。`);
    } catch (error) {
      setStatus(`读取用例资产失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function toggleDraftSelection(draftId: number) {
    setSelectedDraftIds((prev) => (prev.includes(draftId) ? prev.filter((id) => id !== draftId) : [...prev, draftId]));
  }

  function toggleSelectAllVisible() {
    setSelectedDraftIds((prev) => {
      if (allVisibleSelected) return prev.filter((id) => !filteredDrafts.some((draft) => draft.id === id));
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

  async function createBlankDraft() {
    setBusy(true);
    try {
      const requirementId = selectedRequirementId !== "all" ? Number(selectedRequirementId) : selectedDraft?.requirement_id ?? null;
      const draft = await api.createCaseDraft({
        requirement_id: typeof requirementId === "number" && Number.isFinite(requirementId) ? requirementId : null,
        title: "新增用例草稿",
        template: "manual",
      });
      setSelectedDraftIds([]);
      await refresh(draft.id);
      setStatus(`已新增用例草稿：#${draft.id}`);
    } catch (error) {
      setStatus(`新增用例失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft() {
    if (!selectedDraft) {
      setStatus("请先选择一条用例");
      return;
    }
    setBusy(true);
    try {
      const updated = await api.updateCaseDraft(selectedDraft.id, { title, yaml });
      setDrafts((items) => items.map((item) => (item.id === updated.id ? updated : item)));
      selectDraft(updated);
      setStatus(`草稿已保存：#${updated.id}`);
    } catch (error) {
      setStatus(`保存草稿失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function promoteDraft() {
    if (!selectedDraft) {
      setStatus("请先选择一条用例");
      return;
    }
    setBusy(true);
    try {
      const updated = await api.updateCaseDraft(selectedDraft.id, { title, yaml });
      const result = await api.validateCaseDraft(updated.id, { yaml, case_id: caseId });
      setValidation(result);
      if (!result.valid) {
        setStatus(`YAML 校验失败，已阻止转正式：${result.errors.join("；")}`);
        return;
      }
      const promoted = await api.promoteCaseDraft(updated.id, { case_id: caseId, filename });
      await refresh(promoted.id);
      setCases(await api.cases());
      setStatus(`已转正式 case：${promoted.promoted_case_id}`);
    } catch (error) {
      setStatus(`转正式 case 失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function runAgentExplore(draft: CaseDraft) {
    const targetLabel = defaultCaseId(draft) || `draft #${draft.id}`;
    setBusy(true);
    setStatus(`正在提交 Agent Explore：${targetLabel}，将按当前草稿最新内容执行...`);
    try {
      let sourceDraft = draft;
      if (draft.id === selectedDraftId && detailMode === "draft") {
        sourceDraft = await api.updateCaseDraft(draft.id, { title, yaml });
        setDrafts((items) => items.map((item) => (item.id === sourceDraft.id ? sourceDraft : item)));
        selectDraft(sourceDraft);
      }
      const task = await api.createRun("agent-explore", undefined, sourceDraft.id);
      setStatus(`已创建 Agent Explore 任务：${task.id}`);
      onRunCreated?.(task.id);
    } catch (error) {
      setStatus(`Agent Explore 提交失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function toggleAiExecutionMode() {
    setBusy(true);
    try {
      const current = await api.platformSettings();
      const nextMode = current.runner.browser_mode === "background" ? "visible" : "background";
      const updated = await api.savePlatformSettings({
        runner: {
          ...current.runner,
          browser_mode: nextMode,
          headless: nextMode === "background",
        },
      });
      setBrowserModeState(updated.runner.browser_mode || nextMode);
      setStatus(nextMode === "background" ? "AI 执行模式已切换为无头模式。" : "AI 执行模式已切换为有头模式。");
    } catch (error) {
      setStatus(`AI 执行模式切换失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function copyDraft(draft: CaseDraft) {
    setBusy(true);
    try {
      let sourceDraft = draft;
      if (draft.id === selectedDraftId && detailMode === "draft") {
        sourceDraft = await api.updateCaseDraft(draft.id, { title, yaml });
      }
      const copied = await api.createCaseDraft({
        requirement_id: sourceDraft.requirement_id,
        title: `${sourceDraft.title || "未命名用例"} - 副本`,
        yaml: sourceDraft.yaml,
        template: sourceDraft.template || "manual",
      });
      setSelectedDraftIds([]);
      await refresh(copied.id);
      setStatus(`已复制用例：#${copied.id}`);
    } catch (error) {
      setStatus(`复制用例失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteDraft(draft: CaseDraft) {
    const label = draft.promoted_case_id || `草稿 #${draft.id}`;
    if (!window.confirm(`是否确认删除 ${label}？`)) return;
    setBusy(true);
    try {
      await api.deleteCaseDraft(draft.id);
      setSelectedDraftIds((items) => items.filter((id) => id !== draft.id));
      await refresh(selectedDraftId === draft.id ? null : selectedDraftId);
      setStatus(`已删除用例：${label}`);
    } catch (error) {
      setStatus(`删除用例失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function batchDeleteSelected() {
    if (!selectedDraftIds.length) {
      setStatus("请先勾选至少一条用例");
      return;
    }
    if (!window.confirm(`是否确认删除选中的 ${selectedDraftIds.length} 条用例？`)) return;
    setBatchBusy(true);
    try {
      const result = await api.batchDeleteCaseDrafts(selectedDraftIds);
      const nextSelected = selectedDraftId && !selectedDraftIds.includes(selectedDraftId) ? selectedDraftId : null;
      setSelectedDraftIds([]);
      await refresh(nextSelected);
      setStatus(`批量删除完成：成功 ${result.deleted} 条，失败 ${result.failed} 条`);
    } catch (error) {
      setStatus(`批量删除失败：${errorMessage(error)}`);
    } finally {
      setBatchBusy(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const selectedFormalCase = selectedDraft?.promoted_case_id ? cases.find((item) => item.id === selectedDraft.promoted_case_id) || null : null;

  return (
    <div className="page case-toolbox-page">
      <div className="case-layout case-layout--wide">
        <Card className="case-table-card" title="用例记录" subtitle="按项目、需求和关键字筛选用例">
          <div className="case-filters">
            <label className="case-filter-field">
              <span>关键字</span>
              <input className="text-input" value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索用例ID / 标题" />
            </label>
            <label className="case-filter-field">
              <span>状态</span>
              <select className="case-filter-select" value={draftFilter} onChange={(event) => setDraftFilter(event.target.value as typeof draftFilter)}>
                <option value="all">全部</option>
                <option value="draft">草稿</option>
                <option value="promoted">已转正式</option>
              </select>
            </label>
            <label className="case-filter-field">
              <span>项目</span>
              <select className="case-filter-select" value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}>
                <option value="all">所有项目</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="case-filter-field">
              <span>需求</span>
              <select className="case-filter-select" value={selectedRequirementId} onChange={(event) => setSelectedRequirementId(event.target.value)}>
                <option value="all">所有需求</option>
                {requirements.map((requirement) => (
                  <option key={requirement.id} value={String(requirement.id)}>
                    {requirement.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="case-filter-field">
              <span>开始时间</span>
              <input className="text-input" type="date" value={startedDate} onChange={(event) => setStartedDate(event.target.value)} />
            </label>
            <div className="case-filter-actions">
              <button className="btn btn--primary" type="button" onClick={() => refresh()} disabled={busy || batchBusy}>
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
            <button className="btn btn--primary" type="button" disabled={batchBusy || busy} onClick={createBlankDraft}>
              新增用例
            </button>
            <button className="btn btn--outline" type="button" disabled={batchBusy || busy || !selectedDraftIds.length} onClick={batchDeleteSelected}>
              批量删除用例
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
                  <th>用例ID</th>
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
                  const requirement = requirementById.get(draft.requirement_id);
                  const projectName = requirement?.project_id ? projectById.get(String(requirement.project_id))?.name || "未匹配项目" : "未分配项目";
                  const formalCase = draft.promoted_case_id ? cases.find((item) => item.id === draft.promoted_case_id) || null : null;
                  return (
                    <tr key={draft.id} className={draft.id === selectedDraftId ? "is-selected-row" : undefined} onClick={() => selectDraft(draft)}>
                      <td onClick={(event) => event.stopPropagation()}>
                        <label className="case-row-check">
                          <input type="checkbox" checked={selectedDraftIdSet.has(draft.id)} onChange={() => toggleDraftSelection(draft.id)} />
                          <span>{index + 1}</span>
                        </label>
                      </td>
                      <td>
                        <strong>{meta.caseId}</strong>
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
                          <StatusPill tone={meta.priority === "P0" ? "red" : meta.priority === "P1" ? "amber" : "blue"}>{meta.priority}</StatusPill>
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
                          <button className="case-row-action case-row-action--agent" type="button" title="执行 Agent 模式" disabled={busy} onClick={() => void runAgentExplore(draft)}>
                            <CaseActionSvg icon="agent" />
                          </button>
                          <button
                            className={`case-row-action case-row-action--mode ${browserMode === "background" ? "is-headless" : "is-headed"}`}
                            type="button"
                            title={browserMode === "background" ? "当前无头模式，点击切换为有头模式" : "当前有头模式，点击切换为无头模式"}
                            disabled={busy || batchBusy}
                            onClick={() => void toggleAiExecutionMode()}
                          >
                            <CaseActionSvg icon="mode" />
                          </button>
                          <button className="case-row-action case-row-action--copy" type="button" title="复制当前用例" disabled={busy || batchBusy} onClick={() => void copyDraft(draft)}>
                            <CaseActionSvg icon="copy" />
                          </button>
                          <button className="case-row-action case-row-action--danger" type="button" title="删除当前用例" disabled={busy || batchBusy} onClick={() => void deleteDraft(draft)}>
                            <CaseActionSvg icon="delete" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {!filteredDrafts.length ? (
                  <tr>
                    <td colSpan={10}>当前筛选条件下没有用例。</td>
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
            title={detailMode === "formal" ? "正式用例故事" : "草稿内容"}
            subtitle={detailMode === "formal" ? "这里显示已沉淀正式用例的故事和回归入口。" : "这里显示草稿 YAML、质量校验和正式沉淀入口。"}
          >
            <label className="field-label" htmlFor="case-title-input">
              标题
            </label>
            <input id="case-title-input" className="text-input" value={title} onChange={(event) => setTitle(event.target.value)} disabled={!selectedDraft || detailMode === "formal"} />

            <div className="case-form-grid">
              <label className="field-label" htmlFor="case-id-input">
                用例ID
                <input id="case-id-input" className="text-input" value={caseId} onChange={(event) => setCaseId(event.target.value)} disabled={!selectedDraft || detailMode === "formal"} />
              </label>
              <label className="field-label" htmlFor="case-filename-input">
                文件名
                <input id="case-filename-input" className="text-input" value={filename} onChange={(event) => setFilename(event.target.value)} disabled={!selectedDraft || detailMode === "formal"} />
              </label>
            </div>

            <textarea className="text-input case-detail-editor" value={yaml} onChange={(event) => setYaml(event.target.value)} disabled={!selectedDraft || detailMode === "formal"} />

            {selectedDraft ? (
              <div className="selected-summary">
                <StatusPill tone={draftTone(selectedDraft.status)}>{selectedDraft.status}</StatusPill>
                {selectedDraft.promoted_case_id ? <StatusPill tone="green">已沉淀</StatusPill> : null}
                {selectedFormalCase?.has_automation_asset ? <StatusPill tone="blue">有自动化资产</StatusPill> : null}
              </div>
            ) : null}

            {validation ? (
              <div className={`validation-box ${validation.valid ? "validation-box--ok" : "validation-box--error"}`}>
                <strong>{validation.valid ? "校验通过" : "校验未通过"}</strong>
                {validation.errors.map((item) => (
                  <p key={item}>{item}</p>
                ))}
                {validation.warnings.map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            ) : null}

            <div className="button-row">
              <button className="btn btn--outline" type="button" disabled={!selectedDraft || busy || detailMode === "formal"} onClick={saveDraft}>
                保存草稿
              </button>
              <button className="btn btn--primary" type="button" disabled={!selectedDraft || busy || detailMode === "formal"} onClick={promoteDraft}>
                转正式
              </button>
              <button className="btn btn--outline" type="button" title="按当前草稿最新内容执行 Agent Explore" disabled={!selectedDraft || busy} onClick={() => selectedDraft && void runAgentExplore(selectedDraft)}>
                AG
              </button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
