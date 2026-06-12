import { useEffect, useMemo, useState } from "react";

import { Card } from "../components/Card";
import { StatusPill } from "../components/StatusPill";
import { api, type Requirement, type RequirementDetail } from "../data/api";
import type { PageId, PlatformNavKey } from "../types";

const STATUS_OPTIONS = [
  { value: "draft", label: "草稿", tone: "amber" },
  { value: "analyzed", label: "已分析", tone: "blue" },
  { value: "cases_generated", label: "已生成用例", tone: "green" },
  { value: "archived", label: "已归档", tone: "dark" },
] as const;

type RequirementForm = {
  title: string;
  document: string;
  status: string;
};

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "unknown error";
}

function formatTime(value?: string | null) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function statusMeta(status?: string | null) {
  return STATUS_OPTIONS.find((item) => item.value === status) || STATUS_OPTIONS[0];
}

function toForm(requirement: Requirement): RequirementForm {
  return {
    title: requirement.title || "",
    document: requirement.document || "",
    status: requirement.status || "draft",
  };
}

export function RequirementManagement({
  onNavigate,
}: {
  onNavigate: (page: PageId, navKey?: PlatformNavKey) => void;
}) {
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [detail, setDetail] = useState<RequirementDetail | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [form, setForm] = useState<RequirementForm>({ title: "", document: "", status: "draft" });
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("正在读取需求列表...");

  const selectedRequirement = detail?.requirement ?? null;
  const dirty = Boolean(
    creating ||
    (selectedRequirement &&
      (form.title !== selectedRequirement.title ||
        form.document !== selectedRequirement.document ||
        form.status !== selectedRequirement.status)),
  );

  const filteredRequirements = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    return requirements.filter((item) => {
      if (statusFilter !== "all" && item.status !== statusFilter) return false;
      if (!q) return true;
      return `${item.title} ${item.document} ${item.status}`.toLowerCase().includes(q);
    });
  }, [keyword, requirements, statusFilter]);

  const metrics = useMemo(() => {
    const draftTotal = requirements.reduce((sum, item) => sum + (item.draft_count || item.case_count || 0), 0);
    const analyzed = requirements.filter((item) => item.status === "analyzed" || item.status === "cases_generated").length;
    const archived = requirements.filter((item) => item.status === "archived").length;
    return { total: requirements.length, analyzed, draftTotal, archived };
  }, [requirements]);

  async function refresh(nextId = selectedId) {
    setLoading(true);
    try {
      const items = await api.requirements();
      setRequirements(items);
      const target = items.find((item) => item.id === nextId) || items[0] || null;
      if (target) {
        await openRequirement(target.id);
      } else {
        setSelectedId(null);
        setDetail(null);
        setForm({ title: "", document: "", status: "draft" });
        setMessage("暂无需求，请先到 AI生成 页面创建。");
      }
    } catch (error) {
      setMessage(`需求列表读取失败：${errorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }

  async function openRequirement(id: number) {
    setBusy(true);
    try {
      const next = await api.requirementDetail(id);
      setSelectedId(id);
      setDetail(next);
      setCreating(false);
      setForm(toForm(next.requirement));
      setMessage(`已选择需求：${next.requirement.title}`);
    } catch (error) {
      setMessage(`需求详情读取失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveRequirement() {
    if (!form.title.trim() || !form.document.trim()) {
      setMessage("标题和正文不能为空。");
      return;
    }
    setBusy(true);
    try {
      if (creating || !selectedRequirement) {
        const created = await api.createRequirement({
          title: form.title.trim(),
          document: form.document.trim(),
        });
        setDetail(created);
        setSelectedId(created.requirement.id);
        setCreating(false);
        setForm(toForm(created.requirement));
        await refresh(created.requirement.id);
        setMessage("需求已新增。可以前往 AI生成 生成测试用例。");
        return;
      }
      const next = await api.updateRequirement(selectedRequirement.id, {
        title: form.title.trim(),
        document: form.document.trim(),
        status: form.status,
      });
      setDetail(next);
      setForm(toForm(next.requirement));
      setRequirements((items) =>
        items.map((item) => (item.id === next.requirement.id ? { ...item, ...next.requirement } : item)),
      );
      setMessage("需求已保存。需求内容如有变化，可前往 AI生成 重新生成用例。");
    } catch (error) {
      setMessage(`需求保存失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function startCreateRequirement() {
    setCreating(true);
    setSelectedId(null);
    setDetail(null);
    setForm({ title: "", document: "", status: "draft" });
    setMessage("正在新增需求，请填写标题和正文后保存。");
  }

  async function deleteRequirement() {
    if (!selectedRequirement) return;
    const ok = window.confirm(`确认删除"${selectedRequirement.title}"？关联测试点和草稿也会被清理。`);
    if (!ok) return;
    setBusy(true);
    try {
      const deleted = await api.deleteRequirement(selectedRequirement.id);
      const remaining = requirements.filter((item) => item.id !== selectedRequirement.id);
      setRequirements(remaining);
      const next = remaining[0] || null;
      if (next) {
        await openRequirement(next.id);
      } else {
        setSelectedId(null);
        setDetail(null);
        setForm({ title: "", document: "", status: "draft" });
      }
      setMessage(`已删除"${deleted.title}"：清理 ${deleted.deleted_test_points} 个测试点、${deleted.deleted_case_drafts} 个草稿。`);
    } catch (error) {
      setMessage(`需求删除失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refresh(null);
  }, []);

  return (
    <div className="page requirement-management-page">
      <section className="requirement-metrics">
        <Metric label="需求总数" value={metrics.total} tag="Total" />
        <Metric label="已分析需求" value={metrics.analyzed} tag="Analyzed" />
        <Metric label="关联草稿" value={metrics.draftTotal} tag="Drafts" />
        <Metric label="已归档" value={metrics.archived} tag="Archived" />
      </section>

      <div className="requirement-management-layout">
        <Card className="requirement-list-card" title="需求列表" subtitle="筛选、选择并追踪需求资产状态。">
          <div className="requirement-list-toolbar">
            <button className="btn btn--primary" type="button" onClick={startCreateRequirement} disabled={busy}>
              新增需求
            </button>
            <span className="muted">新增后先进入草稿状态，不会自动调用 AI。</span>
          </div>
          <div className="requirement-filter-grid">
            <label className="case-filter-field">
              <span>关键词</span>
              <input
                className="text-input"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索标题 / 正文 / 状态"
              />
            </label>
            <label className="case-filter-field">
              <span>状态</span>
              <select className="case-filter-select" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="all">全部状态</option>
                {STATUS_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <div className="case-filter-actions">
              <button className="btn btn--primary" type="button" onClick={() => void refresh()} disabled={loading || busy}>
                刷新
              </button>
              <button className="btn btn--outline" type="button" onClick={() => { setKeyword(""); setStatusFilter("all"); }}>
                重置
              </button>
            </div>
          </div>

          <div className="requirement-table-shell">
            <table className="table requirement-table">
              <thead>
                <tr>
                  <th>标题</th>
                  <th>状态</th>
                  <th>草稿</th>
                  <th>测试点</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                {filteredRequirements.map((item) => {
                  const meta = statusMeta(item.status);
                  return (
                    <tr
                      key={item.id}
                      className={item.id === selectedId ? "is-active" : ""}
                      onClick={() => void openRequirement(item.id)}
                    >
                      <td>
                        <strong>{item.title}</strong>
                        <span>#{item.id} · 创建 {formatTime(item.created_at)}</span>
                      </td>
                      <td><StatusPill tone={meta.tone}>{meta.label}</StatusPill></td>
                      <td>{item.draft_count ?? item.case_count ?? 0}</td>
                      <td>{item.test_point_count ?? 0}</td>
                      <td>{formatTime(item.updated_at)}</td>
                    </tr>
                  );
                })}
                {!filteredRequirements.length ? (
                  <tr>
                    <td colSpan={5}>{loading ? "正在加载需求..." : "当前筛选条件下没有需求。"}</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="requirement-detail-card" title={creating ? "新增需求" : "需求详情"} subtitle={creating ? "draft" : selectedRequirement ? `#${selectedRequirement.id}` : "请选择左侧需求"}>
          {selectedRequirement || creating ? (
            <>
              <div className="requirement-detail-actions">
                <button className="btn btn--primary" type="button" onClick={saveRequirement} disabled={busy || !dirty}>
                  {creating ? "创建需求" : "保存需求"}
                </button>
                <button className="btn btn--outline" type="button" onClick={() => onNavigate("ai-generate", "ai-generate")} disabled={creating}>
                  去 AI生成
                </button>
                <button className="btn btn--outline" type="button" onClick={() => onNavigate("cases", "cases")} disabled={creating}>
                  查看用例
                </button>
                <button className="btn btn--outline link-button--danger" type="button" onClick={deleteRequirement} disabled={busy || creating}>
                  删除
                </button>
              </div>

              <label className="field-label">需求标题</label>
              <input className="text-input" value={form.title} onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))} />

              <label className="field-label">需求状态</label>
              <select className="text-input" value={form.status} onChange={(event) => setForm((prev) => ({ ...prev, status: event.target.value }))}>
                {STATUS_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>

              <label className="field-label">需求正文</label>
              <textarea
                className="textarea-mock textarea-real requirement-management-document"
                value={form.document}
                onChange={(event) => setForm((prev) => ({ ...prev, document: event.target.value }))}
              />

              {!creating && selectedRequirement ? (
                <>
                  <div className="requirement-summary-grid">
                    <InfoPanel title="AI 分析摘要" value={selectedRequirement.analysis_summary || "暂无分析摘要。"} />
                    <InfoPanel title="风险提示" value={selectedRequirement.risk_summary || "暂无风险提示。"} />
                  </div>

                  <div className="requirement-case-summary">
                    <strong>关联用例</strong>
                    <span>{selectedRequirement.draft_count ?? selectedRequirement.case_count ?? 0} 条草稿，可点击“查看用例”进入用例管理查看明细。</span>
                  </div>
                </>
              ) : null}
            </>
          ) : (
            <p className="empty-state">请选择一条需求查看详情。</p>
          )}
          <div className="requirements-status-line">{message}</div>
        </Card>
      </div>
    </div>
  );
}

function Metric({ label, value, tag }: { label: string; value: number; tag: string }) {
  return (
    <div className="qa-metric-card requirement-metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{tag}</small>
    </div>
  );
}

function InfoPanel({ title, value }: { title: string; value: string }) {
  return (
    <section className="requirement-info-panel">
      <strong>{title}</strong>
      <p>{value}</p>
    </section>
  );
}
