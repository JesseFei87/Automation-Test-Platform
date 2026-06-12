# ICM 自动化测试管理平台 · 增量 PRD

> 适用范围：`codex-chrome-smoke` 项目根目录
> 文档版本：v0.1（增量，不重写基线 PRD）
> 关联模块：`icm_platform/`、`runner/`、`web-ui/`
> 路线编号：A 资产采纳 · B 登录复用 + 重试 + 稳定性 · C YAML → Python 模板化

---

## 1. 背景与现状

经过项目调研，确认以下事实基线（不再重复 PRD 原文）：

| 能力 | 状态 | 关键证据 |
|---|---|---|
| LLM 用例生成 | 已上线 | `icm_platform/ai_service.py` 4 类 prompt 已接 `minimax-m3` + `ollama-local` |
| Playwright 执行 | 已跑通 12 条 | `runner/main.py`、`runner/cases.py`、`runner/flows/icm_case_001..012.py`、`runner/browser.py` |
| 报告 LLM 分析 | 已上线 | `api.analyze_run_report_with_ai` + `report_analyses` 缓存表 |
| observed asset 落盘 | 已实现 | `runner/asset_recorder.py` 写 `reports/observed-assets/{run_id}.json` |
| conservative 合并策略 | **后端已实现 / 端到端入口仅报告详情页** | `api.merge_automation_asset()`、`api.merge_run_observed_asset()`（仅 `POST /api/runs/{run_id}/merge-observed-asset`），前端按钮在 `ReportDetail.tsx:301` |
| retry / stability / flaky | **未实现** | 代码库零命中 |
| storageState 跨用例复用 | **未实现** | 每次 `run_case` 走 `open_login_page` + `perform_login` 重新登录 |
| YAML → Python 模板化（codegen） | **未实现** | 代码库零命中，无 Jinja2 依赖 |

**关键洞察**：
- 路线 A 不是从零搭，而是把已沉淀的"报告详情页合并按钮"按用户故事搬到 **CaseToolbox 主流程**，让"跑用例 → 采纳观察值 → 回写 YAML"形成闭环，不再要求测试工程师先打开报告详情页。
- 路线 B、C 是真正的 0→1 工作。

---

## 2. 产品目标

| 路线 | 一句话目标 | 业务指标 |
|---|---|---|
| A 资产采纳 | 让"采纳观察值"在 CaseToolbox 一站式完成，无需跳转报告页 | CaseToolbox 内采纳成功率 ≥ 90%；误覆盖人工字段事件 0 起 |
| B 复用 + 重试 + 稳定性 | 把单条用例端到端时长从 ~25s 降到 ~8s，并给回归集一份"信任名单" | batch 回归时长 -50%；flaky 用例漏检 0 起；误把 flaky 用例加入回归集 0 起 |
| C YAML → Python | 13/14/15 号用例不再手写 flow，由 YAML 一键生成 | 新增 1 条用例的 flow 编写时间从 ~2h 降到 ~5min；生成后无需再改 |

---

## 3. 用户故事池

### 路线 A · 资产采纳主流程化

- **US-A1** 作为测试工程师，我希望在 CaseToolbox 选中一条用例时直接看到"采纳最近一次 passed run 的观察值"按钮，**以便**不离开主流程就能完成资产沉淀。
- **US-A2** 作为测试工程师，我希望回写采用 conservative 合并（已有 `operation_steps`/`selectors`/`input_values`/`assertions` 不被覆盖），**以便**手工精修过的字段不会被一次跑通覆盖。
- **US-A3** 作为测试工程师，我希望采纳前能预览"本次新增 / 保留 / 缺失"三段 diff，**以便**我在点击前确认是否会破坏我之前手工维护的字段。
- **US-A4** 作为测试工程师，我希望采纳完成后能立即看到 YAML 内 `automation_asset` 块的最新结果和"上次采纳时间 / 上次采纳的 run_id"，**以便**追溯来源。
- **US-A5** 作为测试工程师，我希望可以"拒绝"本次观察值（仅记录到 `observed_assets` 但不入 YAML），**以便**用例在 CI 跑通但我不信任时留下证据。

### 路线 B · 登录复用 + 重试 + 稳定性

