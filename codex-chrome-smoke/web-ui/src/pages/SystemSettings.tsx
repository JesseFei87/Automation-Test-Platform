import { useEffect, useState } from "react";
import { Card } from "../components/Card";
import { StatusPill } from "../components/StatusPill";
import { useToast } from "../components/Toast";
import { api, type AISettings, type ApiElementKnowledgeEnvironment, type ApiElementKnowledgeRefreshTask, type OllamaModel, type PlatformSettings, type SystemHealth } from "../data/api";

const MODEL_PRESETS = {
  "minimax-m3": {
    provider: "minimax-m3",
    base_url: "https://api.minimaxi.com/v1",
    model: "MiniMax-M3",
    api_key: "",
  },
  "ollama-local": {
    provider: "ollama-local",
    base_url: "http://192.168.12.38:11434/v1",
    model: "qwen3.6:35b",
    api_key: "",
  },
} as const;

const DEFAULT_PLATFORM_SETTINGS: PlatformSettings = {
  runner: {
    browser_mode: "background",
    queue_mode: "serial",
    screenshot_policy: "latest_plus_failed_archive",
    headless: true,
    maximize_window: false,
    viewport_mode: "fixed",
    viewport_width: 1600,
    viewport_height: 1100,
    ignore_https_errors: true,
  },
  asset_policy: {
    observed_asset_enabled: true,
    allow_passed_run_merge: true,
    merge_strategy: "conservative",
    require_verified_before_regression: true,
  },
  environment: {
    icm_base_url: "https://192.168.16.203:49187",
    icm_login_url: "https://192.168.16.203:49187/#/login?redirect=%2Fredirect",
    dev_portal_base_url: "https://dev.tcsoft.net.cn",
    dev_login_url: "https://dev.tcsoft.net.cn/login?redirect=%2Fredirect",
    remote_help_url: "https://dev.tcsoft.net.cn/hubble/remoteHelpInfo",
  },
  accounts: {
    labo: { username: "labo", has_password: true, password_masked: "****1111" },
    jesse: { username: "jesse", has_password: true, password_masked: "****3456" },
    tester: { username: "Tester", has_password: true, password_masked: "****3456" },
    admin: { username: "admin", has_password: true, password_masked: "****1088" },
  },
};

const ACCOUNT_LABELS: Record<keyof PlatformSettings["accounts"], string> = {
  labo: "labo 屏幕墙账号",
  jesse: "jesse 工单侧账号",
  tester: "Tester 回归账号",
  admin: "admin 管理账号",
};

type AIForm = {
  provider: string;
  base_url: string;
  model: string;
  api_key: string;
};

type SystemSettingsProps = {
  onAISettingsChange?: () => void | Promise<void>;
};

function mergePlatformSettings(platform: PlatformSettings): PlatformSettings {
  return {
    ...DEFAULT_PLATFORM_SETTINGS,
    ...platform,
    runner: { ...DEFAULT_PLATFORM_SETTINGS.runner, ...platform.runner },
    asset_policy: { ...DEFAULT_PLATFORM_SETTINGS.asset_policy, ...platform.asset_policy },
    environment: { ...DEFAULT_PLATFORM_SETTINGS.environment, ...platform.environment },
    accounts: {
      ...DEFAULT_PLATFORM_SETTINGS.accounts,
      ...platform.accounts,
    },
  };
}

