# Findings

## 2026-06-07 Runner 设置接入执行链路
- 原 runner CLI 没有可选参数，worker 也未读取平台设置；现在通过兼容参数方式接入，不影响原 VS Code 命令。
- `browser_mode` 仍作为页面策略说明保留，实际控制浏览器是否无界面运行的是 `headless`。
- `browser_mode` 已升级为 headless 的单一语义来源，避免页面上出现互相矛盾的浏览器模式与 headless 勾选。

## 2026-06-07 系统设置真实化
- 当前 `settings` 菜单存在但不可跳转，App 也没有设置页。
- AI 设置已在需求工作台内真实可用，适合在系统设置中复用同一套接口。
- Runner 与资产策略采用 SQLite 持久化，首版先作为平台配置中心保存策略；执行链路后续可逐步读取这些配置生效。

## 2026-06-07 报告详情页接入 observed asset
- observed asset 属于运行证据，放在报告详情页比放在执行中心或用例工具箱更符合“先审查证据，再确认合并”的流程。
- 当前前端合并按钮按报告状态控制，后端仍保留 passed run 硬校验，避免前端绕过导致资产污染。

## 2026-06-07 后台真实执行自动沉淀资产
- 现有执行中心已是后台 worker 调用 Playwright runner，具备不影响用户前台 Chrome 的基础。
- 风险点在于不能让 AI 或失败运行直接污染正式 `automation_asset`，因此应先保存 `observed_asset`，再由 passed run 合并。
- 合并策略采用保守模式：已有语义化资产不被观测器的通用 selector 覆盖，只补充 `status/source/observed_at/evidence`；缺失字段才用 observed asset 填充。

## 2026-06-06
- 当前后端已有 `case_drafts` 表，但缺少草稿列表、详情、编辑、转正式用例接口。
- 当前 `POST /api/test-points/generate-cases` 只接收 `test_point_ids`，不支持模板和标题。
- 当前 `AIService.generate_cases` 是本地规则拼接，未接入已配置的大模型。
- 当前用例工具箱仍以静态/半静态展示为主，没有读取 `case_drafts`。
- 本次保留“规则生成”作为本地稳定入口，同时新增“AI 生成”使用当前模型配置。
- 转正式 case 采用显式动作，且目标 YAML 文件存在时拒绝覆盖。
- `codex-chrome-smoke` 当前不是 Git 仓库目录，`git status` 无法用于变更检查。

## 2026-06-06 Dashboard 首页真实化
- 当前 Dashboard 仍引用 `dashboardConsoleLines` 和 `testPoints` mock 数据。
- 现有前端 API 已覆盖首页所需的大部分数据，可优先在前端聚合，不必新增后端接口。
- Dashboard 真实化无需新增后端接口，使用现有 API 聚合即可满足首版总控台需求。
- Dashboard 仍保留 `PageId` 类型从 mock 模块导入；这不是展示 mock 数据，后续可单独把导航类型迁出 mock 文件。

## 2026-06-06 导航类型迁出 mock
- `mock.ts` 目前混合了承载产品导航常量和原型假数据，导致核心页面仍与 mock 文件耦合。
- `PageId`、`navItems`、`flowSteps` 属于真实产品结构，应迁出到独立类型和导航常量文件。
- 迁移后 `mock.ts` 只保留 legacy demo data，核心页面、组件和 API 类型均不再引用它。

## 2026-06-06 删除 mock.ts
- `mock.ts` 删除前已确认零引用。
- 当前真实导航常量位于 `web-ui/src/data/navigation.ts`，页面类型位于 `web-ui/src/types.ts`。

## 2026-06-06 AI 报告分析真实化
- 当前报告详情的 `analysis` 来自本地规则函数，不会调用已配置的大模型。
- 为避免打开报告时被模型延迟阻塞，真实 AI 分析适合做成显式按钮触发。
- GET 报告详情继续返回本地快速分析，POST 分析接口负责真实 AI 调用，避免页面首屏被模型耗时阻塞。

## 2026-06-06 AI 分析结果缓存入库
- 当前 `POST /api/reports/{run_id}/analyze` 每次都会调用模型，可能重复消耗本地/远程模型资源。
- 缓存需要绑定 report hash 和 provider/model，避免报告变化或模型切换后复用旧结论。
- GET 报告详情现在可读取已有 AI 缓存；没有缓存时仍返回本地规则分析，保证首屏稳定。

## 2026-06-06 报告分析历史版本与强制重分析
- 现有 `report_analyses` 适合作为最新缓存，但 `unique(run_id, report_hash, provider, model)` 不适合保存多次历史版本。
- 应新增独立历史表，保留最新缓存的快速读取能力。
- 强制重新分析会跳过最新缓存，调用模型后同时更新最新缓存并追加历史版本。

## 2026-06-06 YAML 草稿格式校验
- 当前转正式 case 只替换 id 并写文件，缺少 YAML 语法和关键字段门禁。
- 草稿生成链路可能产生空 `automation_asset`，转正式前应显式拦截并提示补齐。
- 规则生成的 YAML 草稿默认 `automation_asset.operation_steps/selectors/assertions` 为空，因此现在会被门禁拦截，符合“先人工补齐沉淀资产，再转正式”的目标。
