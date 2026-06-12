import { useEffect, useState } from "react";
import { api, type AISettings, type OllamaModel, type PlatformSettings, type SystemHealth } from "../data/api";
import { Card } from "../components/Card";
import { StatusPill } from "../components/StatusPill";

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
};

const DEFAULT_PLATFORM_SETTINGS: PlatformSettings = {
  runner: {
    browser_mode: "background",
    queue_mode: "serial",
    batch_range: "TC-ICM-001..TC-ICM-012",
    screenshot_policy: "latest_plus_failed_archive",
    headless: true,
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

type SystemSettingsProps = {
  onAISettingsChange?: () => void | Promise<void>;
};

export function SystemSettings({ onAISettingsChange }: SystemSettingsProps) {
  const [aiSettings, setAiSettings] = useState<AISettings | null>(null);
  const [aiForm, setAiForm] = useState(MODEL_PRESETS["minimax-m3"]);
  const [platformSettings, setPlatformSettings] = useState<PlatformSettings>(DEFAULT_PLATFORM_SETTINGS);
  const [accountPasswords, setAccountPasswords] = useState<Record<string, string>>({});
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  const [status, setStatus] = useState("正在读取系统设置...");
  const [busy, setBusy] = useState(false);
  const [testingAIConnection, setTestingAIConnection] = useState(false);

  useEffect(() => {
    void loadSettings();
  }, []);

  async function loadSettings() {
    setBusy(true);
    try {
      const [ai, platform, healthResult] = await Promise.all([api.aiSettings(), api.platformSettings(), api.systemHealth()]);
      setAiSettings(ai);
      setAiForm({
        provider: ai.provider || MODEL_PRESETS["minimax-m3"].provider,
        base_url: ai.base_url || MODEL_PRESETS["minimax-m3"].base_url,
        model: ai.model || MODEL_PRESETS["minimax-m3"].model,
        api_key: "",
      });
      setPlatformSettings({ ...DEFAULT_PLATFORM_SETTINGS, ...platform });
      setAccountPasswords({});
      setHealth(healthResult);
      if (ai.provider === "ollama-local") {
        await loadOllamaModels(ai.base_url, ai.model);
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
    setAiForm(preset);
    if (provider === "ollama-local") {
      void loadOllamaModels(preset.base_url, preset.model);
    }
  }

  async function loadOllamaModels(baseUrl = aiForm.base_url, preferredModel = aiForm.model) {
    try {
      const result = await api.ollamaModels(baseUrl);
      setOllamaModels(result.models);
      const names = result.models.map((item) => item.model || item.name);
      const nextModel = names.includes(preferredModel)
        ? preferredModel
        : names.includes("qwen3.6:35b")
          ? "qwen3.6:35b"
          : names[0] || preferredModel;
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
      setStatus(`AI 设置已保存：${saved.provider} / ${saved.model}`);
      await onAISettingsChange?.();
    } catch (error) {
      setStatus(`AI 设置保存失败：${error instanceof Error ? error.message : "unknown error"}`);
    } finally {
      setBusy(false);
    }
  }

  async function testAIConnection() {
    setTestingAIConnection(true);
    setStatus(`正在测试 AI 连接：${aiForm.provider} / ${aiForm.model}，请稍候...`);
    try {
      const result = await api.testAIConnection();
      setStatus(`AI 连接成功：${result.provider} / ${result.model}`);
      await onAISettingsChange?.();
    } catch (error) {
      setStatus(`AI 连接失败：${error instanceof Error ? error.message : "unknown error"}`);
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
      setPlatformSettings(saved);
      setAccountPasswords({});
      setStatus("平台设置已保存");
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
    setPlatformSettings((current) => ({ ...current, runner: { ...current.runner, ...patch } }));
  }

  function setBrowserMode(browserMode: string) {
    patchRunner({ browser_mode: browserMode, headless: browserMode === "background" });
  }

  function patchAssetPolicy(patch: Partial<PlatformSettings["asset_policy"]>) {
    setPlatformSettings((current) => ({ ...current, asset_policy: { ...current.asset_policy, ...patch } }));
  }

  function patchEnvironment(patch: Partial<PlatformSettings["environment"]>) {
    setPlatformSettings((current) => ({ ...current, environment: { ...current.environment, ...patch } }));
  }

  function patchAccount(key: keyof PlatformSettings["accounts"], username: string) {
    setPlatformSettings((current) => ({
      ...current,
      accounts: { ...current.accounts, [key]: { ...current.accounts[key], username } },
    }));
  }

  return (
    <div className="page settings-page">
      <div className="settings-grid">
        <Card title="AI 模型设置" subtitle={aiSettings?.has_api_key ? `已保存 Key：${aiSettings.api_key_masked}` : "Minimax 需要 Key，Ollama 本地模型通常无需 Key。"}>
          <div className="settings-status">
            <StatusPill tone={aiSettings?.provider === "ollama-local" ? "green" : "blue"}>{aiForm.provider}</StatusPill>
            <StatusPill tone="purple">{aiForm.model}</StatusPill>
          </div>
          <label className="field-label">Provider</label>
          <select className="text-input" value={aiForm.provider} onChange={(event) => applyModelPreset(event.target.value as keyof typeof MODEL_PRESETS)}>
            <option value="minimax-m3">Minimax M3 Token Plan</option>
            <option value="ollama-local">本地 Ollama</option>
          </select>
          <div className="button-row model-presets">
            <button className="btn btn--soft" onClick={() => applyModelPreset("minimax-m3")} type="button">切到 Minimax-M3</button>
            <button className="btn btn--soft" onClick={() => applyModelPreset("ollama-local")} type="button">切到 Ollama</button>
          </div>
          <label className="field-label">Base URL</label>
          <input className="text-input" value={aiForm.base_url} onChange={(event) => setAiForm((current) => ({ ...current, base_url: event.target.value }))} />
          {aiForm.provider === "ollama-local" ? (
            <>
              <div className="button-row">
                <button className="btn btn--outline" disabled={busy} onClick={() => loadOllamaModels()} type="button">刷新 Ollama 模型</button>
                <span className="muted">{ollamaModels.length ? `${ollamaModels.length} 个模型可选` : "尚未读取模型列表"}</span>
              </div>
              <label className="field-label">Ollama 模型</label>
              <select className="text-input" value={aiForm.model} onChange={(event) => setAiForm((current) => ({ ...current, model: event.target.value }))}>
                {ollamaModels.length ? ollamaModels.map((item) => {
                  const modelName = item.model || item.name;
                  return <option key={modelName} value={modelName}>{modelName}</option>;
                }) : <option value={aiForm.model}>{aiForm.model}</option>}
              </select>
            </>
          ) : null}
          <label className="field-label">Model</label>
          <input className="text-input" value={aiForm.model} onChange={(event) => setAiForm((current) => ({ ...current, model: event.target.value }))} />
          <label className="field-label">Subscription Key / API Key</label>
          <input
            className="text-input"
            placeholder={aiForm.provider === "ollama-local" ? "Ollama 通常无需填写" : aiSettings?.has_api_key ? "留空表示继续使用已保存 Key" : "请输入 Token Plan Key"}
            type="password"
            value={aiForm.api_key}
            onChange={(event) => setAiForm((current) => ({ ...current, api_key: event.target.value }))}
          />
          <div className="button-row">
            <button className="btn btn--primary" disabled={busy} onClick={saveAISettings} type="button">保存 AI 设置</button>
            <button className="btn btn--outline" disabled={busy || testingAIConnection} onClick={testAIConnection} type="button">
              {testingAIConnection ? <><span className="inline-spinner" />测试中...</> : "测试连接"}
            </button>
          </div>
          {testingAIConnection ? (
            <div className="settings-note settings-note--progress">正在请求后端并等待模型响应，连接完成后会自动刷新右上角模型名称。</div>
          ) : null}
        </Card>

        <Card title="环境与账号配置" subtitle="URL 和账号保存在本机后端；密码只可更新，不会在前端明文回显。">
          <label className="field-label">ICM base_url</label>
          <input className="text-input" value={platformSettings.environment.icm_base_url} onChange={(event) => patchEnvironment({ icm_base_url: event.target.value })} />
          <label className="field-label">ICM 登录页</label>
          <input className="text-input" value={platformSettings.environment.icm_login_url} onChange={(event) => patchEnvironment({ icm_login_url: event.target.value })} />
          <label className="field-label">dev portal base_url</label>
          <input className="text-input" value={platformSettings.environment.dev_portal_base_url} onChange={(event) => patchEnvironment({ dev_portal_base_url: event.target.value })} />
          <label className="field-label">dev portal 登录页</label>
          <input className="text-input" value={platformSettings.environment.dev_login_url} onChange={(event) => patchEnvironment({ dev_login_url: event.target.value })} />
          <label className="field-label">远程协助信息页</label>
          <input className="text-input" value={platformSettings.environment.remote_help_url} onChange={(event) => patchEnvironment({ remote_help_url: event.target.value })} />
          <div className="account-grid">
            {Object.entries(platformSettings.accounts).map(([key, account]) => (
              <div className="account-row" key={key}>
                <div>
                  <strong>{ACCOUNT_LABELS[key as keyof PlatformSettings["accounts"]]}</strong>
                  <span>{account.has_password ? `已保存 ${account.password_masked}` : "未保存密码"}</span>
                </div>
                <input className="text-input" value={account.username} onChange={(event) => patchAccount(key as keyof PlatformSettings["accounts"], event.target.value)} />
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
          <button className="btn btn--green" disabled={busy} onClick={() => savePlatformSettings()} type="button">保存环境与账号</button>
        </Card>

        <Card title="Runner 执行设置" subtitle="控制后台 runner 的运行方式；执行中心发起任务时会读取这些设置。">
          <label className="field-label">浏览器模式</label>
          <select className="text-input" value={platformSettings.runner.browser_mode} onChange={(event) => setBrowserMode(event.target.value)}>
            <option value="background">后台独立浏览器</option>
            <option value="visible">可视化浏览器</option>
          </select>
          <div className="settings-note">
            {platformSettings.runner.browser_mode === "background"
              ? "后台独立浏览器会自动使用 headless=true，不打扰前台操作。"
              : "可视化浏览器会自动使用 headless=false，方便观察调试过程。"}
          </div>
          <label className="field-label">队列模式</label>
          <select className="text-input" value={platformSettings.runner.queue_mode} onChange={(event) => patchRunner({ queue_mode: event.target.value })}>
            <option value="serial">串行执行</option>
            <option value="limited_parallel">小并发预留</option>
          </select>
          <label className="field-label">默认 Batch 范围</label>
          <input className="text-input" value={platformSettings.runner.batch_range} onChange={(event) => patchRunner({ batch_range: event.target.value })} />
          <label className="field-label">截图策略</label>
          <select className="text-input" value={platformSettings.runner.screenshot_policy} onChange={(event) => patchRunner({ screenshot_policy: event.target.value })}>
            <option value="latest_plus_failed_archive">latest 覆盖 + 失败归档</option>
            <option value="always_archive">每次都归档</option>
          </select>
          <button className="btn btn--green" disabled={busy} onClick={() => savePlatformSettings()} type="button">保存 Runner 设置</button>
        </Card>

        <Card title="资产沉淀策略" subtitle="控制 observed asset 生成、合并和 verified 门禁。">
          <label className="settings-check">
            <input type="checkbox" checked={platformSettings.asset_policy.observed_asset_enabled} onChange={(event) => patchAssetPolicy({ observed_asset_enabled: event.target.checked })} />
            <span>后台运行时生成 observed asset</span>
          </label>
          <label className="settings-check">
            <input type="checkbox" checked={platformSettings.asset_policy.allow_passed_run_merge} onChange={(event) => patchAssetPolicy({ allow_passed_run_merge: event.target.checked })} />
            <span>允许 passed run 合并为 verified automation_asset</span>
          </label>
          <label className="settings-check">
            <input type="checkbox" checked={platformSettings.asset_policy.require_verified_before_regression} onChange={(event) => patchAssetPolicy({ require_verified_before_regression: event.target.checked })} />
            <span>日常回归前要求 automation_asset verified</span>
          </label>
          <label className="field-label">合并策略</label>
          <select className="text-input" value={platformSettings.asset_policy.merge_strategy} onChange={(event) => patchAssetPolicy({ merge_strategy: event.target.value })}>
            <option value="conservative">保守合并：不覆盖已有人工资产</option>
            <option value="observed_fill_missing">仅用 observed asset 补缺失字段</option>
          </select>
          <div className="settings-note">当前后端仍保留硬门禁：只有 passed 的单 case run 可以合并，失败运行不会污染正式 YAML。</div>
          <button className="btn btn--green" disabled={busy} onClick={() => savePlatformSettings()} type="button">保存资产策略</button>
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
            <HealthLine label="SQLite" value={health ? `${health.sqlite.path} · ${health.sqlite.updated_at || "未更新"}` : ""} ok={health?.sqlite.exists} />
            {health ? Object.entries(health.paths).map(([key, item]) => (
              <HealthLine key={key} label={key} value={`${item.path} · ${item.updated_at || "未更新"}`} ok={item.exists && item.is_dir} />
            )) : null}
          </div>
          <p className="analysis-copy">设置更新时间：{platformSettings.updated_at || "尚未保存"}</p>
          <div className="button-row">
            <button className="btn btn--outline" disabled={busy} onClick={loadSettings} type="button">重新读取设置</button>
            <button className="btn btn--soft" disabled={busy} onClick={refreshHealth} type="button">刷新健康检查</button>
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
      <strong className={ok ? "health-ok" : "health-bad"}>{ok ? "OK" : "检查"}</strong>
      <small>{value || "待检查"}</small>
    </div>
  );
}
