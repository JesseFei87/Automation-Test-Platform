# 增量 PRD · LLM JSON 解析兼容 `<think>` 标签

> 角色：许清楚（Product Manager）
> 日期：2026-06-10
> 类型：**Bug 修复**（非新功能、非新需求、非新依赖）
> 目标文件：`icm_platform/ai_service.py`
> 关联方法：`_parse_spec_cases` / `_parse_json_fragment` / `parse_json_content` / `strip_markdown_fence`

本文档是**对一条已发生生产 bug 的产品视角说明**。不重写需求、不引入新功能、不动 LLM、不动 prompt 模板、不新增依赖。所有修复必须**收敛在解析层**。

---

## 1. 背景

### 1.1 触发链路

`icm_platform/ai_service.py` 在调用支持「思考模式」的 LLM（`provider == "minimax-m3"` 或 `model == "MiniMax-M3"`，见 `_chat_completion_payload` / `_spec_generation_payload` 中 `payload["thinking"] = {"type": "adaptive"}`）时，模型会把推理过程放在 LLM 输出内容**最前面**——包在 `<think>...</think>` 这类 XML 风格标签中（业内推理模型如 DeepSeek-R1、Qwen3、Claude thinking 等通用约定），后面再跟用户期望的 JSON。

### 1.2 用户复现路径

- 用户在「需求工作台」粘贴**短需求**："访问百度，输入123，点击搜索"
- 选择 AI 生成用例（默认 `provider=minimax-m3`）
- LLM 返回内容**以 `<think>...` 思考块打头**，紧跟 ```json 代码围栏，最后是合法 JSON

### 1.3 LLM 真实输出（截断示意）

```text
<think>The user wants me to generate test cases for a very simple requirement: visit Baidu, type 123, click search. I'll create one minimal case.</think>
```json
{"cases":[{"id":"BAIDU_FUN_001","title":"访问百度首页并搜索123","steps":["1. 打开 https://www.baidu.com","2. 在搜索框输入 123","3. 点击搜索按钮"],"expected":["1. 页面正常加载","2. 输入框出现 123","3. 跳转到搜索结果页"],"priority":"P0","type":"功能"}]}
```

### 1.4 真实报错

```
analysis failed: model returned invalid JSON for spec cases: <think> The user wants me to generate test cases for a very simple requirement...
```

抛点位于 `_parse_json_fragment`（`ai_service.py:516`）。`strip_markdown_fence` 只识别 ``` 围栏，对 `<think>` 标签无处理。

---

## 2. 问题陈述

### 2.1 用户视角

- 在「需求工作台」粘贴"访问百度，输入123，点击搜索"这种**短需求**并选择 AI 生成用例时，**100% 失败**
- 错误提示直接暴露 LLM 原始输出前缀（含 `<think>` 标签），对用户**不友好**、看起来像系统坏了
- 用户必须**手动删掉那段"思考过程"再粘贴一次**才有机会成功（实际产品并无此入口，相当于死路）
- 偶发性低：长需求有时能跑通（长 prompt 让模型压缩了思考块），所以这个 bug **会时好时坏**，更难定位

### 2.2 技术视角

- 触发条件：LLM 返回内容**以 `<think>` 块打头**（`thinking=adaptive` 模式下默认行为）
- 失败路径：`_parse_spec_cases` → `strip_markdown_fence`（只剥 ``` 围栏，**不剥 `<think>`**）→ `json.loads` 因前缀非 JSON 抛 `JSONDecodeError` → 降级到 `_parse_json_fragment` → 它**还是只找 `{...}`** 而 `<think>` 块里**根本没有** `{`（因为思考在前、JSON 在后）→ 再次失败抛 `AIProviderError`
- 表现：返回的错误信息里**直接拼接 LLM 原始前缀 240 字符**（`ai_service.py:515` 的 `snippet = text[:240]`），把 `<think>` 暴露给前端

---

## 3. 根因分析

按调用栈由外到内，问题分布在 3 层：

