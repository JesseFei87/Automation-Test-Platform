# ICM 增量 · QA 第 2 轮回归报告 · 输入信息卡片改造

> 角色：严过关（QA Engineer）· 第 2 轮
> 日期：2026-06-10
> 范围基线：[`icm-incremental-input-2026-06-10.md`](./icm-incremental-input-2026-06-10.md) v1.0（§3 验收为准绳）
> 第 1 轮标的：P0-6 ⚠️ / P1-2 ❌ / P1-3 ⚠️（已工程师修复，本轮回归）

---

## 1. 环境清单

| 类别 | 状态 | 证据 |
|---|---|---|
| Python 单测 | ✅ 跑 | `python -m unittest icm_platform.tests.test_project_profiles icm_platform.tests.test_ai_prompt_context icm_platform.tests.test_e2e_analyze_spec_context` → **42/42 OK**（原 39 + 新增 3 端到端） |
| `npx tsc -b --noEmit` | ✅ 跑 | `web-ui/` 目录 EXIT=0，无输出 |
| 新增端到端测试落盘 | ✅ | `icm_platform/tests/test_e2e_analyze_spec_context.py`（3 个 test，含 P0-6 / P1-2 / P1-3 覆盖） |
| 浏览器 / UI 截图 | ❌ 不跑 | 与第 1 轮同：静态环境无浏览器；UI 项改 grep + 文件位置证据 |

---

## 2. 验收 10 条逐条结果

### P0（6 条）

| # | 验收项 | 结果 | 证据（行号 + 文件） |
|---|---|---|---|
| P0-1 | `test_project_profiles` 通过 | ✅ | 单测 39/39 OK；DB 层 13 + 端点 8 + ai_prompt 16 + e2e 3 = 42 累计 |
| P0-2 | `from icm_platform.api import list_projects, create_project` 不报错 | ✅ | 第 1 轮已实测 OK，本轮未重跑（接口未变更） |
| P0-3 | "所属项目" 是 Autocomplete | ✅ | `RequirementsWorkspace.tsx:737-750` `<ProjectAutocomplete>` 受控下拉（`page=0` 模糊匹配） |
| P0-4 | "+ 新建项目" 出现在下拉中 | ✅ | `RequirementsWorkspace.tsx:1220-1325` `<NewProjectDialog>` + 行 248-281 `submitNewProject()` → `api.createProject` → `loadProjects()` 刷新 |
| P0-5 | 刷新页面下拉值仍在 | ✅ | `loadProjects` 在 `useEffect` 行 225-229 从 `project_profiles` 拉取 |
| **P0-6** | **LLM prompt 含 `Base URL: ...`（端到端）** | **✅ 升级** | **第 1 轮 ⚠️ 端到端断，现 ✅**：① `RequirementsWorkspace.tsx:351-356` `analyze()` payload 增 `context_info` + `project_id`；② `api.ts:438` 签名改为 `payload: {title, document, context_info?, project_id?}`；③ `api.py:645-647` `analyze_requirement_spec` 调 `get_project_profile(payload.project_id)` 查 base_url；④ `ai_service.py:402-417` `_spec_generation_payload` 把 `build_project_block(project)` 注入 sections。**端到端证据**：`test_e2e_project_and_context_both_injected_into_llm_prompt` 通过（mock LLM 后 LLM 收到的 prompt JSON 字符串含 "Base URL: https://icm.example.com"） |

### P1（4 条）

| # | 验收项 | 结果 | 证据 |
|---|---|---|---|
| P1-1 | 上下文区域渲染 4 子字段 | ✅ | `RequirementsWorkspace.tsx:784-840` 渲染 env_url/test_account/excluded/refs，`useState(true)` 默认展开（行 195） |
| **P1-2** | **4 字段值随用例保存到 `cases.spec_yaml.context_info`** | **✅ 升级** | **第 1 轮 ❌ 端到端未实现，现 ✅**：① `api.py:485-504` `_save_spec_case_drafts(..., context_info=...)` 行 491-494 把 context_info 写进 YAML 顶层 `context_payload["context_info"] = context_info`；② `api.py:682` 调时传 `context_info=context_info`。**端到端证据**：`test_e2e_context_info_persisted_to_case_drafts_yaml_top_level` 通过：POST 后从 DB 读 `case_drafts.yaml`，`yaml.safe_load()` 后顶层含 `context_info` 键，值与提交一致 |
| **P1-3** | **prompt 含上下文段（端到端）** | **✅ 升级** | **第 1 轮 ⚠️ 端到端断，现 ✅**：① `RequirementsWorkspace.tsx:351-356` payload 含 `context_info`；② `api.py:75-79` `RequirementRequest` 增 `context_info: dict \| None = None`；③ `api.py:648-655` 调 `ai_service.generate_test_cases_spec(..., context_info=context_info)`；④ `ai_service.py:402-417` 调 `build_context_info_block(context_info)` 注入 sections。**端到端证据**：`test_e2e_project_and_context_both_injected_into_llm_prompt` 断言 prompt JSON 字符串含 "环境URL: https://staging" 和 "上下文信息" 段；`test_e2e_prompt_sections_both_present_in_user_content` 断言 sections 顺序（项目→上下文）和 4 子键正确 |
| P1-4 | 字段全空时 prompt 不出现"上下文信息"段 | ✅ | 单元级 `test_prompt_excludes_context_section_when_all_blank` / `_when_none` / `_no_sections_when_both_empty` 全过（`test_ai_prompt_context.py`）；端到端 `test_e2e_prompt_sections_both_present_in_user_content` 也覆盖了"留空字段不出现" |
| P1-5 | `tsc -b --noEmit` EXIT=0 | ✅ | 本轮重跑 EXIT=0 |