- **US-B1** 作为测试工程师，我希望 batch 跑第一条用例时登录一次，后续用例直接复用 storageState，**以便**总时长降到原来的 ~30%。
- **US-B2** 作为测试工程师，我希望 runner 支持 `--retry N` 参数，**以便**偶发性失败自动重试 N 次再判失败。
- **US-B3** 作为测试工程师，我希望每条用例都有一个稳定分（pass_rate = passed / total），< 95% 时打 `flaky` 标，**以便**回归集只放真正稳定的用例。
- **US-B4** 作为测试工程师，我希望在 CaseToolbox 用例列表直接看到稳定分和最后稳定运行时间，**以便**快速识别哪些用例不能进回归集。
- **US-B5** 作为测试工程师，我希望发起"稳定性扫描"（自动连跑 N 次）后能拿到一张表，**以便**批量判定用例是否稳定。

### 路线 C · YAML → Python 模板化

- **US-C1** 作为测试工程师，我希望选中一条正式 case 后点"生成 Python 脚本"，**以便**得到 `runner/flows/icm_case_XXX.py` 草稿文件。
- **US-C2** 作为测试工程师，我希望生成的脚本遵循 `icm_common.py` 已有的工具函数（`prepare_session`、`search_by_keyword` 等），**以便**与现有 12 条用例风格一致。
- **US-C3** 作为测试工程师，我希望生成前看到"无法生成"的明确原因（如缺 `operation_steps` / 缺 selector），**以便**知道先补哪些字段。
- **US-C4** 作为测试工程师，我希望生成后能在 `cases.py` 注册并跑通该用例，**以便**一次完成接入。

---

## 4. 需求池（按优先级）

### P0 · 必须做（不阻塞上线）

| ID | 路线 | 需求 | 备注 |
|---|---|---|---|
| REQ-A-01 | A | CaseToolbox 正式 case 行内加"采纳观察值"按钮，按钮 enabled 当且仅当该 case 存在 passed run 且有 observed asset | 复用 `run_observed_asset` + `merge_run_observed_asset` |
| REQ-A-02 | A | 采纳前调 `GET /api/cases/{id}/observed-asset-diff` 返回 `{kept: [...], added: [...], missing: [...]}` | 纯函数派生，不写库 |
| REQ-A-03 | A | 采纳动作成功后，case YAML 内的 `automation_asset.source`/`observed_at`/`evidence` 更新；保留已有 `operation_steps`/`selectors`/`input_values`/`assertions` | 沿用 `merge_automation_asset()` conservative 语义 |
| REQ-A-04 | A | 失败/未 passed 的 run 在 CaseToolbox 显示为"待采纳 - 需先跑通"灰色按钮 | 复用报告状态 |
| REQ-B-01 | B | runner 支持 `--retry N`（默认 0），单 case 失败时同一 page 重试 N 次，全部失败才标 failed | 复用 `run_case()` |
| REQ-B-02 | B | batch 跑第一条用例前登录并保存 `storage_state.json` 到 `.codex-tmp/storage-state/{system}.json`，后续 case 通过 `context.add_init_script` / `context = browser.new_context(storage_state=...)` 复用 | 失败时回退到逐条登录 |
| REQ-B-03 | B | 新增 SQLite 表 `case_runs(case_id, run_id, passed, started_at, finished_at)` | 每次 run 落库 |
| REQ-B-04 | B | 新增 `GET /api/cases/{id}/stability` → `{case_id, total, passed, pass_rate, status: 'stable'\|'flaky'\|'insufficient', last_stable_at}` | 阈值 pass_rate ≥ 0.95 |
| REQ-B-05 | B | 新增 `POST /api/cases/{id}/stability-scan` 触发连跑 N 次（默认 10），扫描期间返回扫描任务 id | 用现有 worker 队列 |
| REQ-C-01 | C | 新增 `POST /api/cases/{id}/codegen` 返回 `{code, target_path, ok, errors[]}`，不直接写盘（先 dry-run） | 不污染 runner/ |
| REQ-C-02 | C | Jinja2 模板放在 `runner/flows/templates/icm_case.py.j2`，遵循现有 12 条用例风格（`prepare_session` + `browser` 工具函数） | 用例级 |
| REQ-C-03 | C | 前端 CaseToolbox"生成 Python 脚本"按钮，dry-run 成功后二次确认落盘 | 防误生成 |