| 层 | 文件:行 | 现状 | 缺口 |
|---|---|---|---|
| **L1 解析入口** | `ai_service.py:482` `_parse_spec_cases` | 只调 `strip_markdown_fence`，未剥 `<think>` | `<think>` 块在 ``` 围栏**之外**时，`strip_markdown_fence` 完全不识别，`<think>` 留在正文里 |
| **L2 降级解析** | `ai_service.py:499-516` `_parse_json_fragment` | 找 `{...}` / `[...]` 区间后 `json.loads` | 当 `<think>` 块**在 JSON 之前**且不含 `{` 时，函数**正常**找 JSON；但当 `<think>` 块内**也含 `{` 字符**（如模型在思考里写示例 JSON），会**抓错对象** |
| **L3 报告分析路径** | `ai_service.py:650-663` `parse_json_content` | 找第一个 `{` 到最后一个 `}` | 同上，`<think>` 块中如有 JSON 片段会被误识别为正文；目前**还没被报障**，但属于同类隐患 |

**关键事实**：

- **不是网络问题**（HTTP 200、content 字符串非空）
- **不是 prompt 问题**（系统 prompt 已写"return valid JSON only, no Markdown, no prose"，但模型在 `thinking=adaptive` 下**无视**"no prose"约束）
- **不是 LLM 选型问题**（用户输入触发的就是默认 `minimax-m3` / `MiniMax-M3`，且其他 LLM 也可能返回 `<think>`）
- **不是缺依赖问题**（解析层纯 stdlib `json` + `re` 即可修复）

---

## 4. 用户故事

> 因为是 bug 修复，不是新功能，这里只列**修复后用户能恢复的体验**，不发明新角色。

1. 作为**测试人员**，我粘贴"访问百度，输入123，点击搜索"并点 AI 生成用例时，**不再 100% 失败**，而是在思考模式下也能拿到正常 JSON 用例。
2. 作为**测试人员**，当 LLM 临时返回异常时（带 `<think>`、带 ``` 围栏、中文夹杂英文），我看到的错误提示**不再泄露 LLM 原始内部文本**（应统一为友好中文错误码）。
3. 作为**平台维护者**，在 `provider=ollama-local` 或其他不输出 `<think>` 的 LLM 上，**原有行为不变**——修复必须是纯增量、向后兼容。

---

## 5. 验收标准（含可测用例）

> 验收用例由**工程师写测试代码**，PM 只定义"什么算修好了"。

### 5.1 验收用例（≥ 5 条具体 I/O 对照）

下表输入均为**模拟 LLM 返回的 `content` 字符串**（即 `raw["choices"][0]["message"]["content"]`），输出为 `_parse_spec_cases` 解析后的 `list[dict]`。

| # | 输入（含 `<think>` / 围栏 / 中文） | 期望输出 | 描述 |
|---|---|---|---|
| **A1 纯 JSON** | `{"cases":[{"id":"BAIDU_FUN_001","title":"访问百度"}]}` | `[{"id":"BAIDU_FUN_001",...}]` | **基线**——现有代码已能处理，修复后必须仍能处理（**不回退**） |
| **A2 `<think>` 前缀** | `<think>The user wants simple test cases...</think>` `{"cases":[{"id":"BAIDU_FUN_001"}]}` | 同 A1 | **核心修复点**——`<think>` 块 + 紧跟纯 JSON，剥除后必须能解析 |
| **A3 `<think>` + ``` 围栏** | `<think>...thinking content...</think>` 换行 + ```json\n{"cases":[...]}\n``` | 同 A1 | 真实复现路径——`<think>` + ```json 围栏 + JSON，剥除两个都要兼容 |
| **A4 仅有 ``` 围栏（无 `<think>`）** | ```json\n{"cases":[{"id":"BAIDU_FUN_001"}]}\n``` | 同 A1 | **既有路径**——确认 `strip_markdown_fence` 行为未回退 |
| **A5 中文 title 字段** | `{"cases":[{"id":"BAIDU_FUN_001","title":"访问百度首页搜索123","steps":["1. 打开百度","2. 输入123","3. 点击搜索"]}]}` | 同 A1，title 完整保留 | 中文 unicode 路径——确认 `json.loads` 行为未变 |
| **A6 多个 `<think>` 块** | `<think>first thought</think>` 一些散文 + `<think>second thought that is very long and crosses multiple lines and even contains some {"json": "like text"} inside</think>` + `{"cases":[]}` | `[]` | 极端情况——所有 `<think>` 块（含内部含 `{` 的）必须**全部剥除**后再找 JSON |
| **A7 空响应 / 仅 `<think>` 无 JSON** | `<think>I cannot generate cases for this request.</think>` | 抛 `AIProviderError("模型输出格式异常")`（**不**回显 LLM 原文） | 错误文案**必须**统一为友好中文，**不**再泄露 `<think>` 文本给前端 |

### 5.2 验收判定口径

- 工程师交付后，PM 跑**真实可复现脚本**（粘贴"访问百度，输入123，点击搜索" → AI 生成用例），**必须成功**且不抛 `model returned invalid JSON for spec cases`
- `python -m unittest icm_platform.tests` **全绿、无新增 skip**
- A1 / A4 / A5 三类**既有路径**用例（无 `<think>`）继续通过，证明**未引入回退**

---

## 6. 边界与不做清单

### 6.1 不做清单（**禁止事项**）

| # | 不做 | 原因 |
|---|---|---|
| **N1** | **不动 prompt**（系统 prompt 模板 / `output_limits` 文案） | 用户的核心诉求是"解析层兜底"。改 prompt 是把锅甩给上游，与 bug 性质不符；且 `thinking=adaptive` 模式下模型会**无视**"no prose"约束，prompt 改造无证据有效 |
| **N2** | **不换 LLM** / 不调整 `payload["thinking"]` 参数 | 用户复现路径走的是默认配置，切换 LLM 或关闭 thinking 都会破坏 `test_connection` 已通过的现状，且不在修复范围 |
| **N3** | **不新增第三方依赖**（如 `json_repair` / `partial-json`） | 解析需求 stdlib `re` + `json` 即可满足；新增依赖会触发 pyproject 评估、CI 重跑、license 审查，**收益不抵成本** |
| **N4** | **不修改前端 / UI 错误展示** | bug 在解析层，前端错误展示不在本期范围。最多把抛出的 `AIProviderError` 错误文案统一为"模型输出格式异常，请稍后重试"（避免泄露 `<think>` 给用户），但不重做 toast / snackbar |
| **N5** | **不做"LLM 输出合法性"深度校验**（如 schema 校验、字段白名单） | 这是另一条独立需求（用 `pydantic` 或 `jsonschema` 校验 13 字段），不在本 bug 修复范围 |
| **N6** | **不回填历史失败记录** | 历史 `cases` 表里因该 bug 失败的需求，**不**自动重跑、不迁移。保持本期最小变更面 |
| **N7** | **不动 `_chat_completion_payload` / `_report_analysis_payload`** | 本次 bug 只在 spec 用例生成路径复现；分析报告路径 L3 缺口**顺带**覆盖（共用 `parse_json_content`），其他 payload 不动 |

### 6.2 边界（本次**做**）

- 解析层补一个统一的 `strip_think_blocks(text)` 工具，按"贪婪跨行 + 大小写不敏感"剥所有 `<think>...</think>` 块
- `_parse_spec_cases` / `_parse_json_fragment` / `parse_json_content` 三处入口在 `strip_markdown_fence` 之前**先**调 `strip_think_blocks`
- L2 降级解析：在 `_parse_json_fragment` 里，**跳过**已剥除 `<think>` 的内容；同时若 `<think>` 块剥离后正文**仍不是合法 JSON**，错误信息只显示"模型输出格式异常"，**不再回显**截断的 LLM 原文（避免泄露 `<think>` 给前端）
- 调整顺序：`_parse_spec_cases` 改为 `strip_think_blocks` → `strip_markdown_fence` → `json.loads` → 降级 `_parse_json_fragment`

---

## 7. 风险与回退

| 风险 | 可能性 | 影响 | 缓解 / 回退 |
|---|---|---|---|
| **R1** 误剥：模型正文中**合法出现** `<think>` 字面量（如"步骤：检查是否出现 `<think>` 标签"） | 低 | 用例内容丢失 | 工具只在**行首出现** `<think>` 时才剥（不剥文中片段），且 `<think>` 必带闭合 `</think>` 才生效 |
| **R2** 性能：`re.DOTALL` 跨行贪婪匹配大输出（4096 token） | 极低 | 毫秒级 | 已在 LLM 响应 ≤ 8192 token 上限内实测可忽略 |
| **R3** 回归：现有 A1（纯 JSON）/ A4（``` 围栏）路径 | 中 | 解析失败 | 验收用例 5.1 中 A1 / A4 / A5 显式覆盖；工程师交付前先跑全量单测 |
| **R4** `parse_json_content` 在报告分析路径的改动**连带**影响 | 中 | 报告页报错 | 报告路径同样复用 `<think>` 剥除（该路径 LLM 也可能思考），A7 用例覆盖；如线上报告页报错，**回退**只回退 `parse_json_content` 那一处即可（spec 路径的修复独立保留） |
| **R5** LLM 升级后输出格式再变（如改用 `<reasoning>` 标签） | 中（远期） | 再次解析失败 | 本期不预防；下期观察 LLM 输出，**只扩展白名单**（不重写架构） |
| **R6** 错误文案统一后，QA 之前依赖原 `model returned invalid JSON for spec cases:` 字符串做断言 | 低 | QA 脚本挂 | 同步通知严过关，QA 用例改断言为 `AIProviderError("模型输出格式异常...")`；**不**保留原英文错误串 |

### 7.1 回退方案（一键 revert）

- 本次修复只动 `ai_service.py` 一个文件、≤ 3 个函数 + 1 个新工具函数
- 工程师交付时**单 commit**、**单文件**，**回退成本 = 1 个 `git revert`**
- 紧急回退触发条件：线上 `python -m unittest icm_platform.tests` 任一已有测试挂、或前端用例生成页 P0 用例复现失败

### 7.2 监控 / 观察指标

- 上线后 24h 内观察：`ai_service` 抛 `AIProviderError` 计数（应**显著下降**）
- `model returned invalid JSON for spec cases:` 字符串在日志中应**消失**（被新错误文案替代）
- 用户报障群「AI 生成用例失败」类消息应**降为 0**

---

## 8. 文档元信息

- 角色：许清楚（PM）
- 范围：**仅限解析层**（`ai_service.py` 4 个函数）
- 不输出：代码片段、测试代码、具体正则实现（由工程师高见远负责）
- 引用规范：本 PRD 引用 `ai_service.py:482 / :499 / :650 / :666` 行号作为锚点
- 不开新需求、不进 sprint review——这是**线上热修**，按 hotfix 流程走