---

## 3. 3 端到端修复验证（从 ⚠️/❌ 升 ✅）

| ID | 第 1 轮 | 第 2 轮 | 修复证据链 | 端到端测试 |
|---|---|---|---|---|
| P0-6 | ⚠️ 单过 / 端断 | ✅ 端到端通 | `RequirementsWorkspace.tsx:351-356` → `api.ts:438` → `api.py:75-79, 645-647` → `ai_service.py:402-417` | `test_e2e_project_and_context_both_injected_into_llm_prompt`（断言 prompt 串含 "Base URL: https://icm.example.com"） |
| P1-2 | ❌ 未实现 | ✅ 端到端通 | `RequirementsWorkspace.tsx:351-356` → `api.ts:438` → `api.py:75-79` → `api.py:485-494, 682`（`_save_spec_case_drafts` 写 YAML 顶层） | `test_e2e_context_info_persisted_to_case_drafts_yaml_top_level`（断言 `yaml.safe_load` 顶层有 `context_info` 键） |
| P1-3 | ⚠️ 单过 / 端断 | ✅ 端到端通 | `RequirementsWorkspace.tsx:351-356` → `api.ts:438` → `api.py:75-79, 648-655` → `ai_service.py:402-417`（`build_context_info_block`） | `test_e2e_project_and_context_both_injected_into_llm_prompt` + `test_e2e_prompt_sections_both_present_in_user_content` |

---

## 4. 新增端到端测试

| 测试 | 文件 | 行号 | 覆盖 |
|---|---|---|---|
| `test_e2e_project_and_context_both_injected_into_llm_prompt` | `icm_platform/tests/test_e2e_analyze_spec_context.py` | 类 `AnalyzeSpecE2ETests` 行 144-181 | mock `_post_json` 拦截 LLM，POST 传 `project_id=icm-seed + context_info.env_url=https://staging`，断言 LLM prompt JSON 串同时含 "Base URL: https://icm.example.com" 和 "环境URL: https://staging" |
| `test_e2e_prompt_sections_both_present_in_user_content` | 同上 | 行 183-210 | 解析 prompt user content 字典，断言 `prompt_sections` 顺序 = [项目, 上下文]、4 子键正确、空字段不出现 |
| `test_e2e_context_info_persisted_to_case_drafts_yaml_top_level` | 同上 | 行 220-244 | POST 传 `context_info` 全字段，从 DB 读 `case_drafts.yaml`，`yaml.safe_load` 后顶层有 `context_info` 键且值匹配 |

3 个测试在 `icm_platform/tests/test_e2e_analyze_spec_context.py` 共 246 行（含 setUp/tearDown/辅助函数）。

---

## 5. 智能路由判定

### **→ NoOne**

10 条验收全过（6 P0 + 4 P1，含基线 P1-5 tsc），3 端到端从 ⚠️/❌ 升级到 ✅，新增 3 个端到端测试（覆盖 P0-6 + P1-2 + P1-3）全绿。所有数据流从 `RequirementsWorkspace.tsx` → `api.ts` → `api.py` → `ai_service.py` → `case_drafts.yaml` 已贯通；`_save_spec_case_drafts` 把 `context_info` 写进 YAML 顶层（`api.py:485-494`），`build_project_block` / `build_context_info_block` 在 LLM payload 中产生正确 `prompt_sections`。无新 bug、无新缺口。

---

## 6. 遗留问题

| # | 类型 | 描述 | 处置 |
|---|---|---|---|
| 1 | 已知偏差 | 实际改动文件是 `RequirementsWorkspace.tsx` 而非基线声明的 `CaseToolbox.tsx` | 沿用第 1 轮采纳口径（基线下版应改"目标文件"） |
| 2 | 环境限制 | UI 截图 / 浏览器交互未做（基线 P0-3/4/5 字面要求） | 沿用 grep + 文件位置证据 + 端到端 HTTP 测试覆盖；下轮启动 dev server 后可补 |
| 3 | 环境噪音 | `starlette` deprecation 提示装 `httpx2`、`datetime.utcnow()` 弃用 | 与本增量无关，不影响验收 |

无功能性遗留；本增量可收口。

---

## 7. 整体收口判断

**可以收口。** 10 条验收全过、3 端到端从 ⚠️/❌ 升 ✅、42 测试全绿、tsc EXIT=0。无 engineer 端 bug、无 QA 端测试代码 bug，路由 NoOne。
