import { useEffect, useMemo, useRef, useState } from "react";
import MindElixir from "mind-elixir";
import "mind-elixir/style.css";
import { api, type TestPoint } from "../data/api";
import { Card } from "../components/Card";
import { StatusPill } from "../components/StatusPill";

type ViewMode = "category" | "module";
type CaseTemplate = "functional" | "negative" | "regression" | "e2e";
type CaseGenerator = "rule" | "ai";

type Group = {
  key: string;
  label: string;
  points: TestPoint[];
};

type PointDraft = {
  name: string;
  category: string;
  priority: string;
  status: string;
  description: string;
  module: string;
  source: string;
};

type MindNode = {
  id: string;
  topic: string;
  expanded?: boolean;
  tags?: string[];
  children?: MindNode[];
  style?: Record<string, string>;
};

type MindData = {
  nodeData: MindNode;
};

type MindTopicElement = HTMLElement & {
  nodeObj?: { id?: string };
};

type ReorderUpdate = {
  id: number;
  parent_id: number | null;
  sort_order: number;
  module?: string | null;
  category?: string | null;
};

const EMPTY_DRAFT: PointDraft = {
  name: "",
  category: "功能",
  priority: "P1",
  status: "已确认",
  description: "",
  module: "",
  source: "manual",
};

const PRIORITY_STYLE: Record<string, Record<string, string>> = {
  P0: { color: "var(--green)", background: "var(--green-soft)", border: "1px solid var(--green)" },
  P1: { color: "var(--amber)", background: "var(--amber-soft)", border: "1px solid var(--amber)" },
  P2: { color: "var(--blue)", background: "var(--blue-soft)", border: "1px solid var(--blue)" },
};

function groupPoints(points: TestPoint[], mode: ViewMode): Group[] {
  const map = new Map<string, TestPoint[]>();
  for (const point of points) {
    const key = mode === "category" ? point.category || "未分类" : point.module || point.requirement_title || "未归属模块";
    map.set(key, [...(map.get(key) || []), point]);
  }
  return Array.from(map.entries())
    .map(([label, items]) => ({ key: label, label, points: items }))
    .sort((a, b) => a.label.localeCompare(b.label, "zh-Hans-CN"));
}

function sortPoints(points: TestPoint[]) {
  return [...points].sort((a, b) => (a.sort_order ?? a.id) - (b.sort_order ?? b.id) || a.id - b.id);
}

function buildPointTree(points: TestPoint[], parentId: number | null): MindNode[] {
  const ids = new Set(points.map((point) => point.id));
  const children = sortPoints(
    points.filter((point) => {
      const pointParent = point.parent_id ?? null;
      if (parentId === null) return pointParent === null || !ids.has(pointParent);
      return pointParent === parentId;
    }),
  );
  return children.map((point) => ({
    id: `tp-${point.id}`,
    topic: `${point.priority}｜${point.name}`,
    tags: [point.category, point.module || "未归属模块", point.source || "unknown"],
    style: PRIORITY_STYLE[point.priority] || PRIORITY_STYLE.P2,
    children: buildPointTree(points, point.id),
  }));
}

function toMindData(points: TestPoint[], mode: ViewMode): MindData {
  const groups = groupPoints(points, mode);
  return {
    nodeData: {
      id: "root",
      topic: `已确认测试点 (${points.length})`,
      expanded: true,
      children: groups.map((group) => ({
        id: `group-${encodeURIComponent(group.key)}`,
        topic: `${group.label} (${group.points.length})`,
        expanded: true,
        children: buildPointTree(group.points, null),
      })),
    },
  };
}

function pointTone(priority: string): "green" | "amber" | "blue" {
  if (priority === "P0") return "green";
  if (priority === "P1") return "amber";
  return "blue";
}

function pointIdFromMindId(rawId: unknown): number | null {
  const id = String(rawId || "").replace(/^me/, "");
  if (!id.startsWith("tp-")) return null;
  const value = Number(id.slice(3));
  return Number.isFinite(value) ? value : null;
}

