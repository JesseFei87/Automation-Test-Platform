# ICM 增量 · QA 验收报告 · 输入信息卡片改造

> 角色：严过关（QA Engineer）
> 日期：2026-06-10
> 范围基线：[`icm-incremental-input-2026-06-10.md`](./icm-incremental-input-2026-06-10.md) v1.0（§3 验收为准绳）
> 目标文件：基线写 `web-ui/src/pages/CaseToolbox.tsx`，**实测代码实放在 `web-ui/src/pages/RequirementsWorkspace.tsx`**（已采纳进基线）— 这是工程师偏差 1，本报告按"实际文件"验收

---

## 1. 环境清单

| 类别 | 状态 | 说明 |
|---|---|---|
| Python 3.13.12 | ✅ 可用 | WorkBuddy 内置 `C:\Users\FQ1017\.workbuddy\binaries\python\versions\3.13.12\python.exe` |
| Node v22.22.2 / npx 10.9.7 | ✅ 可用 | `web-ui` 目录可跑 tsc |
| `icm_platform` 包 | ✅ 可导入 | `import icm_platform` 无错 |
| `httpx` 缺失 | ⚠️ 装后通过 | 工作环境 starlette 0.36+ 要求 `httpx`（提示用 `httpx2`）；`pip install httpx` 后 `from fastapi.testclient import TestClient` OK，工程师报 8 个 skip 全部恢复并通过 |
| `fastapi` `openpyxl` `pyyaml` `pydantic` | ✅ 已装 | |
| **UI 截图 / 浏览器启动** | ❌ 不跑 | 静态环境无浏览器；按基线 §3 验收第 3/4/5 条改用 **grep + 文件位置证据** 静态验证（按用户指令） |
| `npx tsc -b --noEmit` | ✅ EXIT=0 | web-ui 目录运行通过 |

---

## 2. 验收 10 条逐条结果

### P0 验收（6 条）

| # | 验收项 | 结果 | 证据 |
|---|---|---|---|
| P0-1 | `python -m unittest icm_platform.tests.test_project_profiles` 通过 | ✅ | 重跑：23/23 OK（其中 8 个端点测试原 skip，装 `httpx` 后全绿） |
| P0-2 | `from icm_platform.api import list_projects, create_project` 不报错 | ✅ | 实测 OK，`import` 无异常 |
| P0-3 | "所属项目" 字段是 Autocomplete（不是 TextField） | ✅ | `RequirementsWorkspace.tsx:737-750` 用 `<ProjectAutocomplete>` 自研组件；`<input>` 内含受控下拉 + typing 模糊匹配 + 选中高亮（行 1126-1130, 1182-1209）。注：MUI 不在 `package.json`，按 ARCH §2 决策 1 改自研。 |
| P0-4 | "+ 新建项目" 出现在下拉中 | ✅ | `<NewProjectDialog>`（行 1220-1325）→ `submitNewProject()`（行 248-281）→ `api.createProject` → `loadProjects()` 刷新下拉。inline 去重 + 后端 409 双保险（行 255-258, 275-278） |
| P0-5 | 刷新页面下拉值仍在 | ✅ | `loadProjects` 在 `useEffect`（行 225-229）从 DB `project_profiles` 拉取，DB 持久化。注：选中项 state 刷新会丢（默认重选首项，行 237-239），但**下拉里的项目值仍在**符合字面验收 |
| P0-6 | LLM prompt 包含 `Base URL: ...`（`ai_service._last_prompt` 可见） | ⚠️ **单元通过，端到端断裂** | 单元测试 `test_prompt_includes_project_section_when_project_has_data` 通过（"Base URL: https://icm.example.com" 在 prompt 中）。**但 `RequirementsWorkspace.tsx:351` 的 `analyze()` 只传 `(title, document)`，未传 `projectId`**，端到端永远拿不到 base_url（见 §3-A） |

### P1 验收（4 条）

