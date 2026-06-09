import { useEffect, useState } from "react";
import { api, type ApiCase, type CaseDraft, type CaseDraftValidation } from "../data/api";
import { Card } from "../components/Card";
import { FlowSteps } from "../components/FlowSteps";
import { StatusPill } from "../components/StatusPill";

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

export function CaseToolbox() {
  const [cases, setCases] = useState<ApiCase[]>([]);
  const [drafts, setDrafts] = useState<CaseDraft[]>([]);
  const [selectedDraftId, setSelectedDraftId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [yaml, setYaml] = useState("");
  const [caseId, setCaseId] = useState("TC-ICM-013");
  const [filename, setFilename] = useState("tc-icm-013-generated.yaml");
  const [status, setStatus] = useState("正在读取用例资产...");
  const [busy, setBusy] = useState(false);
  const [validation, setValidation] = useState<CaseDraftValidation | null>(null);

  const selectedDraft = drafts.find((draft) => draft.id === selectedDraftId) || null;

  async function refresh() {
    setBusy(true);
    try {
      const [caseResult, draftResult] = await Promise.allSettled([api.cases(), api.caseDrafts()]);
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
        const active = selectedDraftId ? draftResult.value.find((item) => item.id === selectedDraftId) : draftResult.value[0];
        if (active) selectDraft(active);
        messages.push(`${draftResult.value.length} 条 YAML 草稿`);
      } else {
        setDrafts([]);
        messages.push(`YAML 草稿暂不可用：${errorMessage(draftResult.reason)}`);
      }

      setStatus(messages.join("；"));
    } catch (error) {
      setStatus(`读取用例资产失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function selectDraft(draft: CaseDraft) {
    const nextCaseId = defaultCaseId(draft);
    setSelectedDraftId(draft.id);
    setTitle(draft.title);
    setYaml(draft.yaml);
    setCaseId(nextCaseId);
    setFilename(draft.promoted_path ? draft.promoted_path.split(/[\\/]/).pop() || defaultFilename(nextCaseId) : defaultFilename(nextCaseId));
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
      const caseItems = await api.cases();
      setCases(caseItems);
      setStatus(`已转正式 case：${promoted.promoted_case_id}`);
    } catch (error) {
      setStatus(`转正式 case 失败：${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="page">
      <FlowSteps activeIndex={3} />
      <div className="case-layout case-layout--wide">
        <div className="case-sidebar">
          <Card className="case-list-card" title="正式用例列表" subtitle="来自 test-cases/icm/*.yaml">
            <table className="table">
              <thead>
                <tr><th>Case</th><th>状态</th><th>脚本</th></tr>
              </thead>
              <tbody>
                {cases.map((item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td>
                    <td>{item.has_automation_asset ? "已沉淀" : item.status}</td>
                    <td>Python</td>
                  </tr>
                ))}
                {!cases.length ? (
                  <tr><td colSpan={3}>暂无正式 case；请确认后端已启动，或先将 YAML 草稿转正式 case。</td></tr>
                ) : null}
              </tbody>
            </table>
          </Card>

          <Card title="YAML 草稿库" subtitle="从测试点生成，人工确认后再转正式 case">
            <div className="draft-list">
              {drafts.map((draft) => (
                <button className={`draft-list__item ${draft.id === selectedDraftId ? "is-active" : ""}`} key={draft.id} onClick={() => selectDraft(draft)} type="button">
                  <strong>{draft.title}</strong>
                  <span>draft #{draft.id} · {draft.template || "functional"}</span>
                  <StatusPill tone={draftTone(draft.status)}>{draft.status}</StatusPill>
                </button>
              ))}
              {!drafts.length ? <p className="empty-state">还没有 YAML 草稿，请先到测试点思维导图选中测试点生成。</p> : null}
            </div>
          </Card>
        </div>

        <div className="case-main">
          <Card title="YAML 草稿编辑" subtitle="草稿保存在 SQLite；保存后不会自动覆盖正式 case 文件。">
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
                <option value="">暂无草稿，请先到测试点思维导图生成</option>
              )}
            </select>
            {!drafts.length ? <p className="empty-state">还没有 YAML 草稿，草稿标题下拉对应为空。</p> : null}
            <label className="field-label">YAML 内容</label>
            <textarea className="code-block code-block--editor" value={yaml} onChange={(event) => setYaml(event.target.value)} placeholder="请选择一条草稿，或从测试点页面生成 YAML 草稿。" />
            <div className="button-row">
              <button className="btn btn--primary" disabled={busy || !selectedDraft} onClick={saveDraft} type="button">保存草稿</button>
              <button className="btn btn--outline" disabled={busy || !selectedDraft} onClick={validateDraft} type="button">校验 YAML</button>
              <button className="btn btn--outline" disabled={busy} onClick={refresh} type="button">刷新</button>
              <span className="muted">{status}</span>
            </div>
          </Card>

          <Card className="asset-card" title="转正式 case" subtitle="显式确认后写入 test-cases/icm/*.yaml；若文件已存在会拒绝覆盖。">
            <div className="promote-grid">
              <label>
                <span className="field-label">正式 Case ID</span>
                <input className="text-input" value={caseId} onChange={(event) => {
                  const value = event.target.value;
                  setCaseId(value);
                  setFilename(defaultFilename(value));
                }} />
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
            <div className={`validation-panel ${validation?.valid ? "validation-panel--ok" : validation ? "validation-panel--error" : ""}`}>
              <div className="validation-panel__header">
                <strong>YAML 质量门禁</strong>
                {validation ? <StatusPill tone={validation.valid ? "green" : "red"}>{validation.valid ? "通过" : "未通过"}</StatusPill> : <StatusPill tone="blue">待校验</StatusPill>}
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
            <button className="btn btn--green" disabled={busy || !selectedDraft} onClick={promoteDraft} type="button">转正式 case 文件</button>
          </Card>
        </div>
      </div>
    </div>
  );
}