function groupLabelFromMindNode(node: MindNode): string {
  return node.topic.replace(/\s+\(\d+\)$/, "");
}

function pointIdsFromMindNodes(nodes: Array<{ id?: unknown }> | undefined): number[] {
  return Array.from(new Set((nodes || []).map((node) => pointIdFromMindId(node.id)).filter((id): id is number => Boolean(id))));
}

function pointIdsFromDom(host: HTMLElement | null): number[] {
  if (!host) return [];
  return Array.from(host.querySelectorAll(".selected"))
    .map((node) => pointIdFromMindId((node as HTMLElement).dataset.nodeid))
    .filter((id): id is number => Boolean(id));
}

function collectReorderUpdates(data: MindData, mode: ViewMode): ReorderUpdate[] {
  const updates: ReorderUpdate[] = [];

  function visit(nodes: MindNode[] = [], parentId: number | null, groupLabel: string) {
    nodes.forEach((node, index) => {
      const id = pointIdFromMindId(node.id);
      if (!id) return;
      updates.push({
        id,
        parent_id: parentId,
        sort_order: index + 1,
        module: mode === "module" ? groupLabel : undefined,
        category: mode === "category" ? groupLabel : undefined,
      });
      visit(node.children || [], id, groupLabel);
    });
  }

  for (const group of data.nodeData.children || []) {
    visit(group.children || [], null, groupLabelFromMindNode(group));
  }
  return updates;
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function downloadText(filename: string, content: string, type: string) {
  downloadBlob(filename, new Blob([content], { type }));
}

export function TestPointsMap() {
  const mapHostRef = useRef<HTMLDivElement | null>(null);
  const mindRef = useRef<any>(null);
  const [points, setPoints] = useState<TestPoint[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>("category");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [draft, setDraft] = useState<PointDraft>(EMPTY_DRAFT);
  const [yamlPreview, setYamlPreview] = useState("");
  const [caseTitle, setCaseTitle] = useState("ICM 测试点生成用例草稿");
  const [caseTemplate, setCaseTemplate] = useState<CaseTemplate>("functional");
  const [caseGenerator, setCaseGenerator] = useState<CaseGenerator>("rule");
  const [status, setStatus] = useState("正在读取已确认测试点...");
  const [busy, setBusy] = useState(false);

  const mindData = useMemo(() => toMindData(points, viewMode), [points, viewMode]);
  const selectedPoints = points.filter((point) => selectedIds.includes(point.id));
  const selectedOne = selectedPoints.length === 1 ? selectedPoints[0] : null;

  async function refreshPoints() {
    setBusy(true);
    try {
      const result = await api.testPoints("confirmed");
      setPoints(result);
      setStatus(`已读取 ${result.length} 个已确认测试点`);
    } catch (error) {
      setStatus(`读取测试点失败：${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refreshPoints();
  }, []);

  useEffect(() => {
    if (selectedOne) {
      setDraft({
        name: selectedOne.name,
        category: selectedOne.category,
        priority: selectedOne.priority,
        status: selectedOne.status,
        description: selectedOne.description || "",
        module: selectedOne.module || selectedOne.requirement_title || "",
        source: selectedOne.source || "manual",
      });
    }
  }, [selectedOne?.id]);

  function syncSelectionFromMind(mind = mindRef.current) {
    const ids = pointIdsFromMindNodes(mind?.currentNodes?.map((node: MindTopicElement) => node.nodeObj || {}));
    setSelectedIds(ids.length ? ids : pointIdsFromDom(mapHostRef.current));
  }

  function focusPoint(id: number) {
    const mind = mindRef.current;
    if (!mind) return;
    try {
      const el = mind.findEle(`tp-${id}`);
      mind.clearSelection?.();
      mind.selectNode?.(el);
      mind.focusNode?.(el);
      setSelectedIds([id]);
    } catch {
      setStatus("该节点可能处于折叠状态，请先展开分组后再定位。");
    }
  }

  async function createPoint() {
    if (!draft.name.trim()) {
      setStatus("请先填写测试点名称");
      return;
    }
    setBusy(true);
    try {
      await api.createTestPoint(draft);
      setDraft(EMPTY_DRAFT);
      await refreshPoints();
      setStatus("测试点已新增并进入 Mind Elixir 思维导图");
    } catch (error) {
      setStatus(`新增失败：${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveSelectedPoint() {
    if (!selectedOne) {
      setStatus("请选择一个测试点再编辑");
      return;
    }
    setBusy(true);
    try {
      await api.updateTestPoint(selectedOne.id, draft);
      await refreshPoints();
      setStatus(`测试点已保存：${draft.name}`);
    } catch (error) {
      setStatus(`保存失败：${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveMapStructure() {
    const mind = mindRef.current;
    if (!mind) return;
    setBusy(true);
    try {
      const data = mind.getData?.() as MindData;
      const updates = collectReorderUpdates(data, viewMode);
      const result = await api.reorderTestPoints(updates);
      await refreshPoints();
      setStatus(`导图结构已保存：${result.updated} 个测试点`);
    } catch (error) {
      setStatus(`保存导图结构失败：${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteByIds(ids: number[]) {
    if (!ids.length) {
      setStatus("请选择要删除的测试点");
      return;
    }
    setBusy(true);
    try {
      for (const id of ids) {
        await api.deleteTestPoint(id);
      }
      setSelectedIds([]);
      await refreshPoints();
      setStatus("已删除选中的测试点");
    } catch (error) {
      setStatus(`删除失败：${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setBusy(false);
    }
  }

  async function generateYamlByIds(ids: number[]) {
    if (!ids.length) {
      setStatus("请选择一个或多个测试点生成 YAML");
      return;
    }
    setBusy(true);
    try {
      const result = await api.generateCasesFromTestPoints(ids, {
        title: caseTitle,
        template: caseTemplate,
        generator: caseGenerator,
      });
      setYamlPreview(result.yaml);
      setStatus(`YAML 草稿已生成：draft #${result.draft_id}，可到用例工具箱继续编辑或转正式 case`);
    } catch (error) {
      setStatus(`生成 YAML 失败：${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setBusy(false);
    }
  }

  async function exportImage() {
    const mind = mindRef.current;
    if (!mind) return;
    try {
      const png = await mind.exportPng?.();
      if (png) {
        downloadBlob(`icm-test-points-${viewMode}.png`, png);
        setStatus("Mind Elixir 思维导图已导出为 PNG");
        return;
      }
      const svg = mind.exportSvg?.();
      if (svg instanceof Blob) {
        downloadBlob(`icm-test-points-${viewMode}.svg`, svg);
        setStatus("Mind Elixir 思维导图已导出为 SVG");
        return;
      }
    } catch (error) {
      setStatus(`导出图片失败：${error instanceof Error ? error.message : "unknown error"}`);
      return;
    }
    downloadText(`icm-test-points-${viewMode}.json`, JSON.stringify(mind.getData?.() || mindData, null, 2), "application/json;charset=utf-8");
    setStatus("当前环境无法导出图片，已导出导图 JSON 数据");
  }

  function fitMap() {
    mindRef.current?.scaleFit?.();
    setStatus("导图已适配当前画布");
  }

  function centerMap() {
    mindRef.current?.toCenter?.();
    setStatus("导图已回到中心");
  }

  useEffect(() => {
    if (!mapHostRef.current) return;
    mapHostRef.current.innerHTML = "";
    const mind = new (MindElixir as any)({
      el: mapHostRef.current,
      direction: (MindElixir as any).SIDE || 2,
      editable: true,
      contextMenu: {
        focus: true,
        link: false,
        extend: [
          {
            name: "选中生成 YAML",
            onclick: () => {
              const ids = pointIdsFromMindNodes(mind.currentNodes?.map((node: MindTopicElement) => node.nodeObj || {}));
              void generateYamlByIds(ids);
            },
          },
          {
            name: "删除选中测试点",
            onclick: () => {
              const ids = pointIdsFromMindNodes(mind.currentNodes?.map((node: MindTopicElement) => node.nodeObj || {}));
              void deleteByIds(ids);
            },
          },
        ],
      },
      toolBar: true,
      nodeMenu: true,
      keypress: true,
      mobileMultiSelect: true,
      mouseSelectionButton: 0,
    });
    mind.init(mindData);
    mindRef.current = mind;
    setTimeout(() => mind.scaleFit?.(), 0);

    const handleSelection = () => syncSelectionFromMind(mind);
    mind.bus?.addListener?.("selectNodes", handleSelection);
    mind.bus?.addListener?.("unselectNodes", handleSelection);
    mind.bus?.addListener?.("operation", handleSelection);

    const handleClick = () => setTimeout(() => syncSelectionFromMind(mind), 0);
    mapHostRef.current.addEventListener("click", handleClick);
    mapHostRef.current.addEventListener("contextmenu", handleClick);

    return () => {
      mapHostRef.current?.removeEventListener("click", handleClick);
      mapHostRef.current?.removeEventListener("contextmenu", handleClick);
      mind.bus?.removeListener?.("selectNodes", handleSelection);
      mind.bus?.removeListener?.("unselectNodes", handleSelection);
      mind.bus?.removeListener?.("operation", handleSelection);
      mind.destroy?.();
      mindRef.current = null;
    };
  }, [mindData]);

  return (
    <div className="page points-page">
      <div className="points-toolbar">
        <div className="button-row">
          <button className={`btn ${viewMode === "category" ? "btn--primary" : "btn--soft"}`} onClick={() => setViewMode("category")} type="button">
            按测试类型
          </button>
          <button className={`btn ${viewMode === "module" ? "btn--primary" : "btn--soft"}`} onClick={() => setViewMode("module")} type="button">
            按功能模块
          </button>
          <button className="btn btn--outline" disabled={busy} onClick={refreshPoints} type="button">刷新</button>
          <button className="btn btn--outline" disabled={busy} onClick={saveMapStructure} type="button">保存导图结构</button>
          <button className="btn btn--outline" onClick={fitMap} type="button">适配画布</button>
          <button className="btn btn--outline" onClick={centerMap} type="button">回到中心</button>
          <button className="btn btn--outline" onClick={exportImage} type="button">导出图片</button>
          <button className="btn btn--green" disabled={busy || !selectedIds.length} onClick={() => generateYamlByIds(selectedIds)} type="button">选中生成 YAML</button>
        </div>
        <span className="muted">{status}</span>
      </div>

      <div className="points-layout">
        <Card className="points-map-card" title="Mind Elixir 测试点思维导图" subtitle="拖拽调整层级或顺序后，点击“保存导图结构”写回 SQLite。">
          <div className="mind-elixir-host" ref={mapHostRef} />
        </Card>

        <div className="points-side">
          <Card title={selectedOne ? "编辑测试点" : "新增测试点"} subtitle={selectedOne ? "当前只在选中单个测试点时编辑。" : "新增后默认进入已确认测试点地图。"}>
            <label className="field-label">测试点名称</label>
            <input className="text-input" value={draft.name} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} />
            <label className="field-label">测试类型</label>
            <input className="text-input" value={draft.category} onChange={(event) => setDraft((current) => ({ ...current, category: event.target.value }))} />
            <label className="field-label">功能模块</label>
            <input className="text-input" value={draft.module} onChange={(event) => setDraft((current) => ({ ...current, module: event.target.value }))} />
            <label className="field-label">来源</label>
            <select className="text-input" value={draft.source} onChange={(event) => setDraft((current) => ({ ...current, source: event.target.value }))}>
              <option value="manual">manual</option>
              <option value="ai_generated">ai_generated</option>
              <option value="case_asset">case_asset</option>
              <option value="mindmap_edit">mindmap_edit</option>
            </select>
            <label className="field-label">优先级</label>
            <select className="text-input" value={draft.priority} onChange={(event) => setDraft((current) => ({ ...current, priority: event.target.value }))}>
              <option>P0</option>
              <option>P1</option>
              <option>P2</option>
            </select>
            <label className="field-label">状态</label>
            <select className="text-input" value={draft.status} onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value }))}>
              <option>已确认</option>
              <option>待确认</option>
              <option>待复核</option>
              <option>已覆盖</option>
            </select>
            <label className="field-label">说明</label>
            <textarea className="textarea-mock textarea-real point-description" value={draft.description} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} />
            <div className="button-row">
              <button className="btn btn--primary" disabled={busy || !selectedOne} onClick={saveSelectedPoint} type="button">保存编辑</button>
              <button className="btn btn--green" disabled={busy} onClick={createPoint} type="button">新增节点</button>
              <button className="btn btn--outline" onClick={() => setDraft(EMPTY_DRAFT)} type="button">清空</button>
            </div>
          </Card>

          <Card title="用例生成配置" subtitle="先确认选中的测试点，再生成可编辑 YAML 草稿。">
            <label className="field-label">草稿标题</label>
            <input className="text-input" value={caseTitle} onChange={(event) => setCaseTitle(event.target.value)} />
            <label className="field-label">用例模板</label>
            <select className="text-input" value={caseTemplate} onChange={(event) => setCaseTemplate(event.target.value as CaseTemplate)}>
              <option value="functional">功能用例</option>
              <option value="negative">异常用例</option>
              <option value="regression">回归用例</option>
              <option value="e2e">端到端链路</option>
            </select>
            <label className="field-label">生成方式</label>
            <select className="text-input" value={caseGenerator} onChange={(event) => setCaseGenerator(event.target.value as CaseGenerator)}>
              <option value="rule">规则生成（本地稳定）</option>
              <option value="ai">AI 生成（使用当前模型设置）</option>
            </select>
            <div className="selected-summary">
              <strong>已选 {selectedIds.length} 个测试点</strong>
              <span>{selectedPoints.map((point) => point.name).join("、") || "请在导图中选择一个或多个测试点"}</span>
            </div>
            <button className="btn btn--green btn--wide" disabled={busy || !selectedIds.length} onClick={() => generateYamlByIds(selectedIds)} type="button">
              按当前配置生成 YAML 草稿
            </button>
          </Card>

          <Card title="选中测试点" subtitle="点击下方标签可定位到导图节点。">
            <div className="button-row">
              <StatusPill tone="green">已选 {selectedIds.length}</StatusPill>
              {selectedPoints.slice(0, 8).map((point) => (
                <button className="point-chip-button" key={point.id} onClick={() => focusPoint(point.id)} type="button">
                  <StatusPill tone={pointTone(point.priority)}>{point.name}</StatusPill>
                </button>
              ))}
            </div>
            <div className="button-row points-actions">
              <button className="btn btn--dark" disabled={busy || !selectedIds.length} onClick={() => generateYamlByIds(selectedIds)} type="button">生成 YAML 草稿</button>
              <button className="btn btn--outline" disabled={busy || !selectedIds.length} onClick={() => setSelectedIds([])} type="button">取消选择</button>
              <button className="btn btn--outline" disabled={busy || !selectedIds.length} onClick={() => deleteByIds(selectedIds)} type="button">删除选中</button>
            </div>
          </Card>

          <Card className="markdown-card" title="YAML 草稿预览" subtitle="由当前选中的测试点生成，并保存到 SQLite 草稿库。">
            <pre className="markdown-preview">{yamlPreview || "选中一个或多个测试点后，点击“选中生成 YAML”。"}</pre>
          </Card>
        </div>
      </div>
    </div>
  );
}