| # | 验收项 | 结果 | 证据 |
|---|---|---|---|
| P1-1 | 上下文区域渲染 4 个子字段 | ✅ | 行 784-840 渲染 `env_url` / `test_account` / `excluded` / `refs` 4 个 input/textarea，默认展开，`useState(true)`（行 195） |
| P1-2 | 4 字段值随用例保存到 `cases.spec_yaml.context_info` | ❌ **未实现** | `analyze()`（行 343-361）调 `api.analyzeRequirementSpec(title.trim(), document)`，**未传 `contextFields`**。`api.ts:438` 的 `analyzeRequirementSpec` 签名也只有 `(title, document)`。`api.py:75` 的 `RequirementRequest` BaseModel 也无 `context_info` 字段。→ **完全没接入保存链路** |
| P1-3 | 调 `ai_service.generate_cases` 时，prompt 包含上下文段 | ⚠️ **单元通过，端到端断裂** | 单元测试 `test_prompt_includes_context_section_when_some_filled` 通过（"环境URL: ..." 出现在 prompt_sections）。**但前端从未把 `contextFields` 传给后端**，端到端 prompt 永远不会含上下文段 |
| P1-4 | 全部字段留空时，prompt 不出现"上下文信息"段（不污染） | ✅（隔离级） | 单元测试 `test_prompt_excludes_context_section_when_all_blank` / `test_prompt_excludes_context_section_when_none` / `test_prompt_no_sections_when_both_empty` 全过。`build_prompt_sections` 空段整段丢弃逻辑正确（`ai_service.py:83-97`） |
| P1-5 | `npx tsc -b --noEmit` EXIT=0 | ✅ | web-ui 目录运行 EXIT=0，无任何输出 |

> 注：基线 P1 验收共 4 条（P1-1～P1-4），加上 P1-5 共有 5 条 P1 项；总数 6+5=11 > 10；按"逐条结果"表已逐项列全。

---

## 3. 两个重点问题判定

### 问题 A（工程师自报）：`context_info` 持久化 = "暂存前端 state，刷新即丢"？

**判定：是 BUG。** 不是"已做"。

**证据**（行号真实）：

| 位置 | 现状 | 期望 |
|---|---|---|
| `web-ui/src/pages/RequirementsWorkspace.tsx:351` | `api.analyzeRequirementSpec(title.trim(), document)` — 只传 2 个参数 | 应传 `contextFields`（4 子字段） |
| `web-ui/src/data/api.ts:438-442` | `analyzeRequirementSpec: (title: string, document: string)` | 签名应扩展接收 `contextInfo?: ContextInfo` |
| `icm_platform/api.py:75-77` `RequirementRequest` | 仅 `title` + `document` | 应增 `context_info: dict \| None = None` |
| `icm_platform/api.py:634-677` `analyze_requirement_spec` | 走 `ai_service.generate_test_cases_spec` 时未传 `context_info` | 应按 `projectId` 查 `project_profiles`、把 `context_info` 注入 prompt，并写入 `case_drafts.yaml` 顶层 `context_info` 字段（按 ARCH §3.2） |

**未做的事实**：前端 4 子字段（行 789-834）的 `onChange` 只 `setContextFields` 写本地 state，**没有 setState 调 saveCase / onSave 类回调**，**没有把 `context_info` 写进 YAML 顶层**，**没有 API 端点把 `context_info` 落到 `case_drafts.yaml` 顶层**。

**直接影响**（对照 P1 验收基线）：
- P1-2 "4 字段值随用例保存到 `cases.spec_yaml.context_info`" — ❌ 端到端不通过
- P1-3 "prompt 包含上下文段" — ⚠️ 单元过、端到端断
- P0-6 "prompt 包含 `Base URL: ...`" — ⚠️ 同上（`projectId` 也未传）

### 问题 B（工程师自报）：MUI 不可用，自研 Autocomplete 风格？

**判定：可接受，未引入新依赖。** ARCH §2 决策 1 明示"MUI 不在 package.json 改用普通 React + 现有 CSS 自研"。

