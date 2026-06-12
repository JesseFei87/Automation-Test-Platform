# ICM 需求工作台 · 增量需求 · 输入卡片改造

> 存证日期：2026-06-10 15:54
> 项目：ICM 自动化测试管理平台（`codex-chrome-smoke/`）
> 增量目标文件：`web-ui/src/pages/CaseToolbox.tsx`（输入信息卡片）
> 工作流：待启动标准 SOP（团队 `software-icm-platform-d59e` 已解散，下次开新团队）

---

## 1. 背景

`CaseToolbox.tsx` 顶部"输入信息"卡片当前承载 5 个字段：所属项目、关联需求、上传文件、需求描述、上下文信息。

用户调研显示：**所属项目**和**上下文信息**两个字段是"用得最多但形式最弱"的瓶颈——

- 所属项目：自由文本，每次手敲，不同人拼写不一致，无法做项目维度统计
- 上下文信息：单一大 TextField，测试人员写到哪里算哪里，LLM 接收到的 prompt 没有结构，生成用例的相关性波动大

本增量需求即解决这两点。

---

## 2. 范围

### ✅ 范围内（2 项）

#### P0 · 所属项目下拉化

| 项 | 详情 |
|---|---|
| **目标** | 把"所属项目"从自由 TextField 升级为 Autocomplete 下拉，数据来自新增的 `project_profiles` 表 |
| **数据模型** | 新表 `project_profiles`：`id` (TEXT PK), `name` (TEXT UNIQUE NOT NULL), `base_url` (TEXT), `description` (TEXT), `created_at`, `updated_at` |
| **CRUD** | 至少支持：列表、创建、改名、删除 4 个操作；后端给 4 个端点 |
| **前端** | MUI Autocomplete；支持"输入即搜索"；选中后存 `projectId` 到用例草稿/需求池；提供"+ 新建项目"入口（弹小 Dialog 输入 name + base_url） |
| **LLM 联动** | 生成用例的 prompt 注入 `{project_base_url}` `{project_description}` 上下文，让 LLM 知道项目环境 |
| **种子数据** | 启动时若 `project_profiles` 为空，插 2 条示例：ICM / DxONE |
| **位置** | `icm_platform/db.py`（DDL）、`icm_platform/api.py`（4 端点）、`web-ui/src/data/api.ts`（包装）、`web-ui/src/pages/CaseToolbox.tsx`（UI） |

#### P1 · 上下文信息结构化

| 项 | 详情 |
|---|---|
| **目标** | 把单一 TextField 拆为 4 个子字段 |
| **4 子字段** | `环境URL`（TextField，可空）/ `测试账号`（TextField，可空）/ `排除范围`（TextField multiline，可空）/ `参考文档`（TextField，可空） |
| **数据模型** | 暂不入库（轻量）；用 1 个 JSON 字段 `context_info` (TEXT) 存到 `cases` 表的 spec YAML 顶层 |
| **前端** | 在原位置用 4 个 Stack 排列；保持折叠/展开可选（默认展开） |
| **LLM 联动** | prompt 模板扩展 1 段："## 上下文信息\\n- 环境URL: {env_url}\\n- 测试账号: {test_account}\\n- 排除范围: {excluded}\\n- 参考文档: {refs}"；空字段省略 |
| **后端零侵入** | 不新增端点；改 `icm_platform/ai_service.py` 的 prompt 拼装即可 |
| **位置** | `web-ui/src/pages/CaseToolbox.tsx`（UI + 拼 prompt）、`icm_platform/ai_service.py`（prompt 模板） |

### ❌ 不在范围（明确划线）

| 项 | 划线理由 |
|---|---|
| 关联需求（ID 联动） | 暂时只展示文本，下拉留待下期 |
| 上传文件（XMind / XLSX 解析） | 解析器未稳，下期 |
| 需求描述（结构调整） | 非瓶颈，下期 |
| 多人协作（项目权限） | 越界，单独需求 |
| 数据迁移 | `cases` 表已有数据不迁移，新增字段用 NULL 默认 |

---

## 3. 验收标准

### P0 验收
- [ ] `python -m unittest icm_platform.tests.test_project_profiles` 通过
- [ ] `python -c "from icm_platform.api import list_projects, create_project"` 不报错
- [ ] 启动 web-ui 后，`所属项目` 字段是 Autocomplete（不是 TextField）
- [ ] 启动 web-ui 后，能"+ 新建项目"并出现在下拉中
- [ ] 启动 web-ui 后，刷新页面下拉值仍在
- [ ] LLM 生成用例的 prompt 包含 `Base URL: ...`（可通过 `ai_service._last_prompt` 调试看到）

### P1 验收
- [ ] 上下文区域渲染 4 个子字段
- [ ] 4 个字段值随用例保存到 `cases.spec_yaml.context_info`
- [ ] 调 `ai_service.generate_cases` 时，prompt 包含上下文段
- [ ] 全部字段留空时，prompt 不出现"上下文信息"段（不污染）
- [ ] `npx tsc -b --noEmit` EXIT=0

---

## 4. 任务列表（待架构师细化）

| 序 | 任务 | 估计行数 | 依赖 |
|---|---|---|---|
| T1 | `db.py`：加 `project_profiles` DDL + 启动时种子 2 条 | ~30 | — |
| T2 | `api.py`：4 端点（list / get / create / delete） | ~80 | T1 |
| T3 | `web-ui/src/data/api.ts`：4 包装 + 1 类型 | ~25 | T2 |
| T4 | `CaseToolbox.tsx`：所属项目改 Autocomplete + 新建项目 Dialog | ~120 | T3 |
| T5 | `ai_service.py`：生成 prompt 注入 project 上下文 | ~25 | T1 |
| T6 | `CaseToolbox.tsx`：上下文 4 子字段 | ~80 | — |
| T7 | `ai_service.py`：生成 prompt 注入 context_info 段 | ~30 | T6 |
| T8 | `icm_platform/tests/test_project_profiles.py` 单测 | ~120 | T2 |
| T9 | `runner/tests/test_ai_prompt_context.py`（mock LLM 验 prompt 拼接） | ~80 | T5 T7 |
| T10 | `npx tsc -b --noEmit` + 集成自测 | — | T4 T6 |

---

## 5. 风险与备注

1. **Lark MCP 不稳定**：上次 PM 节点 Spawn 失败，下次开团队时**先**手动跑一遍 PM 节点的 1 个最小任务确认可用，再展开
2. **`cases` 表已有数据**：`context_info` 字段默认 NULL，老用例照常工作
3. **项目名唯一约束**：UI 输入重复要 inline 校验，不能等后端 400
4. **prompt 长度**：4 字段全填满大约 +200 token，注意 `max_tokens` 限制
5. **不破坏路线 A/B/C 既有功能**：5 字段顺序保留为：项目/关联需求/上传/需求描述/上下文，**不重新排版**

---

## 6. 启动协议

下次启动 SOP 时按以下顺序：

1. 主理人创建团队 `software-icm-incremental-input`
2. 分派 PM（许清楚）写**增量 PRD**，引用本文件作为范围基线
3. PM 输出后 → 架构师（高见远）写**增量设计 + 任务列表**
4. 架构师输出后 → 工程师（寇豆码）实现 T1-T10
5. 工程师 IS_PASS: YES 后 → QA（严过关）验收
6. QA 全部通过 → 交付总结

PM 节点**启动前**先手测一次最小任务（"列出 P0/P1"），失败就走"快速模式"（跳过 PM，工程师直接吃这份存证）。

---

## 7. 版本

- v1.0 · 2026-06-10 15:54 · 范围锁定