### P1 · 强烈建议

| ID | 路线 | 需求 |
|---|---|---|
| REQ-A-05 | A | 采纳历史表 `asset_adoptions(case_id, run_id, mode: 'accept'\|'reject', adopted_by, adopted_at, diff_summary)` |
| REQ-A-06 | A | CaseToolbox 显示该 case 最近 3 次采纳时间和采纳人 |
| REQ-B-06 | B | CaseToolbox 用例列表新增"稳定分"列（0%~100% + 颜色徽标） |
| REQ-B-07 | B | batch 执行时若某用例 storageState 复用失败，自动 fallback 重新登录并打 log |
| REQ-C-04 | C | 生成的 Python 脚本自动注册到 `runner/cases.py` 的 `CASE_RUNNERS`，并在 README 中追加说明 |
| REQ-C-05 | C | codegen 失败原因细分：`missing operation_steps` / `missing selectors` / `unsupported step kind` / `success` |

### P2 · 锦上添花

| ID | 路线 | 需求 |
|---|---|---|
| REQ-A-07 | A | "批量采纳"：勾选多条 case 一次性采纳最近 passed run |
| REQ-B-08 | B | stability 阈值可在系统设置里改（默认 0.95） |
| REQ-B-09 | B | flaky 用例自动隔离到 `tests_flaky/`，不进 `tests/` 回归集 |
| REQ-C-06 | C | codegen 模板可按 `template: functional\|negative\|regression` 切换生成风格 |

---

## 5. UI 改动清单（前端 CaseToolbox）

> 主战场：`web-ui/src/pages/CaseToolbox.tsx`，辅助：`pages/ReportDetail.tsx`、`pages/ExecutionCenter.tsx`、`pages/SystemSettings.tsx`。

| 区域 | 改动 | 关联需求 |
|---|---|---|
| 正式用例列表（侧边栏） | "脚本"列前新增"稳定分"列（百分比 + 颜色 pill：绿 ≥95% / 黄 80–95% / 红 <80% / 灰 insufficient） | REQ-B-06 |
| 正式用例列表 | 每行末尾新增"采纳观察值"按钮：passed run → 主色；无 passed → 灰；正在合并 → 加载 | REQ-A-01 |
| 正式用例列表 | 鼠标悬停稳定分显示"passed/total · last_stable_at" tooltip | REQ-B-04 |
| 右侧主区 | 在"YAML 草稿编辑"卡片上方新增"采纳预览"卡片（展开后显示 kept/added/missing 三段 diff） | REQ-A-02 / US-A-3 |
| 右侧主区 | 在"转正式 case"卡片下方新增"生成 Python 脚本"卡片，按钮触发现有 case codegen dry-run | REQ-C-01 / US-C-1 |
| 右侧主区 | codegen 结果区显示代码预览 + 落盘按钮（二次确认）+ 失败原因列表 | REQ-C-03 / REQ-C-05 |
| 顶栏 | 切换 case 时自动加载该 case 的 stability 数据 + 最近一次 observed asset 元数据 | REQ-B-04 |
| 执行中心 | batch 跑完后增加"采纳全部"按钮（仅列出 passed run） | REQ-A-07 |
| 系统设置 | 增加"稳定性阈值"输入框（默认 0.95） | REQ-B-08 |
| 系统设置 | 增加"启用 storageState 复用"开关（默认开） | REQ-B-02 |

---

## 6. API 改动清单

