import { useEffect, useMemo, useRef, useState } from "react";
import MindElixir from "mind-elixir";
import "mind-elixir/style.css";

import { Card } from "../components/Card";
import { useConfirm } from "../components/ConfirmDialog";
import { parseRequirementFile, RequirementDocumentInput } from "../components/RequirementDocumentInput";
import { StatusPill } from "../components/StatusPill";
import { useToast } from "../components/Toast";
import { api, type AISettings, type CaseDraft, type ContextInfo, type Project, type Requirement, type RequirementDetail } from "../data/api";

type CoverageFocus = "balanced" | "normal" | "abnormal_boundary" | "permission_security";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "unknown error";
}

function createGenerationId() {
  return `generation-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function safeCount(value: number | null | undefined) {
  return typeof value === "number" ? value : 0;
}

function formatSecondTime(value?: string | null) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function initialWorkspaceState() {
  return {
    title: "",
    document: "",
  };
}

// ---- XMind 导出：Canvas 2D 手画脑图 PNG（不引入新依赖） ----
function buildLegacyMindPngBlob(drafts: CaseDraft[]): Promise<Blob> {
  return new Promise((resolve, reject) => {
    if (!drafts.length) {
      reject(new Error("没有可导出的用例"));
      return;
    }
    const padding = 24;
    const nodeH = 36;
    const nodeW = 240;
    const gapY = 12;
    const gapX = 16;
    const rootW = 200;
    const rootH = 56;
    const rootGap = 80;
    const cols = 3;
    const rows = Math.ceil(drafts.length / cols);

    const canvas = document.createElement("canvas");
    canvas.width = padding * 2 + rootGap + rootW + cols * nodeW + (cols - 1) * gapX;
    canvas.height = padding * 2 + rootH + 20 + rows * (nodeH + gapY);

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      reject(new Error("当前浏览器不支持 Canvas 2D"));
      return;
    }

    // 背景
    ctx.fillStyle = "#FFFFFF";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const rootX = padding;
    const rootY = padding;
    drawNode(ctx, rootX, rootY, rootW, rootH, "测试用例集", "#1F6FEB", "#FFFFFF", true);

    drafts.forEach((draft, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const x = padding + rootGap + rootW + col * (nodeW + gapX);
      const y = padding + rootH + 20 + row * (nodeH + gapY);
      const title = (draft.title || `draft #${draft.id}`).slice(0, 16);
      const tone = String(draft.status || "").toLowerCase() === "draft" ? "#F59E0B" : "#10B981";
      drawNode(ctx, x, y, nodeW, nodeH, title, "#F8FAFC", "#1F2329", false, tone);

      // 连线
      ctx.strokeStyle = "#D0D7DE";
      ctx.lineWidth = 1.2;
      const startX = rootX + rootW;
      const startY = rootY + rootH / 2;
      const endX = x;
      const endY = y + nodeH / 2;
      const midX = (startX + endX) / 2;
      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.lineTo(midX, startY);
      ctx.lineTo(midX, endY);
      ctx.lineTo(endX, endY);
      ctx.stroke();
    });

    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("Canvas 导出失败"));
    }, "image/png");
  });
}

function drawNode(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  text: string,
  bg: string,
  fg: string,
  isRoot: boolean,
  accent?: string,
) {
  ctx.fillStyle = bg;
  ctx.strokeStyle = isRoot ? "transparent" : accent || "#1F6FEB";
  ctx.lineWidth = isRoot ? 0 : 1.5;
  const r = 6;
  const hasRoundRect = typeof (ctx as unknown as { roundRect?: () => void }).roundRect === "function";
  if (hasRoundRect) {
    ctx.beginPath();
    (ctx as unknown as { roundRect: (x: number, y: number, w: number, h: number, r: number) => void }).roundRect(
      x,
      y,
      w,
      h,
      r,
    );
    ctx.fill();
    ctx.stroke();
  } else {
    ctx.fillRect(x, y, w, h);
  }

  ctx.fillStyle = fg;
  ctx.font = isRoot ? "600 14px system-ui, -apple-system, sans-serif" : "13px system-ui, -apple-system, sans-serif";
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";
  ctx.fillText(text, x + w / 2, y + h / 2, w - 16);
}

// ---- XMind 导出：Markdown 大纲（可被 XMind / 幕布 / 任何脑图工具打开） ----
function buildMindMarkdown(drafts: CaseDraft[]): string {
  if (!drafts.length) return "# 测试用例集\n\n（无用例）\n";
  const lines: string[] = ["# 测试用例集", ""];
  drafts.forEach((draft, i) => {
    const title = draft.title || `draft #${draft.id}`;
    lines.push(`## ${i + 1}. ${title}`);
    lines.push("");
    lines.push(`- **ID**: ${draft.id}`);
    lines.push(`- **状态**: ${draft.status}`);
    lines.push(`- **更新时间**: ${draft.updated_at}`);
    lines.push(`- **模板**: ${draft.template || "spec"}`);
    lines.push("");
  });
  return lines.join("\n");
}

type ExportMindNode = {
  id: string;
  topic: string;
  expanded?: boolean;
  tags?: string[];
  style?: Record<string, string>;
  children?: ExportMindNode[];
};

type ExportMindData = {
  nodeData: ExportMindNode;
};

type MindExportGroupMode = "type" | "priority";