export function SystemSettings({ onAISettingsChange }: SystemSettingsProps) {
  const toast = useToast();
  const [aiSettings, setAiSettings] = useState<AISettings | null>(null);
  const [aiForm, setAiForm] = useState<AIForm>({ ...MODEL_PRESETS["minimax-m3"] });
  const [platformSettings, setPlatformSettings] = useState<PlatformSettings>(DEFAULT_PLATFORM_SETTINGS);
  const [accountPasswords, setAccountPasswords] = useState<Record<string, string>>({});
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  const [status, setStatus] = useState("正在读取系统设置...");
  const [aiActionNotice, setAiActionNotice] = useState("");
  const [elementPreview, setElementPreview] = useState<ApiElementKnowledgeEnvironment[]>([]);
  const [selectedElementEnvId, setSelectedElementEnvId] = useState("");
  const [elementTargetUrl, setElementTargetUrl] = useState(DEFAULT_PLATFORM_SETTINGS.environment.icm_login_url);
  const [elementTargetPageId, setElementTargetPageId] = useState("login");
  const [elementTargetName, setElementTargetName] = useState("被测系统登录页");
  const [elementTask, setElementTask] = useState<ApiElementKnowledgeRefreshTask | null>(null);
  const [elementNotice, setElementNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [testingAIConnection, setTestingAIConnection] = useState(false);

  useEffect(() => {
    void loadSettings();
    void loadElementPreview();
  }, []);

  useEffect(() => {
    if (!elementTask?.id || !["queued", "running"].includes(elementTask.status)) return;
    const timer = window.setTimeout(() => {
      void pollElementTask(elementTask.id);
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [elementTask?.id, elementTask?.status]);

  async function loadElementPreview() {
    try {
      const result = await api.elementKnowledgeEnvironmentPreview();
      setElementPreview(result);
      if (!selectedElementEnvId && result[0]?.id) setSelectedElementEnvId(result[0].id);
    } catch (error) {
      setElementNotice(`读取元素知识库扫描环境失败：${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  function applyElementTask(task: ApiElementKnowledgeRefreshTask) {
    setElementTask(task);
    if (["queued", "running"].includes(task.status)) {
      setElementNotice(`扫描任务${task.status === "queued" ? "已排队" : "运行中"}：${task.id}`);
      return;
    }
    if (task.status === "done" || task.status === "passed") {
      setElementNotice(`扫描完成：${task.id}`);
      void loadElementPreview();
      return;
    }
    if (task.status === "failed") {
      setElementNotice(`扫描失败：${task.error || "unknown error"}`);
      return;
    }
    setElementNotice(`扫描任务状态：${task.status}`);
  }

  async function pollElementTask(taskId: string) {
    try {
      applyElementTask(await api.elementKnowledgeRefreshTask(taskId));
    } catch (error) {
      setElementNotice(`查询扫描任务失败：${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  async function startElementScan() {
    if (!elementTargetUrl.trim()) {
      setElementNotice("请先填写要扫描的 target_url");
      return;
    }
    setElementNotice("正在创建元素知识库扫描任务...");
    try {
      const task = await api.refreshElementKnowledge({
        no_scan: false,
        environment_id: selectedElementEnvId || undefined,
        target_url: elementTargetUrl.trim(),
        target_page_id: elementTargetPageId.trim() || "login",
        target_name: elementTargetName.trim() || elementTargetPageId.trim() || "被测系统页面",
        include_states: true,
        headless: platformSettings.runner.headless,
        min_healing_failures: 1,
      });
      applyElementTask(task);
    } catch (error) {
      setElementNotice(`创建扫描任务失败：${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  async function loadSettings() {
    setBusy(true);
    try {
      const [ai, platform, healthResult] = await Promise.all([
        api.aiSettings(),
        api.platformSettings(),
        api.systemHealth(),
      ]);
      setAiSettings(ai);
      setAiForm({
        provider: ai.provider || MODEL_PRESETS["minimax-m3"].provider,
        base_url: ai.base_url || MODEL_PRESETS["minimax-m3"].base_url,
        model: ai.model || MODEL_PRESETS["minimax-m3"].model,
        api_key: "",
      });
      setPlatformSettings(mergePlatformSettings(platform));
      setAccountPasswords({});
      setHealth(healthResult);
      if (ai.provider === "ollama-local") {
        await loadOllamaModels(ai.base_url, ai.model);
      } else {
        setOllamaModels([]);
      }
      setStatus("系统设置已加载");
    } catch (error) {
      setStatus(`读取失败：${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setBusy(false);
    }
  }

  function applyModelPreset(provider: keyof typeof MODEL_PRESETS) {
    const preset = MODEL_PRESETS[provider];
    setAiForm({ ...preset });
    if (provider === "ollama-local") {
      void loadOllamaModels(preset.base_url, preset.model);
    } else {
      setOllamaModels([]);
    }
  }

  async function loadOllamaModels(baseUrl = aiForm.base_url, preferredModel = aiForm.model) {
    try {
      const result = await api.ollamaModels(baseUrl);
      const modelNames = result.models.map((item) => item.model || item.name).filter(Boolean);
      const nextModel = modelNames.includes(preferredModel)
        ? preferredModel
        : modelNames.includes("qwen3.6:35b")
          ? "qwen3.6:35b"
          : modelNames[0] || preferredModel;
      setOllamaModels(result.models);
      setAiForm((current) => ({ ...current, model: nextModel }));
      setStatus(`已读取 ${result.models.length} 个 Ollama 模型`);
    } catch (error) {
      setOllamaModels([]);
      setStatus(`读取 Ollama 模型失败：${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  async function saveAISettings() {
    setBusy(true);
    try {
      const saved = await api.saveAISettings({
        provider: aiForm.provider,
        base_url: aiForm.base_url,
        model: aiForm.model,
        ...(aiForm.api_key.trim() ? { api_key: aiForm.api_key.trim() } : {}),
      });
      setAiSettings(saved);
      setAiForm((current) => ({ ...current, api_key: "" }));
      const message = `AI 设置已保存：${saved.provider} / ${saved.model}`;
      setStatus(message);
      setAiActionNotice(message);
      toast.show({ kind: "success", message: "AI 设置保存成功" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "unknown error";
      setStatus(`AI 设置保存失败：${message}`);
      setAiActionNotice(`AI 设置保存失败：${message}`);
    } finally {
      setBusy(false);
    }
  }

  async function testAIConnection() {
    setTestingAIConnection(true);
    setAiActionNotice("");
    setStatus(`正在测试 AI 连接：${aiForm.provider} / ${aiForm.model}，请稍候...`);
    try {
      const result = await api.testAIConnection();
      const message = `AI 连接成功：${result.provider} / ${result.model}`;
      setStatus(message);
      setAiActionNotice(message);
      await onAISettingsChange?.();
    } catch (error) {
      const message = error instanceof Error ? error.message : "unknown error";
      setStatus(`AI 连接失败：${message}`);
      setAiActionNotice(`AI 连接失败：${message}`);
    } finally {
      setTestingAIConnection(false);
    }
  }

  async function savePlatformSettings(nextSettings = platformSettings) {
    setBusy(true);
    try {
      const accounts = Object.fromEntries(
        Object.entries(nextSettings.accounts).map(([key, value]) => [
          key,
          {
            username: value.username,
            ...(accountPasswords[key]?.trim() ? { password: accountPasswords[key].trim() } : {}),
          },
        ]),
      ) as PlatformSettings["accounts"];
      const saved = await api.savePlatformSettings({
        runner: nextSettings.runner,
        asset_policy: nextSettings.asset_policy,
        environment: nextSettings.environment,
        accounts,
      });
      setPlatformSettings(mergePlatformSettings(saved));
      setAccountPasswords({});
      setStatus("平台设置已保存");
      toast.show({ kind: "success", message: "平台设置保存成功" });
      await refreshHealth();
    } catch (error) {
      setStatus(`平台设置保存失败：${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setBusy(false);
    }
  }

  async function refreshHealth() {
    try {
      setHealth(await api.systemHealth());
    } catch (error) {
      setStatus(`健康检查失败：${error instanceof Error ? error.message : "unknown error"}`);
    }
  }

  function patchRunner(patch: Partial<PlatformSettings["runner"]>) {
    setPlatformSettings((current) => ({
      ...current,
      runner: { ...current.runner, ...patch },
    }));
  }

  function patchEnvironment(patch: Partial<PlatformSettings["environment"]>) {
    setPlatformSettings((current) => ({
      ...current,
      environment: { ...current.environment, ...patch },
    }));
  }

  function setBrowserMode(browserMode: string) {
    patchRunner({ browser_mode: browserMode, headless: browserMode === "background" });
  }

  function patchAccount(key: keyof PlatformSettings["accounts"], username: string) {
    setPlatformSettings((current) => ({
      ...current,
      accounts: {
        ...current.accounts,
        [key]: { ...current.accounts[key], username },
      },
    }));
  }

  const selectedElementEnv = elementPreview.find((item) => item.id === selectedElementEnvId);

  return (
    <div className="page settings-page">
      <div className="settings-grid">
        <Card
          title="AI 模型设置"
          subtitle={
            aiSettings?.has_api_key
              ? `已保存 Key：${aiSettings.api_key_masked}`
              : "Minimax 需要 Key，Ollama 本地模型通常无需 Key。"
          }
        >
          <label className="field-label">Provider</label>
          <select
            className="text-input"
            value={aiForm.provider}
            onChange={(event) => applyModelPreset(event.target.value as keyof typeof MODEL_PRESETS)}
          >
            <option value="minimax-m3">Minimax M3 Token Plan</option>
            <option value="ollama-local">本地 Ollama</option>
          </select>

          <div className="button-row model-presets">
            <button className="btn btn--soft" onClick={() => applyModelPreset("minimax-m3")} type="button">
              切到 Minimax-M3
            </button>
            <button className="btn btn--soft" onClick={() => applyModelPreset("ollama-local")} type="button">
              切到 Ollama
            </button>
          </div>

          <label className="field-label">Base URL</label>
          <input
            className="text-input"
            value={aiForm.base_url}
            onChange={(event) => setAiForm((current) => ({ ...current, base_url: event.target.value }))}
          />

          {aiForm.provider === "ollama-local" ? (
            <>
              <div className="button-row">
                <button className="btn btn--outline" disabled={busy} onClick={() => loadOllamaModels()} type="button">
                  刷新 Ollama 模型
                </button>
                <span className="muted">
                  {ollamaModels.length ? `${ollamaModels.length} 个模型可选` : "尚未读取模型列表"}
                </span>
              </div>
              <label className="field-label">Ollama 模型</label>
              <select
                className="text-input"
                value={aiForm.model}
                onChange={(event) => setAiForm((current) => ({ ...current, model: event.target.value }))}
              >
                {ollamaModels.length
                  ? ollamaModels.map((item) => {
                      const modelName = item.model || item.name;
                      return (
                        <option key={modelName} value={modelName}>
                          {modelName}
                        </option>
                      );
                    })
                  : (
                    <option value={aiForm.model}>{aiForm.model}</option>
                  )}
              </select>
            </>
          ) : null}

          <label className="field-label">Model</label>
          <input
            className="text-input"
            value={aiForm.model}
            onChange={(event) => setAiForm((current) => ({ ...current, model: event.target.value }))}
          />

          <label className="field-label">Subscription Key / API Key</label>
          <input
            className="text-input"
            type="password"
            placeholder={
              aiForm.provider === "ollama-local"
                ? "Ollama 通常无需填写"
                : aiSettings?.has_api_key
                  ? "留空表示继续使用已保存 Key"
                  : "请输入 Token Plan Key"
            }
            value={aiForm.api_key}
            onChange={(event) => setAiForm((current) => ({ ...current, api_key: event.target.value }))}
          />

          <div className="button-row">
            <button className="btn btn--primary" disabled={busy} onClick={saveAISettings} type="button">
              保存 AI 设置
            </button>
            <button
              className="btn btn--outline"
              disabled={busy || testingAIConnection}
              onClick={testAIConnection}
              type="button"
            >
              {testingAIConnection ? (
                <>
                  <span className="inline-spinner" />
                  测试中...
                </>
              ) : (
                "测试连接"
              )}
            </button>
          </div>

          {aiActionNotice ? <div className="settings-note settings-note--success">{aiActionNotice}</div> : null}
          {testingAIConnection ? (
            <div className="settings-note settings-note--progress">
              正在请求后端并等待模型响应，连接完成后会自动刷新右上角模型名称。
            </div>
          ) : null}
        </Card>

        <Card
          title="环境与账号配置"
          subtitle="URL 和账号保存在本机后端；密码只可更新，不会在前端明文回显。"
        >
          <label className="field-label">ICM base_url</label>
          <input
            className="text-input"
            value={platformSettings.environment.icm_base_url}
            onChange={(event) => patchEnvironment({ icm_base_url: event.target.value })}
          />

          <label className="field-label">ICM 登录页</label>
          <input
            className="text-input"
            value={platformSettings.environment.icm_login_url}
            onChange={(event) => patchEnvironment({ icm_login_url: event.target.value })}
          />

          <label className="field-label">dev portal base_url</label>
          <input
            className="text-input"
            value={platformSettings.environment.dev_portal_base_url}
            onChange={(event) => patchEnvironment({ dev_portal_base_url: event.target.value })}
          />

          <label className="field-label">dev portal 登录页</label>
          <input
            className="text-input"
            value={platformSettings.environment.dev_login_url}
            onChange={(event) => patchEnvironment({ dev_login_url: event.target.value })}
          />

          <label className="field-label">远程协助信息页</label>
          <input
            className="text-input"
            value={platformSettings.environment.remote_help_url}
            onChange={(event) => patchEnvironment({ remote_help_url: event.target.value })}
          />

          <div className="account-grid">
            {Object.entries(platformSettings.accounts).map(([key, account]) => (
              <div className="account-row" key={key}>
                <div>
                  <strong>{ACCOUNT_LABELS[key as keyof PlatformSettings["accounts"]]}</strong>
                  <span>{account.has_password ? `已保存 ${account.password_masked}` : "未保存密码"}</span>
                </div>
                <input
                  className="text-input"
                  value={account.username}
                  onChange={(event) => patchAccount(key as keyof PlatformSettings["accounts"], event.target.value)}
                />
                <input
                  className="text-input"
                  type="password"
                  placeholder="留空表示不修改密码"
                  value={accountPasswords[key] ?? ""}
                  onChange={(event) => setAccountPasswords((current) => ({ ...current, [key]: event.target.value }))}
                />
              </div>
            ))}
          </div>

          <button className="btn btn--green" disabled={busy} onClick={() => savePlatformSettings()} type="button">
            保存环境与账号
          </button>
        </Card>

        <Card
          title="元素知识库扫描预览 / 验证"
          subtitle="直接复用上方环境与账号配置，验证登录态并触发后台扫描刷新。"
        >
          <label className="field-label">扫描环境（可选，用于读取登录态配置）</label>
          <select className="text-input" value={selectedElementEnvId} onChange={(event) => setSelectedElementEnvId(event.target.value)}>
            <option value="">不使用环境页面清单</option>
            {elementPreview.length ? elementPreview.map((item) => (
              <option key={item.id} value={item.id}>{item.name || item.id}</option>
            )) : null}
          </select>

          <label className="field-label">Target URL</label>
          <input className="text-input" value={elementTargetUrl} onChange={(event) => setElementTargetUrl(event.target.value)} placeholder="https://host/#/login" />
          <label className="field-label">Target Page ID</label>
          <input className="text-input" value={elementTargetPageId} onChange={(event) => setElementTargetPageId(event.target.value)} placeholder="login" />
          <label className="field-label">Target Name</label>
          <input className="text-input" value={elementTargetName} onChange={(event) => setElementTargetName(event.target.value)} placeholder="被测系统登录页" />

          <div className="health-grid">
            <HealthLine label="配置来源" value={selectedElementEnv?.source || "-"} ok={Boolean(selectedElementEnv)} />
            <HealthLine label="Base URL" value={selectedElementEnv?.base_url || "-"} ok={Boolean(selectedElementEnv?.base_url)} />
            <HealthLine label="登录配置" value={selectedElementEnv?.login_configured ? "已配置登录页和账号" : "未配置登录"} ok={Boolean(selectedElementEnv?.login_configured)} />
            <HealthLine label="Storage State" value={selectedElementEnv?.storage_state_updated_at || selectedElementEnv?.storage_state_path || selectedElementEnv?.storage_state || "未生成"} ok={Boolean(selectedElementEnv?.storage_state_exists)} />
            <HealthLine label="扫描页面数" value={`${selectedElementEnv?.page_count ?? selectedElementEnv?.pages?.length ?? 0} 个页面`} ok={Boolean((selectedElementEnv?.page_count ?? selectedElementEnv?.pages?.length ?? 0) > 0)} />
            <HealthLine label="任务状态" value={elementTask ? `${elementTask.id} · ${elementTask.status}` : "尚未触发"} ok={elementTask ? ["done", "passed"].includes(elementTask.status) : true} />
          </div>

          {elementTask?.progress ? (
            <div className="settings-note settings-note--progress">
              当前阶段：{elementTask.progress.stage || "-"}
              {elementTask.progress.current_page ? `，页面：${elementTask.progress.current_page}` : ""}
              {elementTask.progress.page_total ? `，进度：${elementTask.progress.page_index || 0}/${elementTask.progress.page_total}` : ""}
              {typeof elementTask.progress.element_count === "number" ? `，元素：${elementTask.progress.element_count}` : ""}
            </div>
          ) : null}

          {elementNotice ? <div className="settings-note">{elementNotice}</div> : null}

          <div className="button-row">
            <button className="btn btn--outline" disabled={busy} onClick={loadElementPreview} type="button">
              刷新预览
            </button>
            <button className="btn btn--primary" disabled={busy || !elementTargetUrl.trim() || elementTask?.status === "queued" || elementTask?.status === "running"} onClick={startElementScan} type="button">
              验证并扫描元素知识库
            </button>
          </div>
        </Card>

        <Card
          title="Runner 执行设置"
          subtitle="控制后台 runner 的运行方式；执行中心发起任务时会读取这些设置。"
        >
          <label className="field-label">浏览器模式</label>
          <select
            className="text-input"
            value={platformSettings.runner.browser_mode}
            onChange={(event) => setBrowserMode(event.target.value)}
          >
            <option value="background">后台独立浏览器</option>
            <option value="visible">可视化浏览器</option>
          </select>

          <div className="settings-note">
            {platformSettings.runner.browser_mode === "background"
              ? "后台独立浏览器会自动使用 headless=true，不打扰前台操作。"
              : "可视化浏览器会自动使用 headless=false，方便观察调试过程。"}
          </div>

          <label className="settings-check">
            <input
              type="checkbox"
              checked={platformSettings.runner.maximize_window}
              onChange={(event) => patchRunner({ maximize_window: event.target.checked })}
            />
            启动时最大化浏览器窗口
          </label>

          <label className="field-label">网页视口模式</label>
          <select
            className="text-input"
            value={platformSettings.runner.viewport_mode}
            onChange={(event) => patchRunner({ viewport_mode: event.target.value as "fixed" | "window" })}
          >
            <option value="fixed">固定视口</option>
            <option value="window">跟随浏览器窗口</option>
          </select>

          {platformSettings.runner.viewport_mode === "fixed" ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <label className="field-label">
                视口宽度
                <input
                  className="text-input"
                  type="number"
                  min="320"
                  max="7680"
                  value={platformSettings.runner.viewport_width}
                  onChange={(event) => patchRunner({ viewport_width: Number(event.target.value) || 1600 })}
                />
              </label>
              <label className="field-label">
                视口高度
                <input
                  className="text-input"
                  type="number"
                  min="240"
                  max="4320"
                  value={platformSettings.runner.viewport_height}
                  onChange={(event) => patchRunner({ viewport_height: Number(event.target.value) || 1100 })}
                />
              </label>
            </div>
          ) : null}

          <label className="settings-check">
            <input
              type="checkbox"
              checked={platformSettings.runner.ignore_https_errors}
              onChange={(event) => patchRunner({ ignore_https_errors: event.target.checked })}
            />
            忽略 HTTPS 证书错误
          </label>

          <label className="field-label">队列模式</label>
          <select
            className="text-input"
            value={platformSettings.runner.queue_mode}
            onChange={(event) => patchRunner({ queue_mode: event.target.value })}
          >
            <option value="serial">串行执行</option>
            <option value="limited_parallel">小并发预留</option>
          </select>

          <label className="field-label">截图策略</label>
          <select
            className="text-input"
            value={platformSettings.runner.screenshot_policy}
            onChange={(event) => patchRunner({ screenshot_policy: event.target.value })}
          >
            <option value="latest_plus_failed_archive">latest 覆盖 + 失败归档</option>
            <option value="always_archive">每次都归档</option>
          </select>

          <button className="btn btn--green" disabled={busy} onClick={() => savePlatformSettings()} type="button">
            保存 Runner 设置
          </button>
        </Card>

        <Card title="系统健康检查" subtitle={status}>
          <div className="settings-status">
            <StatusPill tone={health?.api.status === "ok" ? "green" : "red"}>Backend API</StatusPill>
            <StatusPill tone={health?.runner.status === "ok" ? "green" : "red"}>Runner</StatusPill>
            <StatusPill tone={health?.playwright.available ? "green" : "red"}>Playwright</StatusPill>
            <StatusPill tone={health?.playwright.chrome_available ? "green" : "red"}>Chrome</StatusPill>
          </div>

          <div className="health-grid">
            <HealthLine label="Runner 入口" value={health?.runner.path} ok={health?.runner.status === "ok"} />
            <HealthLine label="Chrome 路径" value={health?.playwright.chrome_path || "未发现"} ok={health?.playwright.chrome_available} />
            <HealthLine
              label="SQLite"
              value={health ? `${health.sqlite.path} · ${health.sqlite.updated_at || "未更新"}` : ""}
              ok={health?.sqlite.exists}
            />
            {health
              ? Object.entries(health.paths).map(([key, item]) => (
                  <HealthLine
                    key={key}
                    label={key}
                    value={`${item.path} · ${item.updated_at || "未更新"}`}
                    ok={item.exists && item.is_dir}
                  />
                ))
              : null}
          </div>

          <p className="analysis-copy">设置更新时间：{platformSettings.updated_at || "尚未保存"}</p>
          <div className="button-row">
            <button className="btn btn--outline" disabled={busy} onClick={loadSettings} type="button">
              重新读取设置
            </button>
            <button className="btn btn--soft" disabled={busy} onClick={refreshHealth} type="button">
              刷新健康检查
            </button>
          </div>
        </Card>
      </div>
    </div>
  );
}

function HealthLine({ label, value, ok }: { label: string; value?: string; ok?: boolean }) {
  return (
    <div className="health-line">
      <span>{label}</span>
      <strong className={ok ? "health-ok" : "health-bad"}>{ok ? "OK" : "检查失败"}</strong>
      <small>{value || "待检查"}</small>
    </div>
  );
}
