import { useEffect, useMemo, useState } from "react";

import { Card } from "../components/Card";
import { FlowSteps } from "../components/FlowSteps";
import { StatusPill } from "../components/StatusPill";
import { api, type AISettings, type CaseDraft, type Requirement, type RequirementDetail } from "../data/api";

const DEFAULT_DOCUMENT = `示例：远程报修流程
1. 用户发起设备请求协助
2. 工单侧处理并打开远程界面
3. 点击解决完成闭环`;

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "unknown error";
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

function draftLabel(draft: CaseDraft) {
  return draft.title || `draft #${draft.id}`;
}

function safeCount(value: number | null | undefined) {
  return typeof value === "number" ? value : 0;
}

function initialWorkspaceState() {
  return {
    title: "远程报修流程需求",
    document: DEFAULT_DOCUMENT,
  };
}

export function RequirementsWorkspace() {
  const [title, setTitle] = useState(initialWorkspaceState().title);
  const [document, setDocument] = useState(initialWorkspaceState().document);
  const [settings, setSettings] = useState<AISettings | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [detail, setDetail] = useState<RequirementDetail | null>(null);
  const [selectedDraftId, setSelectedDraftId] = useState<number | null>(null);
  const [yamlPreview, setYamlPreview] = useState("");
  const [status, setStatus] = useState("正在连接需求工作台...");
  const [busy, setBusy] = useState(false);

  const requirement = detail?.requirement ?? null;
  const drafts = detail?.drafts ?? [];
  const selectedDraft = drafts.find((item) => item.id === selectedDraftId) ?? drafts[0] ?? null;
  const canAnalyze = useMemo(() => title.trim().length > 0 && document.trim().length > 0, [document, title]);

  function resetWorkspace(message?: string) {
    const initial = initialWorkspaceState();
    setDetail(null);
    setSelectedDraftId(null);
    setYamlPreview("");
    setTitle(initial.title);
    setDocument(initial.document);
    if (message) {
      setStatus(message);
    }
  }

  useEffect(() => {
    void loadInitialData();
  }, []);

  useEffect(() => {
    if (selectedDraft) {
      setYamlPreview(selectedDraft.yaml);
    }
  }, [selectedDraft]);

  async function loadInitialData() {
    try {
      const [aiSettings, items] = await Promise.all([api.aiSettings(), api.requirements()]);
      setSettings(aiSettings);
      setRequirements(items);
      if (items[0]) {
        await openRequirement(items[0].id);
      } else {
        resetWorkspace("还没有历史需求，先创建一条新的需求记录。");
      }
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
      setTitle(result.requirement.title);
      setDocument(result.requirement.document);
      setSelectedDraftId(result.drafts[0]?.id ?? null);
      setYamlPreview(result.drafts[0]?.yaml || "");
      setStatus(`已打开需求：${result.requirement.title}`);
    } catch (error) {
      setStatus(`读取需求失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function analyze() {
    if (!canAnalyze) {
      setStatus("请先填写需求标题和需求正文。");
      return;
    }
    setBusy(true);
    setStatus("正在按规范生成测试用例...");
    try {
      const result = await api.analyzeRequirementSpec(title.trim(), document);
      setDetail(result);
      setRequirements(await api.requirements());
      setSelectedDraftId(result.drafts[0]?.id ?? null);
      setYamlPreview(result.drafts[0]?.yaml || "");
      setStatus(`已生成 ${result.drafts.length} 条测试用例草稿。`);
    } catch (error) {
      setStatus(`分析失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleUpload(file: File | null) {
    if (!file) return;
    if (!file.name.endsWith(".txt") && !file.name.endsWith(".md")) {
      setStatus("首版仅支持 .txt / .md 文档。");
      return;
    }
    const text = await file.text();
    setDocument(text);
    setTitle(file.name.replace(/\.(txt|md)$/i, ""));
    setStatus(`已读取文档：${file.name}`);
  }

  async function handleDeleteRequirement(item: Requirement) {
    const ok = window.confirm(
      [`确认删除需求“${item.title}”吗？`, `将同时删除 ${safeCount(item.test_point_count)} 个测试点和 ${safeCount(item.draft_count)} 个草稿。`, "此操作不可恢复。"].join(
        "\n",
      ),
    );
    if (!ok) return;

    setBusy(true);
    try {
      const result = await api.deleteRequirement(item.id);
      setStatus(`已删除“${result.title}”：清理 ${result.deleted_test_points} 个测试点、${result.deleted_case_drafts} 个草稿。`);
      const keepId = requirement?.id === item.id ? undefined : requirement?.id;
      await refreshRequirements(keepId);
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

  const caseCount = drafts.length;
  const p0Count = drafts.filter((draft) => /P0/i.test(draft.yaml)).length;
  const latestDraft = drafts[0] ?? null;
  const modelLabel = settings ? `${settings.provider} / ${settings.model}` : "模型读取中...";
  const completionCount = drafts.filter((draft) => ["confirmed", "ready", "passed"].includes(draft.status.trim().toLowerCase())).length;
  const progressPercent = caseCount ? Math.min(100, Math.max(12, Math.round((completionCount / caseCount) * 100))) : 0;

  return (
    <div className="page requirements-page">
      <style>{`
        .requirements-page {
          max-width: 1480px;
        }

        .requirements-summary {
          display: grid;
          gap: 18px;
          padding: 22px 24px;
          margin-bottom: 22px;
        }

        .requirements-summary__head {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 18px;
        }

        .requirements-summary__title {
          display: grid;
          gap: 6px;
        }

        .requirements-summary__title h2 {
          margin: 0;
          font-size: 26px;
        }

        .requirements-summary__title p {
          margin: 0;
          color: var(--muted);
          line-height: 1.6;
        }

        .requirements-summary__meta {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-wrap: wrap;
          justify-content: flex-end;
        }

        .requirements-summary__progress {
          display: grid;
          gap: 10px;
        }

        .requirements-summary__progress-track {
          height: 10px;
          border-radius: 999px;
          background: rgba(43, 95, 239, 0.12);
          overflow: hidden;
        }

        .requirements-summary__progress-fill {
          height: 100%;
          border-radius: 999px;
          background: linear-gradient(90deg, #2b5fef 0%, #24c28a 100%);
        }

        .requirements-summary__progress-copy {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          color: var(--muted);
          font-size: 13px;
          flex-wrap: wrap;
        }

        .requirements-summary__metrics {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 14px;
        }

        .requirements-summary__metric {
          border: 1px solid var(--line);
          border-radius: 18px;
          background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(243, 247, 255, 0.92) 100%);
          padding: 16px 18px;
          display: grid;
          gap: 6px;
        }

        .requirements-summary__metric-label {
          color: var(--muted);
          font-size: 12px;
        }

        .requirements-summary__metric-value {
          font-size: 28px;
          line-height: 1;
          font-weight: 700;
          color: var(--text);
        }

        .requirements-summary__metric-note {
          color: var(--muted);
          font-size: 12px;
        }

        .requirements-layout {
          display: grid;
          grid-template-columns: minmax(300px, 0.95fr) minmax(420px, 1.2fr) minmax(320px, 0.95fr);
          gap: 20px;
          align-items: start;
        }

        .requirements-left,
        .requirements-center,
        .requirements-right {
          display: grid;
          gap: 20px;
          align-content: start;
          min-width: 0;
        }

        .requirements-table-card {
          min-height: 640px;
          display: grid;
          grid-template-rows: auto 1fr;
        }

        .requirements-table-wrap {
          overflow: auto;
        }

        .requirements-status-line {
          color: var(--muted);
          font-size: 13px;
          line-height: 1.6;
        }

        .requirements-right .markdown-card {
          min-height: 380px;
          display: grid;
          grid-template-rows: auto 1fr;
        }

        .requirements-right .markdown-preview {
          margin: 0;
          min-height: 290px;
          max-height: none;
        }

        @media (max-width: 1280px) {
          .requirements-layout {
            grid-template-columns: 1fr;
          }

          .requirements-summary__head,
          .requirements-summary__progress-copy {
            flex-direction: column;
            align-items: flex-start;
          }

          .requirements-summary__meta {
            justify-content: flex-start;
          }

          .requirements-summary__metrics {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }

        @media (max-width: 720px) {
          .requirements-summary__metrics {
            grid-template-columns: 1fr;
          }
        }
      `}</style>

      <FlowSteps activeIndex={0} />

      <Card className="requirements-summary">
        <div className="requirements-summary__head">
          <div className="requirements-summary__title">
            <h2>需求工作台</h2>
            <p>从需求文档直接生成规范化测试用例，并把摘要、风险、导出和 YAML 草稿放在同一屏内，减少来回滚动。</p>
          </div>
          <div className="requirements-summary__meta">
            <StatusPill tone="blue">{modelLabel}</StatusPill>
            <StatusPill tone="green">{requirement ? `当前需求 #${requirement.id}` : "等待创建需求"}</StatusPill>
          </div>
        </div>

        <div className="requirements-summary__progress">
          <div className="requirements-summary__progress-track">
            <div className="requirements-summary__progress-fill" style={{ width: `${progressPercent}%` }} />
          </div>
          <div className="requirements-summary__progress-copy">
            <span>业务目标 → 规范化测试用例 → YAML 草稿 → 真实跑通 → case 沉淀 → Python 脚本化</span>
            <span>{caseCount ? `当前草稿完成度 ${progressPercent}%` : "先创建并分析一条需求"}</span>
          </div>
        </div>

        <div className="requirements-summary__metrics">
          <div className="requirements-summary__metric">
            <span className="requirements-summary__metric-label">历史需求</span>
            <strong className="requirements-summary__metric-value">{requirements.length}</strong>
            <span className="requirements-summary__metric-note">本地库中已保存的需求记录</span>
          </div>
          <div className="requirements-summary__metric">
            <span className="requirements-summary__metric-label">测试用例草稿</span>
            <strong className="requirements-summary__metric-value">{caseCount}</strong>
            <span className="requirements-summary__metric-note">当前需求生成结果</span>
          </div>
          <div className="requirements-summary__metric">
            <span className="requirements-summary__metric-label">高优先级用例</span>
            <strong className="requirements-summary__metric-value">{p0Count}</strong>
            <span className="requirements-summary__metric-note">YAML 中命中的 P0 数量</span>
          </div>
          <div className="requirements-summary__metric">
            <span className="requirements-summary__metric-label">最新草稿</span>
            <strong className="requirements-summary__metric-value">{latestDraft ? latestDraft.id : "--"}</strong>
            <span className="requirements-summary__metric-note">{latestDraft ? draftLabel(latestDraft) : "暂未生成草稿"}</span>
          </div>
        </div>
      </Card>

      <div className="requirements-layout">
        <div className="requirements-left">
          <Card title="需求文档输入" subtitle="粘贴需求或上传 .txt/.md，点击后直接按功能测试用例规范生成草稿。">
            <div className="settings-note">当前模型：{modelLabel}</div>

            <label className="field-label" htmlFor="requirement-title">
              需求标题
            </label>
            <input className="text-input" id="requirement-title" value={title} onChange={(event) => setTitle(event.target.value)} />

            <label className="field-label" htmlFor="requirement-document">
              需求正文
            </label>
            <textarea
              className="textarea-mock textarea-real requirement-textarea"
              id="requirement-document"
              value={document}
              onChange={(event) => setDocument(event.target.value)}
            />

            <div className="button-row">
              <label className="btn btn--soft upload-button">
                上传 .txt/.md
                <input accept=".txt,.md,text/plain,text/markdown" type="file" onChange={(event) => void handleUpload(event.target.files?.[0] || null)} />
              </label>
              <button className="btn btn--green" disabled={busy || !canAnalyze} onClick={analyze} type="button">
                创建与分析
              </button>
            </div>
          </Card>

          <Card title="历史需求" subtitle="点击打开历史需求；删除会同时清理其关联的测试点和草稿。">
            <div className="requirement-list">
              {requirements.length ? (
                requirements.map((item) => (
                  <div className={`requirement-list__item ${item.id === requirement?.id ? "is-active" : ""}`} key={item.id}>
                    <button className="requirement-list__open" onClick={() => void openRequirement(item.id)} type="button">
                      <strong>{item.title}</strong>
                      <span>
                        {safeCount(item.draft_count)} 个用例草稿 · {safeCount(item.test_point_count)} 个测试点
                      </span>
                    </button>
                    <button
                      className="requirement-list__delete"
                      disabled={busy}
                      onClick={(event) => {
                        event.stopPropagation();
                        void handleDeleteRequirement(item);
                      }}
                      title="删除需求"
                      type="button"
                      aria-label="删除需求"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                        <path d="M10 11v6" />
                        <path d="M14 11v6" />
                        <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
                      </svg>
                    </button>
                  </div>
                ))
              ) : (
                <p className="empty-state">暂无需求记录。</p>
              )}
            </div>
          </Card>
        </div>

        <div className="requirements-center">
          <Card className="requirements-table-card" title="AI 生成测试用例" subtitle="点击一条草稿后，右侧会同步展示完整 YAML 预览和导出入口。">
            <div className="requirements-table-wrap">
              <table className="table editable-table">
                <thead>
                  <tr>
                    <th>用例标题</th>
                    <th>模板</th>
                    <th>状态</th>
                    <th>更新时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {drafts.length ? (
                    drafts.map((draft) => (
                      <tr key={draft.id} className={selectedDraft?.id === draft.id ? "is-active" : ""}>
                        <td>{draftLabel(draft)}</td>
                        <td>{draft.template || "spec"}</td>
                        <td>{draft.status}</td>
                        <td>{draft.updated_at}</td>
                        <td>
                          <button
                            className="link-button"
                            onClick={() => {
                              setSelectedDraftId(draft.id);
                              setYamlPreview(draft.yaml);
                            }}
                            type="button"
                          >
                            查看 YAML
                          </button>
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={5}>暂无测试用例草稿。点击“创建与分析”后会按规范自动生成。</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        <div className="requirements-right">
          <Card title="覆盖度与风险提示" subtitle="把当前需求的摘要、风险和导出操作集中在一列，方便边看边导。">
            <div className="button-row">
              <StatusPill tone="green">{`草稿 ${caseCount} 条`}</StatusPill>
              <StatusPill tone="amber">{`P0 ${p0Count} 条`}</StatusPill>
              <StatusPill tone="blue">{`最新草稿 ${latestDraft ? draftLabel(latestDraft) : "暂无"}`}</StatusPill>
            </div>
            <p className="risk-copy">{requirement?.analysis_summary || "这里会显示模型生成的测试用例摘要。"}</p>
            <p className="risk-copy">{requirement?.risk_summary || "这里会显示风险提示与复核建议。"}</p>
            <div className="button-row">
              <button className="btn btn--primary" disabled={busy || !requirement || !drafts.length} onClick={() => void exportCases("xlsx")} type="button">
                导出 XLSX
              </button>
              <button className="btn btn--outline" disabled={busy || !requirement || !drafts.length} onClick={() => void exportCases("yaml")} type="button">
                导出 YAML
              </button>
            </div>
            <div className="requirements-status-line">{status}</div>
          </Card>

          <Card className="markdown-card" title="YAML 草稿预览" subtitle={selectedDraft ? `草稿 #${selectedDraft.id}` : "先选择一条草稿预览。"}>
            <pre className="markdown-preview">{yamlPreview || "生成后会在这里预览单条测试用例 YAML。"}</pre>
          </Card>
        </div>
      </div>
    </div>
  );
}