| Method | Path | 用途 | 路线 | 备注 |
|---|---|---|---|---|
| GET | `/api/cases/{case_id}/observed-asset-diff` | 拉最近 passed run 的 observed asset 与当前 YAML 的 diff（kept/added/missing） | A | 仅派生，不写库 |
| POST | `/api/cases/{case_id}/adoptions` | 采纳最近 passed run 的 observed asset 入 YAML，body: `{run_id, mode: "accept"\|"reject"}` | A | 复用 `merge_automation_asset` + 写 `asset_adoptions` |
| GET | `/api/cases/{case_id}/adoptions?limit=10` | 拉该 case 的采纳历史 | A | |
| GET | `/api/cases/{case_id}/stability` | 拉稳定分 + 状态 + 最近稳定时间 | B | 派生自 `case_runs` |
| POST | `/api/cases/{case_id}/stability-scan` | 触发稳定性扫描，body: `{times: 10}` | B | 入队 worker |
| GET | `/api/stability-scans/{scan_id}` | 查扫描进度 | B | |
| GET | `/api/cases?include_stability=true` | CaseToolbox 列表一次性拿稳定分 | B | 现有 `GET /api/cases` 扩展 query |
| POST | `/api/cases/{case_id}/codegen` | dry-run 生成 `icm_case_XXX.py`，body: `{write: false}` | C | 返回 code + target_path |
| POST | `/api/cases/{case_id}/codegen` | write=true 时落盘 `runner/flows/icm_case_XXX.py` | C | 二次确认 |

CLI 变更（runner）：
- `python -m runner.main run-batch ... --retry N --storage-state path.json --no-storage-state`

---

## 7. 数据模型变更

```sql
-- 路线 B：每次执行落库
create table if not exists case_runs (
  id integer primary key autoincrement,
  case_id text not null,
  run_id text not null,
  passed integer not null,           -- 0/1
  started_at text not null,
  finished_at text not null,
  attempt integer default 1,          -- retry 第几次
  foreign key(run_id) references run_tasks(id)
);
create index if not exists idx_case_runs_case_id on case_runs(case_id);
create index if not exists idx_case_runs_passed on case_runs(case_id, passed);

-- 路线 A：采纳历史
create table if not exists asset_adoptions (
  id integer primary key autoincrement,
  case_id text not null,
  run_id text not null,
  mode text not null,                 -- 'accept' | 'reject'
  diff_summary_json text,             -- {kept, added, missing}
  adopted_at text not null
);
create index if not exists idx_asset_adoptions_case on asset_adoptions(case_id, adopted_at desc);

-- 路线 B：稳定性扫描任务
create table if not exists stability_scans (
  id text primary key,
  case_id text not null,
  total integer not null,
  completed integer default 0,
  passed integer default 0,
  status text not null,               -- 'queued'|'running'|'done'|'failed'
  started_at text not null,
  finished_at text
);
```

无破坏性变更：全部新表，旧数据保留。

---

## 8. 非功能需求

| 维度 | 要求 |
|---|---|
| 性能 | CaseToolbox 列表加载（含 stability）< 800ms（P50）；stability 扫描连跑 10 次 ≤ 5min |
| 可观测性 | 采纳动作、retry 次数、storageState 命中/回退、codegen dry-run 结果都进 `run_logs` |
| 可回滚 | 采纳 / codegen 落盘动作保留备份：采纳前把旧 YAML 复制到 `.codex-tmp/yaml-backup/{case_id}-{ts}.yaml`；codegen 落盘前把旧 py 复制到 `.codex-tmp/flow-backup/` |
| 安全沙箱 | codegen dry-run 与落盘均在前端二次确认；落盘后立刻 `python -m py_compile runner/flows/icm_case_XXX.py` 自检语法 |
| 安全 | storageState 文件不进 git（`.gitignore` 已含 `.codex-tmp/`）；密码不进日志 |
| 兼容性 | 现有 12 条用例无回归；旧 `report_analyses` / `report_analysis_versions` 表不动 |
| 失败安全 | retry 失败 N 次后写入 run_logs `retry exhausted`；storageState 复用失败时回退登录并继续 |

---

## 9. 风险与待确认问题