function readDraftYamlField(draft: CaseDraft, field: MindExportGroupMode) {
  const match = draft.yaml.match(new RegExp(`^${field}:\\s*(.+)$`, "im"));
  return match?.[1]?.trim().replace(/^['"]|['"]$/g, "") || "";
}

function groupDraftsForMind(drafts: CaseDraft[], mode: MindExportGroupMode) {
  const fallback = mode === "type" ? "未标注功能类型" : "未标注优先级";
  const groups = new Map<string, CaseDraft[]>();
  drafts.forEach((draft) => {
    const key = readDraftYamlField(draft, mode) || fallback;
    groups.set(key, [...(groups.get(key) || []), draft]);
  });
  return [...groups.entries()].sort(([left], [right]) => left.localeCompare(right, "zh-Hans-CN"));
}

function buildExportMindData(drafts: CaseDraft[], requirementTitle: string, mode: MindExportGroupMode): ExportMindData {
  const groupLabel = mode === "type" ? "按功能类型" : "按优先级";
  return {
    nodeData: {
      id: "root",
      topic: `${requirementTitle || "测试用例集"} - ${groupLabel} (${drafts.length})`,
      expanded: true,
      children: groupDraftsForMind(drafts, mode).map(([groupName, groupDrafts]) => ({
        id: `group-${mode}-${encodeURIComponent(groupName)}`,
        topic: `${groupName} (${groupDrafts.length})`,
        expanded: true,
        tags: [groupLabel],
        style:
          mode === "priority"
            ? { color: "var(--amber)", background: "var(--amber-soft)", border: "1px solid var(--amber)" }
            : { color: "var(--blue)", background: "var(--blue-soft)", border: "1px solid var(--blue)" },
        children: groupDrafts.map((draft, index) => ({
          id: `draft-${draft.id}`,
          topic: `${index + 1}. ${draft.title || `draft #${draft.id}`}`,
          tags: [String(draft.status || "draft")],
          style:
            String(draft.status || "").toLowerCase() === "draft"
              ? { color: "var(--amber)", background: "var(--amber-soft)", border: "1px solid var(--amber)" }
              : { color: "var(--green)", background: "var(--green-soft)", border: "1px solid var(--green)" },
        })),
      })),
    },
  };
}

async function buildMindPngBlob(drafts: CaseDraft[], requirementTitle: string, mode: MindExportGroupMode): Promise<Blob> {
  if (!drafts.length) throw new Error("没有可导出的用例");
  const host = document.createElement("div");
  host.style.position = "fixed";
  host.style.left = "-10000px";
  host.style.top = "0";
  host.style.width = "1200px";
  host.style.height = "800px";
  document.body.appendChild(host);
  const mind = new (MindElixir as any)({
    el: host,
    direction: (MindElixir as any).SIDE || 2,
    draggable: false,
    contextMenu: false,
    toolBar: false,
    nodeMenu: false,
    keypress: false,
  });
  try {
    mind.init(buildExportMindData(drafts, requirementTitle, mode));
    await new Promise((resolve) => window.setTimeout(resolve, 120));
    mind.scaleFit?.();
    await new Promise((resolve) => window.setTimeout(resolve, 80));
    const png = await mind.exportPng?.();
    if (png instanceof Blob) return png;
    if (typeof png === "string") {
      const response = await fetch(png);
      return response.blob();
    }
    throw new Error("Mind Elixir PNG 导出失败");
  } finally {
    mind.destroy?.();
    host.remove();
  }
}

export function RequirementsWorkspace() {
  const confirm = useConfirm();
  const toast = useToast();
  const generationControllerRef = useRef<AbortController | null>(null);
  const generationIdRef = useRef<string | null>(null);
  const [title, setTitle] = useState(initialWorkspaceState().title);
  const [document, setDocument] = useState(initialWorkspaceState().document);
  const [linkedRequirementId, setLinkedRequirementId] = useState<number | null>(null);
  const [settings, setSettings] = useState<AISettings | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [detail, setDetail] = useState<RequirementDetail | null>(null);
  const [selectedDraftId, setSelectedDraftId] = useState<number | null>(null);
  const [status, setStatus] = useState("正在连接需求工作台...");
  const [busy, setBusy] = useState(false);
  const [parsingDocument, setParsingDocument] = useState(false);
  const [caseCount, setCaseCount] = useState(12);
  const [coverageFocus, setCoverageFocus] = useState<CoverageFocus>("balanced");
  const [xmindMenuOpen, setXmindMenuOpen] = useState(false);

  // ---- P0 · 所属项目下拉化（增量 2026-06-10）----
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [showNewProjectDialog, setShowNewProjectDialog] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectBaseUrl, setNewProjectBaseUrl] = useState("");
  const [newProjectError, setNewProjectError] = useState<string | null>(null);
  const [newProjectBusy, setNewProjectBusy] = useState(false);

  // 可选生成约束，默认折叠且不保存账号凭据。
  const [contextFields, setContextFields] = useState<ContextInfo>({
    business_preconditions: "",
    excluded: "",
  });
  const [showContextFields, setShowContextFields] = useState<boolean>(false);

  // 用 ref 维持项目列表 cache key，避免 useEffect 死循环
  const projectsLoadedRef = useRef(false);

  const requirement = detail?.requirement ?? null;
  const drafts = detail?.drafts ?? [];
  const promotedCount = drafts.filter((item) => item.status === "promoted").length;
  const draftCount = drafts.filter((item) => item.status === "draft").length;
  const selectedDraft =
    drafts.find((item) => item.id === selectedDraftId) ?? drafts[0] ?? null;
  const canAnalyze = useMemo(
    () => title.trim().length > 0 && document.trim().length > 0 && Boolean(projectId) && !parsingDocument,
    [document, parsingDocument, projectId, title],
  );

  function resetWorkspace(message?: string) {
    const initial = initialWorkspaceState();
    setDetail(null);
    setSelectedDraftId(null);
    setLinkedRequirementId(null);
    setTitle(initial.title);
    setDocument(initial.document);
    if (message) {
      setStatus(message);
    }
  }

  useEffect(() => {
    void loadInitialData();
  }, []);

  // P0 · 加载项目档案（id / name / base_url / description）
  useEffect(() => {
    if (projectsLoadedRef.current) return;
    projectsLoadedRef.current = true;
    void loadProjects();
  }, []);

  async function loadProjects(): Promise<Project[]> {
    try {
      const items = await api.listProjects();
      setProjects(items);
      return items;
    } catch (error) {
      setStatus(`项目档案加载失败：${errorMessage(error)}`);
      return [];
    }
  }

  // P0 · "+ 新建项目" Dialog 提交：name inline 去重 + 后端 409 双保险
  async function submitNewProject() {
    const trimmedName = newProjectName.trim();
    if (!trimmedName) {
      setNewProjectError("项目名不能为空");
      return;
    }
    // 前端 inline 去重
    if (projects.some((p) => p.name === trimmedName)) {
      setNewProjectError(`项目名"${trimmedName}"已存在，请换一个名字`);
      return;
    }
    setNewProjectBusy(true);
    setNewProjectError(null);
    try {
      const created = await api.createProject({
        name: trimmedName,
        base_url: newProjectBaseUrl.trim() || null,
      });
      // 重新拉取全量并选中新建项
      const items = await loadProjects();
      const next = items.find((p) => p.id === created.id) || created;
      setProjectId(next.id);
      setShowNewProjectDialog(false);
      setNewProjectName("");
      setNewProjectBaseUrl("");
      setStatus(`已新建项目：${next.name}（${next.id}）`);
    } catch (error) {
      // 409 / 400 双保险（即使前端去重漏了，后端也会拒）
      setNewProjectError(errorMessage(error));
    } finally {
      setNewProjectBusy(false);
    }
  }

  // 点击页面其他位置关闭 XMind 下拉
  useEffect(() => {
    if (!xmindMenuOpen) return;
    function handleClick(event: MouseEvent) {
      const target = event.target as HTMLElement | null;
      if (target && !target.closest(".dropdown")) {
        setXmindMenuOpen(false);
      }
    }
    const doc = window.document;
    doc.addEventListener("mousedown", handleClick);
    return () => doc.removeEventListener("mousedown", handleClick);
  }, [xmindMenuOpen]);

  async function loadInitialData() {
    try {
      const [aiSettings, items] = await Promise.all([api.aiSettings(), api.requirements()]);
      setSettings(aiSettings);
      setRequirements(items);
      setStatus(`当前模型：${aiSettings.provider} / ${aiSettings.model}`);
    } catch (error) {
      setStatus(`读取失败：${errorMessage(error)}`);
    }
  }

  async function refreshRequirements(selectId?: number) {
    const items = await api.requirements();
    setRequirements(items);
    if (typeof selectId === "number") {
      if (items.some((item) => item.id === selectId)) {
        await openRequirement(selectId);
      } else {
        resetWorkspace("当前需求已删除，页面已重置。");
      }
      return;
    }
    resetWorkspace("需求已删除，页面已重置。");
  }

  async function openRequirement(id: number) {
    setBusy(true);
    try {
      const result = await api.requirementDetail(id);
      setDetail(result);
      setLinkedRequirementId(id);
      setTitle(result.requirement.title);
      setDocument(result.requirement.document);
      setProjectId(result.requirement.project_id ?? null);
      setSelectedDraftId(result.drafts[0]?.id ?? null);
      setStatus(`已打开需求：${result.requirement.title}`);
    } catch (error) {
      setStatus(`读取需求失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function handleLinkedRequirementChange(value: string) {
    const nextId = value ? Number(value) : null;
    setLinkedRequirementId(nextId);
    if (!nextId) {
      setProjectId(null);
      resetWorkspace("未关联已有需求，点击开始生成后再显示生成结果。");
      return;
    }
    void openRequirement(nextId);
  }

  async function analyze() {
    if (!canAnalyze) {
      setStatus("请先选择所属项目，并填写需求标题和需求正文。");
      return;
    }
    const controller = new AbortController();
    const generationId = createGenerationId();
    generationControllerRef.current = controller;
    generationIdRef.current = generationId;
    setBusy(true);
    setStatus("正在按规范生成测试用例...");
    try {
      const cleanContext = Object.fromEntries(
        Object.entries(contextFields).map(([key, value]) => [key, value?.trim()]).filter(([, value]) => value),
      ) as ContextInfo;
      const payload = {
        title: title.trim(),
        document: document,
        context_info: Object.keys(cleanContext).length ? cleanContext : undefined,
        project_id: projectId,
        requirement_id: linkedRequirementId,
        generation_id: generationId,
        case_count: caseCount,
        coverage_focus: coverageFocus,
      };
      const result = await api.analyzeRequirementSpec(payload, controller.signal);
      setDetail(result);
      setLinkedRequirementId(result.requirement.id);
      setRequirements(await api.requirements());
      setSelectedDraftId(result.drafts[0]?.id ?? null);
      setStatus(`已生成 ${result.generated_cases ?? result.drafts.length} 条测试用例草稿。`);
    } catch (error) {
      setStatus(controller.signal.aborted ? "已停止生成，未保存用例草稿。" : `分析失败：${errorMessage(error)}`);
    } finally {
      if (generationControllerRef.current === controller) {
        generationControllerRef.current = null;
        generationIdRef.current = null;
        setBusy(false);
      }
    }
  }

  async function stopGeneration() {
    const controller = generationControllerRef.current;
    const generationId = generationIdRef.current;
    if (!controller || !generationId) return;

    try {
      const result = await api.stopRequirementGeneration(generationId);
      if (result.status !== "cancellation_requested") {
        setStatus("生成已进入保存阶段，正在加载结果。");
        return;
      }
      controller.abort();
      setStatus("已停止生成，未保存用例草稿。");
    } catch (error) {
      setStatus(`停止失败：${errorMessage(error)}`);
    }
  }

  async function handleUpload(file: File | null) {
    if (!file) return;
    setParsingDocument(true);
    setStatus(`正在解析文档：${file.name}`);
    try {
      const parsed = await parseRequirementFile(file);
      setDocument(parsed.text);
      setTitle((prev) => (prev.trim() ? prev : parsed.title));
      setStatus(`已解析 ${file.name}，请确认正文后开始生成。`);
    } catch (error) {
      setStatus(`文档解析失败：${errorMessage(error)}`);
    } finally {
      setParsingDocument(false);
    }
  }

  async function handleDeleteRequirement(item: Requirement) {
    const ok = await confirm({
      title: `确认删除需求“${item.title}”？`,
      description: `关联的 ${safeCount(item.draft_count ?? item.case_count)} 个用例草稿也会被清理。删除后无法恢复。`,
      danger: true,
      confirmText: "确认删除",
    });
    if (!ok) return;

    setBusy(true);
    try {
      const result = await api.deleteRequirement(item.id);
      setStatus(
        `已删除"${result.title}"：清理 ${result.deleted_case_drafts} 个用例草稿。`,
      );
      const keepId = requirement?.id === item.id ? undefined : requirement?.id;
      await refreshRequirements(keepId);
      toast.show({ kind: "success", message: "需求删除成功" });
    } catch (error) {
      setStatus(`删除失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function exportCases(format: "xlsx" | "yaml") {
    if (!requirement) {
      setStatus("请先打开一条需求记录。");
      return;
    }

    setBusy(true);
    try {
      const { blob, filename } = await api.exportRequirementCases(requirement.id, format);
      downloadBlob(blob, filename || `cases-${requirement.id}.${format}`);
      setStatus(`已导出 ${format.toUpperCase()}：${requirement.title}`);
    } catch (error) {
      setStatus(`导出失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleXmindPngExport(mode: MindExportGroupMode) {
    if (!requirement || !drafts.length) {
      setStatus("请先打开一条需求并生成用例。");
      return;
    }
    setXmindMenuOpen(false);
    setBusy(true);
    try {
      const blob = await buildMindPngBlob(drafts, requirement.title, mode);
      const safeName = (requirement.title || `req-${requirement.id}`).replace(/[\\/:*?"<>|]/g, "_");
      downloadBlob(blob, `${safeName}-mindmap-${mode}.png`);
      setStatus(`已导出脑图 PNG：${requirement.title}`);
    } catch (error) {
      setStatus(`导出失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleXmindMarkdownExport() {
    if (!requirement || !drafts.length) {
      setStatus("请先打开一条需求并生成用例。");
      return;
    }
    setXmindMenuOpen(false);
    setBusy(true);
    try {
      const md = buildMindMarkdown(drafts);
      const safeName = (requirement.title || `req-${requirement.id}`).replace(/[\\/:*?"<>|]/g, "_");
      downloadBlob(
        new Blob([md], { type: "text/markdown;charset=utf-8" }),
        `${safeName}-mindmap.md`,
      );
      setStatus(`已导出脑图 Markdown：${requirement.title}`);
    } catch (error) {
      setStatus(`导出失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleImportToCaseLibrary() {
    if (!drafts.length) {
      setStatus("暂无可导入的用例。");
      return;
    }
    setStatus("用例库导入：即将支持（需配合用例库后端接口落地）。");
  }

  function handleCopy() {
    if (!selectedDraft) {
      setStatus("暂无可复制的用例，请先生成并选择一条。");
      return;
    }
    void navigator.clipboard.writeText(selectedDraft.yaml).then(
      () => setStatus(`已复制 YAML 到剪贴板（草稿 #${selectedDraft.id}）。`),
      (error) => setStatus(`复制失败：${errorMessage(error)}`),
    );
  }

  function handleClear() {
    if (window.confirm("确认清空当前结果？历史需求不会被删除。")) {
      setDetail(null);
      setSelectedDraftId(null);
      setStatus("已清空当前结果。");
    }
  }

  const modelLabel = settings ? `${settings.provider} / ${settings.model}` : "模型读取中...";

  return (
    <div className="page requirements-page">
      <style>{`
        .page-header {
          margin-bottom: 20px;
        }
        .page-header h1 {
          font-size: 22px;
          font-weight: 600;
          margin: 0 0 6px 0;
        }
        .page-header p {
          color: var(--muted);
          font-size: 13px;
          margin: 0;
        }

        .requirements-layout {
          display: grid;
          grid-template-columns: minmax(360px, 1fr) minmax(520px, 1.4fr);
          gap: 20px;
          align-items: stretch;
        }

        .requirements-left,
        .requirements-right {
          display: grid;
          gap: 20px;
          align-content: stretch;
          align-items: stretch;
          min-width: 0;
        }

        .generation-options {
          display: grid;
          grid-template-columns: minmax(120px, 0.6fr) minmax(180px, 1fr);
          gap: 12px;
        }

        .requirements-input-card,
        .requirements-result-card {
          display: flex;
          flex-direction: column;
          height: 100%;
          min-height: 760px;
        }

        .dropdown {
          position: relative;
          display: inline-block;
        }
        .dropdown__menu {
          position: absolute;
          top: calc(100% + 4px);
          right: 0;
          background: var(--card);
          border: 1px solid var(--line);
          border-radius: 6px;
          box-shadow: var(--shadow);
          min-width: 200px;
          z-index: 10;
          padding: 4px 0;
          list-style: none;
          margin: 0;
        }
        .dropdown__item {
          display: block;
          width: 100%;
          text-align: left;
          background: transparent;
          border: none;
          padding: 8px 12px;
          font-size: 13px;
          cursor: pointer;
          color: var(--text);
        }
        .dropdown__item:hover {
          background: var(--surface-hover, var(--soft));
        }
        .dropdown__item[disabled] {
          color: var(--muted);
          cursor: not-allowed;
        }

        .requirements-result-toolbar {
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 12px;
          margin-bottom: 14px;
        }
        .requirements-import-placeholder {
          display: none;
        }
        .requirements-result-toolbar__main,
        .requirements-result-toolbar__side {
          display: flex;
          align-items: center;
          flex-wrap: wrap;
          gap: 8px;
        }
        .requirements-result-toolbar .btn {
          min-height: 36px;
          padding: 0 14px;
          font-size: 13px;
        }
        .requirements-result-meta {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          min-height: 36px;
          margin-bottom: 12px;
          padding: 0 12px;
          color: var(--muted);
          border: 1px solid var(--line);
          border-radius: 8px;
          background: var(--soft);
          font-size: 12px;
          font-weight: 700;
        }
        .requirements-result-grid {
          display: grid;
          grid-template-columns: minmax(260px, 0.9fr) minmax(420px, 1.35fr);
          align-items: stretch;
          gap: 16px;
          flex: 1;
          min-height: 560px;
        }
        .requirements-draft-list,
        .requirements-draft-preview {
          min-width: 0;
          border: 1px solid var(--line);
          border-radius: 8px;
          background: var(--card);
          overflow: hidden;
        }
        .requirements-draft-list {
          display: grid;
          grid-template-rows: auto minmax(0, 1fr);
        }
        .requirements-draft-list__head {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 92px;
          gap: 10px;
          padding: 12px 14px;
          color: var(--muted);
          border-bottom: 1px solid var(--line);
          background: var(--soft);
          font-size: 12px;
          font-weight: 800;
        }
        .requirements-draft-list__body {
          min-height: 0;
          overflow-y: auto;
          overflow-x: hidden;
        }
        .requirements-draft-row {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          align-items: center;
          gap: 10px;
          width: 100%;
          min-height: 54px;
          padding: 10px 14px;
          color: var(--text);
          border: 0;
          border-bottom: 1px solid var(--line);
          background: var(--card);
          text-align: left;
          cursor: pointer;
        }
        .requirements-draft-row:hover {
          background: var(--soft);
        }
        .requirements-draft-row.is-active {
          background: var(--blue-soft);
          box-shadow: inset 3px 0 0 var(--blue);
        }
        .requirements-draft-row__title {
          overflow: hidden;
          font-size: 13px;
          font-weight: 800;
          line-height: 1.35;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .requirements-draft-preview {
          display: grid;
          grid-template-rows: auto 1fr;
          background: var(--soft);
        }
        .requirements-draft-preview__header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 16px;
          padding: 18px 18px 14px;
          border-bottom: 1px solid var(--line);
          background: var(--card);
        }
        .requirements-draft-preview__header h4 {
          margin: 0 0 8px;
          color: var(--text);
          font-size: 18px;
          line-height: 1.35;
        }
        .requirements-draft-preview__header p {
          margin: 0;
          color: var(--muted);
          font-size: 12px;
          line-height: 1.5;
        }
        .requirements-draft-preview pre {
          min-height: 0;
          margin: 0;
          padding: 18px;
          overflow: auto;
          color: #e6edf7;
          background:
            radial-gradient(circle at 12% 0%, rgba(37, 99, 235, 0.22), transparent 34%),
            radial-gradient(circle at 92% 12%, rgba(16, 185, 129, 0.14), transparent 30%),
            linear-gradient(145deg, #07111f 0%, #0b1324 48%, #020617 100%);
          border-top: 1px solid rgba(148, 163, 184, 0.18);
          font-size: 13px;
          line-height: 1.58;
          white-space: pre-wrap;
          word-break: break-word;
          scrollbar-color: rgba(96, 165, 250, 0.65) rgba(15, 23, 42, 0.85);
        }
        .requirements-empty-result {
          display: grid;
          min-height: 180px;
          place-items: center;
          padding: 24px;
          color: var(--muted);
          font-size: 13px;
          text-align: center;
        }

        .requirements-status-line {
          color: var(--muted);
          font-size: 13px;
          line-height: 1.6;
          margin-top: 12px;
        }

        @media (max-width: 1080px) {
          .requirements-layout {
            grid-template-columns: 1fr;
          }
        }
        @media (max-width: 860px) {
          .requirements-result-grid {
            grid-template-columns: 1fr;
          }
        }

        /* ============================================================
           深色模式补强：RequirementsWorkspace 自定义块的暗色适配
           （跟随 <html data-theme="dark">）
           ============================================================ */
        :root[data-theme="dark"] .dropdown__menu {
          background: var(--card);
          border-color: var(--border-strong, #31415c);
        }
        :root[data-theme="dark"] .dropdown__item {
          color: var(--text);
        }
        :root[data-theme="dark"] .dropdown__item:hover {
          background: var(--surface-hover, #253451);
        }
        :root[data-theme="dark"] .requirements-result-meta {
          background: var(--surface-2, #1d2940);
          border-color: var(--border-strong, #31415c);
          color: var(--muted);
        }
        :root[data-theme="dark"] .requirements-draft-list,
        :root[data-theme="dark"] .requirements-draft-preview {
          background: var(--card);
          border-color: var(--border-strong, #31415c);
        }
        :root[data-theme="dark"] .requirements-draft-list__head {
          background: var(--surface-2, #1d2940);
          border-bottom-color: var(--border-strong, #31415c);
          color: var(--muted);
        }
        :root[data-theme="dark"] .requirements-draft-row {
          background: var(--card);
          border-bottom-color: var(--border-soft, #273349);
          color: var(--text);
        }
        :root[data-theme="dark"] .requirements-draft-row:hover {
          background: var(--surface-hover, #253451);
        }
        :root[data-theme="dark"] .requirements-draft-row.is-active {
          background: var(--blue-soft);
          box-shadow: inset 3px 0 0 var(--blue);
        }
        :root[data-theme="dark"] .requirements-draft-preview {
          background: var(--soft);
        }
        :root[data-theme="dark"] .requirements-draft-preview__header {
          background: var(--card);
          border-bottom-color: var(--border-strong, #31415c);
        }
        :root[data-theme="dark"] .requirements-draft-preview__header h4 {
          color: var(--text);
        }
        :root[data-theme="dark"] .requirements-draft-preview__header p {
          color: var(--muted);
        }
        :root[data-theme="dark"] .page-header p {
          color: var(--muted);
        }
      `}</style>

      <div className="requirements-layout">
        <div className="requirements-left">
          <Card
            className="requirements-input-card"
            title="需求文档输入"
            subtitle="粘贴需求或上传 TXT、MD、DOCX、文本型 PDF，确认正文后生成草稿。"
          >
            <div className="settings-note">当前模型：{modelLabel}</div>

            <label className="field-label" htmlFor="requirement-title">
              需求标题
            </label>
            <input
              className="text-input"
              id="requirement-title"
              placeholder="请输入需求标题"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />

            <label className="field-label" htmlFor="project-name">
              所属项目（必选）
            </label>
            <ProjectAutocomplete
              projects={projects}
              value={projectId}
              onChange={(next) => {
                setProjectId(next?.id ?? null);
              }}
              onCreateNew={() => {
                setNewProjectName("");
                setNewProjectBaseUrl("");
                setNewProjectError(null);
                setShowNewProjectDialog(true);
              }}
            />

            <label className="field-label" htmlFor="linked-requirement">打开已有需求</label>
            <select
              className="text-input"
              id="linked-requirement"
              value={linkedRequirementId ?? ""}
              onChange={(event) => handleLinkedRequirementChange(event.target.value)}
            >
              <option value="">新建需求</option>
              {requirements.map((item) => (
                <option key={item.id} value={item.id}>{item.title}</option>
              ))}
            </select>

            <div className="generation-options">
              <div>
                <label className="field-label" htmlFor="case-count">目标用例数</label>
                <input
                  className="text-input"
                  id="case-count"
                  min={1}
                  max={20}
                  type="number"
                  value={caseCount}
                  onChange={(event) => setCaseCount(Math.min(20, Math.max(1, Number(event.target.value) || 1)))}
                />
              </div>
              <div>
                <label className="field-label" htmlFor="coverage-focus">覆盖重点</label>
                <select
                  className="text-input"
                  id="coverage-focus"
                  value={coverageFocus}
                  onChange={(event) => setCoverageFocus(event.target.value as CoverageFocus)}
                >
                  <option value="balanced">综合覆盖（默认）</option>
                  <option value="normal">正常流程</option>
                  <option value="abnormal_boundary">异常与边界</option>
                  <option value="permission_security">权限与安全</option>
                </select>
              </div>
            </div>

            <div className="context-header">
              <label className="field-label" htmlFor="context-business-preconditions" style={{ marginBottom: 0 }}>
                补充约束（可选）
              </label>
              <button
                className="link-button"
                type="button"
                onClick={() => setShowContextFields((value) => !value)}
                title={showContextFields ? "收起补充约束" : "展开补充约束"}
              >
                {showContextFields ? "收起 ▴" : "展开 ▾"}
              </button>
            </div>
            {showContextFields ? (
              <div className="context-stack" data-testid="context-stack">
                <label className="field-label" htmlFor="context-business-preconditions">
                  业务前置条件
                </label>
                <textarea
                  className="textarea-mock textarea-real"
                  id="context-business-preconditions"
                  rows={3}
                  value={contextFields.business_preconditions ?? ""}
                  onChange={(event) =>
                    setContextFields((prev) => ({ ...prev, business_preconditions: event.target.value }))
                  }
                  placeholder="例如：使用管理员角色；已准备一条待审核数据；功能开关已开启（不要填写密码）"
                />
                <label className="field-label" htmlFor="context-excluded">
                  排除范围
                </label>
                <textarea
                  className="textarea-mock textarea-real"
                  id="context-excluded"
                  rows={2}
                  value={contextFields.excluded ?? ""}
                  onChange={(event) =>
                    setContextFields((prev) => ({ ...prev, excluded: event.target.value }))
                  }
                  placeholder="本次不覆盖的范围（多行）"
                />
              </div>
            ) : (
              <p className="empty-state" style={{ margin: "8px 0 18px 0" }}>
                已折叠。需要补充业务前置条件或排除范围时再展开。
              </p>
            )}

            <RequirementDocumentInput
              id="requirement-document"
              value={document}
              onChange={setDocument}
              onFile={(file) => void handleUpload(file)}
              parsing={parsingDocument}
            >
              <button
                className="btn btn--green"
                disabled={busy || parsingDocument || !canAnalyze}
                onClick={analyze}
                type="button"
              >
                开始生成
              </button>
              <button
                className="btn btn--outline"
                disabled={!busy || !generationControllerRef.current}
                onClick={() => void stopGeneration()}
                type="button"
              >
                停止
              </button>
            </RequirementDocumentInput>
          </Card>
        </div>

        <div className="requirements-right">
          <Card className="requirements-result-card" title="生成结果" subtitle="生成后的用例草稿集中在左侧，右侧即时预览 YAML 详情。">
            <div className="requirements-result-toolbar">
              <div className="requirements-result-toolbar__main">
                <button
                  className="btn btn--primary requirements-import-placeholder"
                  disabled={busy || !requirement || !drafts.length}
                  onClick={handleImportToCaseLibrary}
                  type="button"
                >
                  一键导入用例库
                </button>
                <button
                  className="btn btn--outline"
                  disabled={busy || !requirement || !drafts.length}
                  onClick={() => void exportCases("xlsx")}
                  type="button"
                >
                  导出 Excel
                </button>
                <div className="dropdown">
                  <button
                    className="btn btn--outline"
                    disabled={busy || !requirement || !drafts.length}
                    onClick={() => setXmindMenuOpen((value) => !value)}
                    type="button"
                    aria-haspopup="menu"
                    aria-expanded={xmindMenuOpen}
                  >
                    导出 XMind
                  </button>
                  {xmindMenuOpen && (
                    <ul className="dropdown__menu" role="menu">
                      <li>
                        <button
                          className="dropdown__item"
                          onClick={() => void handleXmindPngExport("type")}
                          type="button"
                          role="menuitem"
                        >
                          按功能类型导出
                        </button>
                      </li>
                      <li>
                        <button
                          className="dropdown__item"
                          onClick={() => void handleXmindPngExport("priority")}
                          type="button"
                          role="menuitem"
                        >
                          按优先级导出
                        </button>
                      </li>
                    </ul>
                  )}
                </div>
              </div>
              <div className="requirements-result-toolbar__side">
                <button
                  className="btn btn--outline"
                  disabled={busy || !selectedDraft}
                  onClick={handleCopy}
                  type="button"
                >
                  复制
                </button>
                <button
                  className="btn btn--outline"
                  disabled={busy || !drafts.length}
                  onClick={handleClear}
                  type="button"
                >
                  清空
                </button>
              </div>
            </div>

            <div className="requirements-result-meta">
              <span>共 {drafts.length} 条用例 · 正式 {promotedCount} · 草稿 {draftCount}</span>
              <span>{selectedDraft ? `当前：${selectedDraft.title || `draft #${selectedDraft.id}`}` : "暂无选中草稿"}</span>
            </div>

            <div className="requirements-result-grid">
              <section className="requirements-draft-list" aria-label="生成用例列表">
                <div className="requirements-draft-list__head">
                  <span>用例标题</span>
                  <span>状态</span>
                </div>
                <div className="requirements-draft-list__body">
                  {drafts.length ? (
                    drafts.map((draft) => (
                      <button
                        key={draft.id}
                        className={`requirements-draft-row${selectedDraft?.id === draft.id ? " is-active" : ""}`}
                        onClick={() => setSelectedDraftId(draft.id)}
                        type="button"
                      >
                        <span className="requirements-draft-row__title">
                          {draft.title || `draft #${draft.id}`}
                        </span>
                        <StatusPill
                          tone={
                            String(draft.status || "").toLowerCase() === "draft"
                              ? "amber"
                              : "green"
                          }
                        >
                          {draft.status || "draft"}
                        </StatusPill>
                      </button>
                    ))
                  ) : (
                    <div className="requirements-empty-result">
                      暂无测试用例草稿，点击“开始生成”后会自动生成。
                    </div>
                  )}
                </div>
              </section>

              <section className="requirements-draft-preview" aria-label="YAML 详情预览">
                {selectedDraft ? (
                  <>
                    <div className="requirements-draft-preview__header">
                      <div>
                        <h4>{selectedDraft.title || `draft #${selectedDraft.id}`}</h4>
                        <p>
                          状态 {selectedDraft.status || "draft"} · 模板{" "}
                          {selectedDraft.template || "spec"} · 更新 {formatSecondTime(selectedDraft.updated_at)}
                        </p>
                      </div>
                      <StatusPill
                        tone={
                          String(selectedDraft.status || "").toLowerCase() === "draft"
                            ? "amber"
                            : "green"
                        }
                      >
                        YAML
                      </StatusPill>
                    </div>
                    <pre>{selectedDraft.yaml || "（空）"}</pre>
                  </>
                ) : (
                  <div className="requirements-empty-result">请选择一条用例查看详情。</div>
                )}
              </section>
            </div>

            <div className="requirements-status-line">{status}</div>
          </Card>
        </div>
      </div>

      {/* P0 · "+ 新建项目" Dialog（架构 §0 决策 2：Dialog P0 不暴露 description，只录 name + base_url） */}
      {showNewProjectDialog ? (
        <NewProjectDialog
          name={newProjectName}
          baseUrl={newProjectBaseUrl}
          error={newProjectError}
          busy={newProjectBusy}
          existingNames={projects.map((p) => p.name)}
          onNameChange={(value) => {
            setNewProjectName(value);
            if (newProjectError) setNewProjectError(null);
          }}
          onBaseUrlChange={setNewProjectBaseUrl}
          onClose={() => {
            if (newProjectBusy) return;
            setShowNewProjectDialog(false);
            setNewProjectError(null);
          }}
          onSubmit={() => void submitNewProject()}
        />
      ) : null}
    </div>
  );
}

// -----------------------------------------------------------------------------
// P0 · 所属项目 Autocomplete（自研；不引入新依赖）
// 架构 §2 决策 1：MUI <Autocomplete freeSolo={false}>，但 MUI 不在 package.json
// 改用普通 React + 现有 CSS 自行实现同样的"受控下拉 + typing 模糊匹配 + 选中高亮"行为
// -----------------------------------------------------------------------------

function ProjectAutocomplete({
  projects,
  value,
  onChange,
  onCreateNew,
}: {
  projects: Project[];
  value: string | null;
  onChange: (next: Project | null) => void;
  onCreateNew: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const containerRef = useRef<HTMLDivElement | null>(null);

  const selected = useMemo(
    () => projects.find((p) => p.id === value) || null,
    [projects, value],
  );

  // 输入框显示值：focus 内显示 draft，blur 回填 selected.name
  const displayValue = open ? draft : selected?.name ?? "";

  const filtered = useMemo(() => {
    const q = draft.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter((p) => p.name.toLowerCase().includes(q));
  }, [draft, projects]);

  // 点外部关闭
  useEffect(() => {
    if (!open) return;
    function handleClick(event: MouseEvent) {
      const target = event.target as Node | null;
      if (containerRef.current && target && !containerRef.current.contains(target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div className="project-autocomplete" ref={containerRef}>
      <div className="project-autocomplete__row">
        <input
          className="text-input project-autocomplete__input"
          id="project-name"
          autoComplete="off"
          value={displayValue}
          placeholder="请选择或搜索项目"
          onFocus={() => {
            setDraft(selected?.name ?? "");
            setOpen(true);
          }}
          onChange={(event) => {
            setDraft(event.target.value);
            setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setOpen(false);
            } else if (event.key === "Enter" && filtered.length > 0) {
              onChange(filtered[0]);
              setDraft("");
              setOpen(false);
            }
          }}
        />
        <button
          className="btn btn--outline project-autocomplete__add"
          type="button"
          onClick={onCreateNew}
          title="新建项目（name + base_url）"
        >
          + 新建项目
        </button>
      </div>
      {open ? (
        <ul className="project-autocomplete__menu" role="listbox">
          {filtered.length === 0 ? (
            <li className="project-autocomplete__empty">无匹配项目</li>
          ) : (
            filtered.map((p) => {
              const isSelected = p.id === value;
              return (
                <li
                  key={p.id}
                  role="option"
                  aria-selected={isSelected}
                  className={`project-autocomplete__item${isSelected ? " is-selected" : ""}`}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    onChange(p);
                    setDraft("");
                    setOpen(false);
                  }}
                >
                  <span className="project-autocomplete__name">{p.name}</span>
                  {p.base_url ? (
                    <span className="project-autocomplete__hint">{p.base_url}</span>
                  ) : null}
                </li>
              );
            })
          )}
        </ul>
      ) : null}
    </div>
  );
}

// -----------------------------------------------------------------------------
// P0 · "+ 新建项目" Dialog（自研；不引入新依赖）
// P0 Dialog 只录 name + base_url；description 通过 PATCH 后续补（架构 §0 决策 2）
// -----------------------------------------------------------------------------

function NewProjectDialog({
  name,
  baseUrl,
  error,
  busy,
  existingNames,
  onNameChange,
  onBaseUrlChange,
  onClose,
  onSubmit,
}: {
  name: string;
  baseUrl: string;
  error: string | null;
  busy: boolean;
  existingNames: string[];
  onNameChange: (value: string) => void;
  onBaseUrlChange: (value: string) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  // inline name 重复校验（基线 §5 风险 3：name 重复要 inline 校验，不能等后端 400）
  const trimmedName = name.trim();
  const inlineDupError =
    trimmedName && existingNames.includes(trimmedName)
      ? `项目名"${trimmedName}"已存在，请换一个名字`
      : null;
  const displayError = error || inlineDupError;
  const canSubmit = trimmedName.length > 0 && !inlineDupError && !busy;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="新建项目"
      className="project-dialog-backdrop"
      onClick={onClose}
    >
      <div
        className="project-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="project-dialog__header">
          <strong>新建项目</strong>
          <button
            className="btn btn--outline"
            type="button"
            onClick={onClose}
            disabled={busy}
          >
            关闭
          </button>
        </div>
        <p className="muted" style={{ margin: "0 0 12px 0", fontSize: 12 }}>
          P0 只录 name + base_url；description 创建后可在项目档案中 PATCH 补。
        </p>
        <label className="field-label" htmlFor="new-project-name">
          项目名（必填，全局唯一）
        </label>
        <input
          id="new-project-name"
          className="text-input"
          value={name}
          onChange={(event) => onNameChange(event.target.value)}
          placeholder="例如：MyProject"
          autoFocus
          autoComplete="off"
        />
        <label className="field-label" htmlFor="new-project-base-url">
          Base URL（可空）
        </label>
        <input
          id="new-project-base-url"
          className="text-input"
          value={baseUrl}
          onChange={(event) => onBaseUrlChange(event.target.value)}
          placeholder="例如：https://staging.example.com"
          autoComplete="off"
        />
        {displayError ? (
          <p className="project-dialog__error" role="alert">
            {displayError}
          </p>
        ) : null}
        <div className="button-row" style={{ marginTop: 12 }}>
          <button
            className="btn btn--primary"
            type="button"
            disabled={!canSubmit}
            onClick={onSubmit}
          >
            {busy ? "提交中…" : "创建"}
          </button>
          <button
            className="btn btn--outline"
            type="button"
            onClick={onClose}
            disabled={busy}
          >
            取消
          </button>
        </div>
      </div>
    </div>
  );
}
