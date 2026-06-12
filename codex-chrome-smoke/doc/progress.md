# Progress

## 2026-06-12 草稿直接 AI 真实执行
- 已启动“草稿直接跑”能力补齐。
- 目标：用例管理行级 AI 按钮在草稿未转正式时也可执行，后端创建临时 YAML 运行资产，worker 调用 runner 执行，不污染正式 `test-cases/icm/*.yaml`。
- 当前设计：正式 case 继续走 `run-case`；草稿 case 走 `run-draft`，由平台生成临时 `reports/draft-runs/<run_id>/*.yaml`。
- 已完成 runner `run-draft` 命令、worker `run-draft` 入队、前端草稿行级 AI 执行入口。
- 已完成验证：`python -m compileall runner icm_platform` 通过，后端 10 个单元测试通过，前端 `npm run build` 通过。
- 已真实跑通：`python -m runner.main run-draft test-cases\icm\TC-ICM-001-login-success.yaml draft-smoke-001`，报告状态 passed，证据链和 trace 已生成。

## 2026-06-07 环境账号配置与系统健康检查
- 已启动环境与账号配置、系统健康检查。
- 目标：系统设置页可安全管理 ICM/dev portal URL 与 labo/jesse/Tester 账号，健康检查展示 API、Runner、Playwright/Chrome、目录和 SQLite 状态。

## 2026-06-07 Runner 设置接入执行链路
- 已启动 Runner 执行设置接入 worker/runner。
- 目标：让 headless、截图策略、batch 范围从系统设置读取并在后台执行时生效，同时保留本地命令兼容。
- 已完成 runner CLI 参数、worker 设置读取与参数传递、截图归档策略和 batch 范围解析。
- 已完成验证：后端 28 个单元测试通过，`python -m compileall icm_platform runner` 通过，前端 `npm run build` 通过。
- 已完成 browser_mode 语义化：后台独立浏览器自动 headless=true，可视化浏览器自动 headless=false。
- 已完成验证：后端 29 个单元测试通过，`python -m compileall icm_platform runner` 通过，前端 `npm run build` 通过。

## 2026-06-07 系统设置真实化
- 已启动系统设置真实化第一版。
- 范围：AI 模型设置、Runner 执行设置、资产沉淀策略。
- 已完成后端平台设置存储与 API、系统设置页面、导航接入和样式。
- 已完成验证：后端 26 个单元测试通过，`python -m compileall icm_platform runner` 通过，前端 `npm run build` 通过。

## 2026-06-07 报告详情页接入 observed asset
- 已完成报告详情页 observed asset 查看与合并入口。
- 已接入 `GET /api/runs/{run_id}/observed-asset` 和 `POST /api/runs/{run_id}/merge-observed-asset`。
- 已完成验证：前端 `npm run build` 通过，后端 25 个单元测试通过，`python -m compileall icm_platform runner` 通过。

## 2026-06-07 后台真实执行自动沉淀资产
- 已启动后台真实执行自动沉淀 `automation_asset` v1。
- 目标：runner 后台真实跑通时生成 `observed_asset`，passed run 才允许由平台接口合并回正式 YAML。
- 已完成 runner 观测器、报告 observed asset 路径、平台读取与合并接口。
- 已完成验证：后端 25 个单元测试通过，`python -m compileall runner icm_platform` 通过，前端 `npm run build` 通过。

## 2026-06-06
- 已明确目标：执行“用例生成链路增强”。
- 已确认当前项目没有 `doc/` 过程目录，本次按约定补齐。
- 下一步：实现后端 draft API 与前端草稿管理。
- 已扩展 `case_drafts` 表字段，增加模板、来源测试点、转正式 case 追踪字段。
- 已扩展后端 API：草稿列表、详情、编辑、转正式 case。
- 已把测试点页生成 YAML 改为支持草稿标题、模板、规则/AI 生成方式。
- 已把用例工具箱改为读取真实草稿库，并支持保存草稿与转正式 case。
- 已补充后端单测覆盖草稿字段、生成、编辑、转正式 case。
- 已完成验证：后端 18 条单测通过，后端编译通过，前端生产构建通过。

## 2026-06-06 Dashboard 首页真实化
- 已启动 Dashboard 首页真实化。
- 目标：移除首页 mock 统计，接入 health、AI 设置、需求、测试点、草稿、正式 case、执行任务和报告真实数据。
- 下一步：重写 Dashboard 数据加载与真实空状态。
- 已完成 Dashboard 首页真实化：需求、测试点、草稿、正式 case、执行任务、报告、Runner 和 AI 设置均读取真实 API。
- 已完成验证：前端生产构建通过，后端 18 条单测通过。

## 2026-06-06 导航类型迁出 mock
- 已启动导航类型迁出：目标是让核心页面不再依赖 `data/mock.ts`。
- 当前待迁移引用：`PageId`、`navItems`、`flowSteps`、用例工具箱 fallback case、执行中心 fallback console。
- 已完成迁移：`PageId` 进入 `web-ui/src/types.ts`，`navItems/flowSteps` 进入 `web-ui/src/data/navigation.ts`。
- 已清理核心页面 mock 依赖：用例工具箱不再使用 fallback case，执行中心不再使用 fallback console。
- 已完成验证：核心代码搜索无 `data/mock` 引用，前端生产构建通过。

## 2026-06-06 删除 mock.ts
- 已确认 `web-ui/src` 下无任何 `data/mock` 引用。
- 已删除 `web-ui/src/data/mock.ts`，让 mock 文件彻底退出核心页面和源码入口。

## 2026-06-06 AI 报告分析真实化
- 已启动 AI 报告分析真实化。
- 目标：报告详情默认保留快速本地分析，新增手动触发真实模型分析，使用当前 Minimax/Ollama 设置。
- 已新增 `POST /api/reports/{run_id}/analyze`，显式调用当前配置的大模型分析报告。
- 已在报告详情页新增“调用 AI 分析”按钮、分析中状态和失败提示。
- 已完成验证：后端 19 条单测通过，后端编译通过，前端生产构建通过。

## 2026-06-06 AI 分析结果缓存入库
- 已启动 AI 报告分析缓存。
- 目标：同一 run、同一报告内容、同一 provider/model 再次分析时直接返回 SQLite 缓存。
- 已新增 `report_analyses` SQLite 表。
- 已实现按 `run_id + report_hash + provider + model` 命中缓存。
- 已在报告详情页展示“已缓存 / 新分析”状态。
- 已完成验证：后端 20 条单测通过，后端编译通过，前端生产构建通过。

## 2026-06-06 报告分析历史版本与强制重分析
- 已启动报告分析历史版本查看和强制重新分析。
- 目标：保留最新缓存，同时记录每次真实 AI 分析版本，前端可查看历史并手动强制刷新。
- 已新增 `report_analysis_versions` 历史表。
- 已扩展 `POST /api/reports/{run_id}/analyze` 支持 `force` 强制重分析。
- 已新增 `GET /api/reports/{run_id}/analyses` 查看历史版本。
- 已在报告详情页新增“强制重新分析”按钮和历史版本列表。
- 已完成验证：后端 21 条单测通过，后端编译通过，前端生产构建通过。

## 2026-06-06 YAML 草稿格式校验
- 已启动 YAML 草稿格式校验。
- 目标：正式落盘前校验 YAML 结构和 automation_asset 完整性，失败则阻止转正式 case。
- 已完成后端校验接口、转正式硬拦截、前端手动校验入口和校验结果展示。
- 已通过后端 23 个单元测试、`python -m compileall icm_platform`、前端 `npm run build`。
