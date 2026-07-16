import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "../components/Card";
import { StatusPill } from "../components/StatusPill";
import { API_ORIGIN, api, type CodegenExperimentSession, type RecorderSession, type RecorderStep } from "../data/api";

const DEFAULT_START_URL = "https://192.168.16.203:49187/#/login";
const ACTIVE_STATUSES = new Set(["starting", "recording"]);

function statusTone(status: string) {
  if (status === "recording") return "blue";
  if (status === "stopped") return "amber";
  if (status === "failed") return "red";
  return "dark";
}

function stepLabel(step: RecorderStep) {
  const names: Record<string, string> = { goto: "打开页面", click: "点击", fill: "输入", select: "选择", check: "勾选", press: "按键", download: "下载", popup: "新窗口" };
  return names[step.action] || step.action;
}

function stepDetail(step: RecorderStep) {
  return step.locator || step.url || step.value || "等待浏览器操作";
}

export function Recorder() {
  const [startUrl, setStartUrl] = useState(DEFAULT_START_URL);
  const [session, setSession] = useState<RecorderSession | null>(null);
  const [codegenSession, setCodegenSession] = useState<CodegenExperimentSession | null>(null);
  const [codegenInputValues, setCodegenInputValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("输入被测系统入口后启动独立录制浏览器。");
  const streamRef = useRef<EventSource | null>(null);

  const steps = session?.steps || [];
  const canStop = Boolean(session && ACTIVE_STATUSES.has(session.status));
  const candidate = session?.candidate || null;
  const warnings = candidate?.blocking_warnings || steps.flatMap((step) => step.warning ? [step.warning] : []);
  const failureMessage = session?.status === "failed" ? session.error || "录制浏览器未能启动。请检查入口网络和证书。" : null;

  const closeStream = () => {
    streamRef.current?.close();
    streamRef.current = null;
  };

  useEffect(() => () => closeStream(), []);

  useEffect(() => {
    if (!session?.id || !ACTIVE_STATUSES.has(session.status)) return;
    const timer = window.setInterval(() => {
      void api.recorderSession(session.id).then(setSession).catch((error: Error) => setMessage(error.message));
    }, 1600);
    return () => window.clearInterval(timer);
  }, [session?.id, session?.status]);

  useEffect(() => {
    if (!codegenSession?.id || (!ACTIVE_STATUSES.has(codegenSession.status) && !["queued", "running"].includes(codegenSession.run?.status || ""))) return;
    const timer = window.setInterval(() => {
      void api.codegenExperiment(codegenSession.id).then(setCodegenSession).catch((error: Error) => setMessage(error.message));
    }, 1600);
    return () => window.clearInterval(timer);
  }, [codegenSession?.id, codegenSession?.status, codegenSession?.run?.status]);

  function subscribe(sessionId: string, streamUrl?: string) {
    closeStream();
    const source = new EventSource(streamUrl || `${API_ORIGIN}/api/recordings/${encodeURIComponent(sessionId)}/stream`);
    streamRef.current = source;
    source.onmessage = (event) => {
      try {
        const update = JSON.parse(event.data) as Partial<RecorderSession> & { step?: RecorderStep };
        setSession((current) => {
          if (!current) return current;
          const nextSteps = update.step ? [...current.steps.filter((item) => item.id !== update.step?.id), update.step].sort((a, b) => a.sequence - b.sequence) : update.steps || current.steps;
          return { ...current, ...update, steps: nextSteps };
        });
      } catch {
        setMessage("录制事件格式无效，已改用状态轮询。");
      }
    };
    source.onerror = () => closeStream();
  }

  async function startRecording() {
    setBusy(true);
    try {
      const next = await api.createRecorderSession({ start_url: startUrl.trim() });
      setSession(next);
      subscribe(next.id, next.stream_url);
      setMessage("独立录制浏览器已启动；你的操作会实时出现在右侧步骤面板。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "录制会话启动失败");
    } finally {
      setBusy(false);
    }
  }

  async function stopRecording() {
    if (!session) return;
    setBusy(true);
    try {
      const next = await api.stopRecorderSession(session.id);
      setSession(next);
      closeStream();
      setMessage("录制已停止。请检查步骤和定位器，再生成候选脚本。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "停止录制失败");
    } finally {
      setBusy(false);
    }
  }

  async function startCodegenExperiment() {
    setBusy(true);
    try {
      const next = await api.createCodegenExperiment({ start_url: startUrl.trim() });
      setCodegenSession(next);
      setMessage("Codegen 实验浏览器已启动；关闭其录制窗口或点击结束实验后，平台只导入生成的 Python async 脚本供对比。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Codegen 实验启动失败");
    } finally {
      setBusy(false);
    }
  }

  async function stopCodegenExperiment() {
    if (!codegenSession) return;
    setBusy(true);
    try {
      const next = await api.stopCodegenExperiment(codegenSession.id);
      setCodegenSession(next);
      setMessage("Codegen 实验已结束；下方仅展示导入脚本，不会写入 Recorder 或回归资产。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Codegen 实验结束失败");
    } finally {
      setBusy(false);
    }
  }

  async function runCodegenExperiment() {
    if (!codegenSession) return;
    setBusy(true);
    try {
      const next = await api.runCodegenExperiment(codegenSession.id, { variables: codegenInputValues });
      setCodegenSession(next);
      setCodegenInputValues({});
      setMessage("Codegen 脚本正在专属实验进程中运行；结果不会写入 Recorder 或正式回归资产。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Codegen 脚本启动失败");
    } finally {
      setBusy(false);
    }
  }

  const stepCount = useMemo(() => `${steps.length} 个已记录步骤`, [steps.length]);
  const codegenInputs = codegenSession?.inputs || [];
  const codegenInputsComplete = codegenInputs.every((input) => !input.required || Boolean(codegenInputValues[input.name]));

  return (
    <div className="recorder-page">
      <section className="recorder-hero">
        <div>
          <span className="recorder-eyebrow">RECORDER / 隔离会话</span>
          <h1>把真实操作变成可审核的测试步骤</h1>
          <p>录制在平台启动的独立浏览器中进行；密码会脱敏，风险操作和不稳定定位器不会自动发布。</p>
        </div>
        {session ? <StatusPill tone={statusTone(session.status)}>会话 {session.status}</StatusPill> : null}
      </section>

      <Card className="recorder-control-card">
        <div className="recorder-controls">
          <label>
            <span>被测系统入口</span>
            <input value={startUrl} onChange={(event) => setStartUrl(event.target.value)} disabled={canStop || busy} placeholder="https://example.test/login" />
          </label>
          <div className="recorder-actions">
            <button className="btn btn--primary" type="button" onClick={startRecording} disabled={busy || canStop || !startUrl.trim()}>启动录制</button>
            <button className="btn btn--outline" type="button" onClick={stopRecording} disabled={busy || !canStop}>停止录制</button>
            <button className="btn btn--outline" type="button" onClick={stopRecording} disabled={busy || !session || canStop || !steps.length}>停止并生成候选</button>
          </div>
        </div>
        <p className="recorder-message" role="status">{message}</p>
        {failureMessage ? <p className="recorder-message recorder-alert" role="alert">{failureMessage}</p> : null}
      </Card>

      <Card className="codegen-experiment-card">
        <header className="recorder-section-heading"><div><span className="recorder-eyebrow">EXPERIMENT / PLAYWRIGHT CODEGEN</span><h2>Codegen 实验模式</h2><p>启动独立浏览器执行 <code>playwright codegen --target=python-async</code>；结果只用于与当前 Recorder 对比。</p></div>{codegenSession ? <StatusPill tone={statusTone(codegenSession.status)}>实验 {codegenSession.status}</StatusPill> : null}</header>
        <div className="codegen-experiment-actions">
          <button className="btn btn--outline" type="button" onClick={startCodegenExperiment} disabled={busy || ACTIVE_STATUSES.has(codegenSession?.status || "") || !startUrl.trim()}>启动 Codegen 实验</button>
          <button className="btn btn--outline" type="button" onClick={stopCodegenExperiment} disabled={busy || !codegenSession || !ACTIVE_STATUSES.has(codegenSession.status)}>结束并导入脚本</button>
          <button className="btn btn--primary" type="button" onClick={runCodegenExperiment} disabled={busy || !codegenSession?.script || codegenSession.status !== "stopped" || !codegenInputsComplete || ["queued", "running"].includes(codegenSession.run?.status || "")}>直接运行录制脚本</button>
        </div>
        {codegenInputs.length ? <section className="codegen-inputs"><h3>本次运行输入</h3><p>仅在本次浏览器进程中使用，启动后立即从页面状态清除，不会保存或显示在日志中。</p><div>{codegenInputs.map((input) => <label key={input.name}><span>{input.action} · {input.name}</span><input type="password" autoComplete="off" value={codegenInputValues[input.name] || ""} onChange={(event) => setCodegenInputValues((current) => ({ ...current, [input.name]: event.target.value }))} /></label>)}</div></section> : null}
        {codegenSession?.error ? <p className="recorder-message recorder-alert" role="alert">{codegenSession.error}</p> : null}
        {codegenSession?.run ? <p className={codegenSession.run.status === "failed" ? "recorder-message recorder-alert" : "recorder-message"}>脚本运行状态：{codegenSession.run.status}{codegenSession.run.error ? ` — ${codegenSession.run.error}` : ""}</p> : null}
        {codegenSession?.script ? <section className="codegen-script-preview"><h3>导入的 Python async 脚本（仅对比）</h3><pre>{codegenSession.script}</pre></section> : <p className="codegen-experiment-note">实验结束后才读取输出文件；不会实时接管 Codegen，也不会生成 Recorder 的 DSL、候选脚本或发布记录。</p>}
      </Card>

      <div className="recorder-grid">
        <Card className="recorder-steps-card">
          <header className="recorder-section-heading"><div><h2>实时步骤</h2><p>{stepCount}</p></div>{session?.current_url ? <code>{session.current_url}</code> : null}</header>
          {steps.length ? <ol className="recorder-step-list">{steps.map((step) => <li key={step.id} className={step.status === "blocked" ? "is-blocked" : step.warning ? "has-warning" : ""}><span>{step.sequence}</span><div><strong>{stepLabel(step)}</strong><code>{stepDetail(step)}</code>{step.value && step.locator ? <small>值：{step.value}</small> : null}{step.warning ? <small className="recorder-warning">{step.warning}</small> : null}</div></li>)}</ol> : <div className="recorder-empty">启动录制后，这里会实时显示点击、输入、跳转和窗口操作。</div>}
        </Card>

        <Card className="recorder-candidate-card">
          <header className="recorder-section-heading"><div><h2>候选脚本</h2><p>仅供审核，未自动加入回归集</p></div>{candidate ? <StatusPill tone={candidate.publishable ? "green" : "amber"}>{candidate.publishable ? "可提交审核" : "需修正"}</StatusPill> : null}</header>
          {candidate ? <div className="recorder-code-tabs"><section><h3>测试 DSL（YAML）</h3><pre>{candidate.yaml || "后端尚未返回 YAML 候选。"}</pre></section><section><h3>Playwright Python</h3><pre>{candidate.playwright_python || "后端尚未返回 Playwright Python 候选。"}</pre></section></div> : <div className="recorder-empty">停止录制后，平台会生成 DSL 与 Playwright Python 候选脚本。</div>}
          {warnings.length ? <aside className="recorder-alert"><strong>发布阻断</strong><ul>{[...new Set(warnings)].map((warning) => <li key={warning}>{warning}</li>)}</ul></aside> : null}
        </Card>
      </div>
    </div>
  );
}