1. **保守合并的"空白是否覆盖"语义**：`merge_automation_asset` 当前是"已有非空才保留"，但 YAML 草稿阶段 `operation_steps` 为空时会被 observed 直接填充；这与"先沉淀资产再转正式"的流程是否冲突？需要确认草稿阶段的合并是否走严格模式。
2. **storageState 失效窗口**：token 过期（默认 30 分钟）期间复用的用例可能 401；是否需要在 storageState 失效时整 batch 自动重新登录？
3. **retry 语义边界**：`--retry N` 是按 case 重试还是按 step 重试？网络超时与断言失败的 retry 策略是否一致？
4. **stability 阈值默认 0.95** 是否过严？现有 12 条用例有多少会立即被标 flaky？需要先跑一轮 baseline。
5. **codegen 模板覆盖度**：现有 YAML 草稿的 `operation_steps` 描述风格可能不统一（"打开设备列表" / "在设备列表页搜索 AU5800" / "点击搜索按钮"），模板能否识别并正确映射？需要枚举实际样本。
6. **采纳粒度**：当前按 case 整体采纳。如果一次跑通有 5 个新增字段但 1 个已有字段被改坏，是否需要支持"字段级采纳"？
7. **采纳审计**：当前 `asset_adoptions` 没有 `adopted_by` 字段；多人共用平台时是否要区分操作人？

---

## 10. 验收标准（Given-When-Then）

### 路线 A

1. **Given** 一条正式 case `TC-ICM-013` 已跑通产生 observed asset，
   **When** 测试工程师在 CaseToolbox 点击"采纳观察值"，
   **Then** YAML 的 `automation_asset.source` 变为 `playwright_observed`，`observed_at` 更新，且已有 `selectors`/`input_values` 不变。

2. **Given** 一条正式 case `TC-ICM-013` 同时有"手工精修的 selectors"和"刚跑通的 observed"，
   **When** 工程师点击"采纳观察值"，
   **Then** 预览 diff 显示"selectors：保留手工值；operation_steps：新增 N 条；assertions：缺失 M 条"，点击确认后才落盘。

3. **Given** 一条用例最新 run 是 failed，
   **When** 工程师进入 CaseToolbox，
   **Then** "采纳观察值"按钮置灰且 tooltip 提示"需先跑通"。

4. **Given** 工程师对某 case 采纳失败，
   **When** 进入 CaseToolbox 再次打开该 case，
   **Then** 列表显示最近 3 次采纳时间和模式（accept/reject）。

### 路线 B

5. **Given** batch `TC-ICM-001..TC-ICM-012` 发起，
   **When** 第一个用例跑通后，
   **Then** storageState 已落盘 `.codex-tmp/storage-state/icm-internal.json`；后续 11 条用例 `prepare_session` 平均耗时 < 1s。

6. **Given** 一条用例 `--retry 2`，
   **When** 首次执行因网络超时失败，
   **Then** 自动重试 2 次；任一次成功则该 case 记 passed；全部失败才记 failed，并在 `run_logs` 出现 `retry exhausted`。

7. **Given** 一条用例 `case_runs` 历史 passed=8, total=10，
   **When** 调用 `GET /api/cases/TC-ICM-003/stability`，
   **Then** 返回 `{pass_rate: 0.8, status: "flaky"}`，CaseToolbox 该用例稳定分显示 80% 黄色徽标。

8. **Given** 工程师对一条新 case 发起 stability-scan times=10，
   **When** 扫描完成，
   **Then** `case_runs` 新增 10 行，`/api/cases/{id}/stability` 返回新值。

### 路线 C

9. **Given** 一条正式 case YAML 包含 `operation_steps: [打开设备列表, 在搜索框输入 AU5800, 点击搜索]`、`selectors: {...}`、`input_values: {device_keyword: AU5800}`，
   **When** 工程师点击"生成 Python 脚本"dry-run，
   **Then** 返回的 `code` 含 `prepare_session`、`open_device_list`、`fill_first`、`click_search_button` 调用，与 `icm_case_003.py` 风格一致。

10. **Given** dry-run 返回 `ok: true` 且工程师二次确认落盘，
    **When** 落盘完成，
    **Then** `runner/flows/icm_case_xxx.py` 写入、`python -m py_compile` 通过、`runner/cases.py` 自动注册到 `CASE_RUNNERS`（人工最终检查），`python -m runner.main run-case TC-ICM-XXX` 跑通。

11. **Given** 一条 case YAML `operation_steps` 为空，
    **When** 工程师点击"生成 Python 脚本"，
    **Then** 返回 `ok: false, errors: ["missing operation_steps"]`，前端禁用落盘按钮。

---

> 本 PRD 是增量文档，不重写基线 PRD。任何与基线冲突之处，以本 PRD 增量路线 A/B/C 为准。