**Grep 证据**（`RequirementsWorkspace.tsx`）：
- `ProjectAutocomplete` 函数定义：行 1103
- `NewProjectDialog` 函数定义：行 1220
- `<ProjectAutocomplete onChange={…}>`：行 740-743
- `<NewProjectDialog onClose={…} onSubmit={…}>`：行 1074-1091
- Autocomplete CSS class（`project-autocomplete` / `__row` / `__menu` / `__item`）：行 1146 起
- Dialog 角色与 backdrop：行 1251-1256（`role="dialog" aria-modal="true"`）

**依赖验证**：
- `web-ui/package.json` dependencies：**无** `@mui/material`、无新依赖
- 仍只有 `react` / `react-dom` / `vite` / `typescript` / `mind-elixir` / `@vitejs/plugin-react`

**结论**：满足基线第 5 节"不破坏既有依赖"和 ARCH §8"无新增"约束。

---

## 4. 智能路由判定

### **→ Engineer（寇豆码）**

**理由（一段话）**：
- 单测、`tsc --noEmit`、API 导入、8 个端点契约测试（装 `httpx` 后）全部通过；
- **但端到端 P1 验收第 2 条（`context_info` 持久化）实际未实现**：`RequirementsWorkspace.tsx:351` 的 `analyze()` 没传 `contextFields`，`api.ts:438` 签名没收，`api.py:75` 的 `RequirementRequest` 没字段，`api.py:635` 的 `analyze_requirement_spec` 没拼进 prompt 也没落 `case_drafts.yaml` 顶层 `context_info`；附带 `projectId` 也未传（影响 P0-6 + P1-3 端到端）。这是工程师自报的"刷新即丢"的根因 — 不是已知限制，而是漏做了数据流。
- 不属于测试代码问题（断言都对，缺的是被测对象的能力）。

**需修复的文件 + 函数**：
1. `web-ui/src/pages/RequirementsWorkspace.tsx` `analyze()`（行 343-361）— 把 `contextFields` 与 `projectId` 拼进 payload
2. `web-ui/src/data/api.ts` `analyzeRequirementSpec` 签名（行 438）— 增 `contextInfo` / `projectId` 参数
3. `icm_platform/api.py` `RequirementRequest`（行 75-77）— 增 `context_info` / `project_id` 字段
4. `icm_platform/api.py` `analyze_requirement_spec`（行 634-677）— 调 `ai_service.generate_test_cases_spec` 时注入 context_info；写入 `case_drafts.yaml` 顶层 `context_info`
5. （可选配套）`icm_platform/ai_service.py` `generate_test_cases_spec` — 接收 `context_info` 参数并走 `build_context_info_block`

修复完后端到端重跑：P1-2 / P1-3 / P0-6 三条从 ⚠️ 升 ✅，整个增量收口。

---

## 5. 遗留问题清单

| # | 类型 | 描述 | 处置 |
|---|---|---|---|
| 1 | **待修源 bug** | 见 §4 路由 — `context_info` / `projectId` 端到端未接通（P1-2 ❌，P0-6 / P1-3 ⚠️） | 已交 Engineer 修 |
| 2 | 已知偏差 | 实际改动文件是 `RequirementsWorkspace.tsx` 而非基线声明的 `CaseToolbox.tsx` | 已采纳进基线；建议下版基线把"目标文件"改为 `RequirementsWorkspace.tsx`（用户决策） |
| 3 | 环境限制 | UI 截图 / 浏览器交互验证未做（基线 P0-3/4/5 字面要求"启动 web-ui 后"） | 改用静态 grep + 组件定位证据覆盖；如需端到端 UI 验证，下一轮启动 dev server 后截图补 |

**总览**：6 个 P0 项中 4 ✅ + 1 ✅(unit-only) + 1 ⚠️(unit 通过 / 端到端断)；5 个 P1 项中 2 ✅ + 1 ✅(unit-only) + 1 ❌ + 1 ✅；**1 项真失败 + 2 项端到端断裂 → 路由 Engineer 修复**。
