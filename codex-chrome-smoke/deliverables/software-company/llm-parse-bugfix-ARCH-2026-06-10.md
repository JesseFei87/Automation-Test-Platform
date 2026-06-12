# 架构设计 · LLM JSON 解析兼容 `<think>` 标签

> 角色：高见远（Architect / 工程师）· 日期：2026-06-10
> 范围：**只动 `icm_platform/ai_service.py` 一个生产文件** + 新增 1 个测试文件
> 依据：许清楚《增量 PRD》(PM-2026-06-10)
> 行号已对源码逐行核对（`ai_service.py:482 / :499 / :650 / :666` 全部命中）

---

## 1. 实施总览

**核心思路**：在解析层插入 1 个工具函数 `strip_think_blocks(text)`，在 3 个解析入口（`_parse_spec_cases` / `_parse_json_fragment` / `parse_json_content`）的最前面统一调用——LLM 在 JSON 之前输出的 `<think>...</think>` 先剥光再交给既有 `strip_markdown_fence` + `json.loads` 链。同时把 `_parse_json_fragment` 末行错误文案统一为中文"模型输出格式异常"，**去掉**回显 LLM 前 240 字符（解决前端泄露 `<think>`）。

**技术选型**：

| 决策 | 选择 | 理由 |
|---|---|---|
| 剥除实现 | `re.sub(r"<think>.*?</think>", "", text, re.IGNORECASE\|re.DOTALL)` | N3 禁第三方；贪婪跨行匹配 R2 可忽略 |
| 误剥保护 | 强制配对闭合 `</think>` 才替换 | 规避 R1——孤立 `<think>` 字面量不剥 |
| 顺序 | `strip_think_blocks` → `strip_markdown_fence` → `json.loads` | PRD 6.2 明确 |
| 错误文案 | 中文"模型输出格式异常" | 替代 `model returned invalid JSON: <snippet>` |
| 文件数 | 生产 1 + 测试 1 | 满足"只动 1 个生产文件"硬约束 |

`ai_service.py` 是**纯解析层 + urllib 包装**，无 DI 容器。改动**局部、向后兼容、零接口变更**——3 个被改函数对外签名完全不变，调用方（`generate_cases_with_ai` / `analyze_spec_with_ai` / 报告 worker）零修改。

---

## 2. 函数签名与调用顺序

### 2.1 新增 `strip_think_blocks`（模块级，紧邻 `strip_markdown_fence` 上方）

```python
import re                                       # ← 新增到 :9 之后

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)

def strip_think_blocks(content: str) -> str:
    """剥除 LLM 推理模型在 JSON 之前输出的 <think>...</think> 思考块。"""
    if not content:
        return content
    return _THINK_BLOCK_RE.sub("", content).strip()
```

**边界**：`None`/空 → 原样；无 `<think>` → 原样（re 短路）；有开无闭 → 不剥（R1）；多块嵌套 → 全部剥。

### 2.2 改造点 diff

| 位置 | 原 | 改 |
|---|---|---|
| `:482` `_parse_spec_cases` 首行 | `text = strip_markdown_fence(content)` | 前置 `text = strip_think_blocks(content)`，再 `strip_markdown_fence` |
| `:499` `_parse_json_fragment` 首行 | （无） | 前置 `text = strip_think_blocks(text)`（幂等防御） |
| `:499` `_parse_json_fragment` 末行 | `raise AIProviderError(f'model returned invalid JSON for spec cases: {snippet}')` | `raise AIProviderError('模型输出格式异常')`（去掉 snippet） |
| `:650` `parse_json_content` 首行 | `text = content.strip()` | `text = strip_think_blocks(content.strip())` |

### 2.3 调用顺序总览

```
generate_cases_with_ai()
  └─ _parse_spec_cases(content)                          [L1 入口]
       ├─ strip_think_blocks(content)         ← NEW
       ├─ strip_markdown_fence(text)
       ├─ json.loads(text) | 失败↓
       └─ _parse_json_fragment(text)                    [L2 降级]
            ├─ strip_think_blocks(text)       ← NEW 幂等
            ├─ find {…} / […] 区间
            ├─ json.loads(candidate) 循环尝试
            └─ 全部失败 → raise AIProviderError('模型输出格式异常')

报告 worker
  └─ parse_json_content(content)                        [L3]
       ├─ strip_think_blocks(content.strip()) ← NEW
       └─ 围栏处理 + json.loads(首{…末})
```

---

## 3. 任务列表（按依赖排序）

> 本 hotfix 生产改动只覆盖 1 个文件，2 个任务覆盖全部；符合 ≤ 5 上限。

| ID | 任务名 | 改动文件 | 依赖 | 优先级 |
|---|---|---|---|---|
| **T1** | 解析层全量改造 | `icm_platform/ai_service.py` | — | **P0** |
| **T2** | 单元测试 + 全量回归 | `icm_platform/tests/test_ai_service_think.py`（新增） | T1 | **P0** |

**T1 步骤**：(1) 顶部新增 `import re`；(2) 紧邻 `strip_markdown_fence` 上方新增 `_THINK_BLOCK_RE` + `strip_think_blocks`；(3) 按 §2.2 改 3 个函数 + 1 处错误文案。
**快速自检**：`python -c "from icm_platform.ai_service import strip_think_blocks; print(strip_think_blocks('<think>x</think>{\"a\":1}'))"` → `{"a":1}`。

**T2 步骤**：(1) 新建测试文件（见 §5）；(2) 跑 `python -m unittest icm_platform.tests` 确认**全绿、无新增 skip**；(3) 重点确认 A1/A4/A5 不回退。

---

## 4. 文件清单（路径 + 改动类型）

| 路径 | 改动类型 | 理由 |
|---|---|---|
| `icm_platform/ai_service.py` | **MODIFY**（唯一生产文件） | + 1 import + 1 工具函数 + 改 3 函数 + 1 处错误文案 |
| `icm_platform/tests/test_ai_service_think.py` | **NEW** | 7+ 条单测 1:1 覆盖 PRD 5.1 A1–A7 |
| `icm_platform/tests/__init__.py` | NO-CHANGE | 既有测试发现逻辑不变 |
| 其他 10 个 `tests/test_*.py` | **NO-CHANGE** | 与本 bug 无关 |
| `icm_platform/api.py` / `worker.py` / `db.py` | **NO-CHANGE** | N1/N7 明确不动 |
| `deliverables/.../*.md` | **NO-CHANGE** | 文档只读 |

---

## 5. 单测设计（≥ 7 条覆盖 PRD 5.1 全部）

**文件**：`icm_platform/tests/test_ai_service_think.py`
**框架**：`unittest`（项目既有约定，与 `test_ai_prompt_context.py` 一致）
**fixture**：直接用字面量字符串，与 PRD 5.1 表格 1:1 对齐。

```python
from __future__ import annotations
import unittest
from icm_platform.ai_service import (
    AIService, AIProviderError, parse_json_content, strip_think_blocks,
)


class TestStripThinkBlocks(unittest.TestCase):
    def test_strip_simple(self):
        self.assertEqual(strip_think_blocks("<think>hello</think>{}"), "{}")

    def test_strip_multiple_with_braces_inside(self):
        text = ('<think>a {"b":"c"} first</think>middle'
                '<think>second with {"x":1} inside</think>{"x":1}')
        self.assertEqual(strip_think_blocks(text), 'middle{"x":1}')


class TestParseSpecCases(unittest.TestCase):
    def test_a1_pure_json_baseline(self):                              # A1
        out = AIService._parse_spec_cases(
            '{"cases":[{"id":"BAIDU_FUN_001","title":"访问百度"}]}')
        self.assertEqual(out, [{"id": "BAIDU_FUN_001", "title": "访问百度"}])

    def test_a2_think_prefix_then_pure_json(self):                     # A2 核心
        text = "<think>The user wants simple test cases.</think>" + \
               '{"cases":[{"id":"BAIDU_FUN_001"}]}'
        self.assertEqual(AIService._parse_spec_cases(text),
                         [{"id": "BAIDU_FUN_001"}])

    def test_a3_think_plus_fence(self):                                # A3 真实复现
        text = "<think>...thinking content...</think>\n```json\n" + \
               '{"cases":[{"id":"BAIDU_FUN_001"}]}\n```'
        self.assertEqual(AIService._parse_spec_cases(text),
                         [{"id": "BAIDU_FUN_001"}])

    def test_a4_fence_only_no_think(self):                             # A4 既有路径
        text = "```json\n" + '{"cases":[{"id":"BAIDU_FUN_001"}]}\n```'
        self.assertEqual(AIService._parse_spec_cases(text),
                         [{"id": "BAIDU_FUN_001"}])

    def test_a5_chinese_unicode(self):                                # A5 中文
        text = ('{"cases":[{"id":"BAIDU_FUN_001",'
                '"title":"访问百度首页搜索123",'
                '"steps":["1. 打开百度","2. 输入123","3. 点击搜索"]}]}')
        out = AIService._parse_spec_cases(text)
        self.assertEqual(out[0]["title"], "访问百度首页搜索123")
        self.assertEqual(len(out[0]["steps"]), 3)

    def test_a6_multiple_think_blocks_with_braces_inside(self):        # A6 极端
        text = ("<think>first thought</think>一些散文"
                '<think>second that is long and crosses lines and '
                'contains some {"json": "like text"} inside</think>'
                '{"cases":[]}')
        self.assertEqual(AIService._parse_spec_cases(text), [])

    def test_a7_only_think_no_json_raises_safe_error(self):            # A7 错误文案
        with self.assertRaises(AIProviderError) as ctx:
            AIService._parse_spec_cases(
                "<think>I cannot generate cases for this request.</think>")
        self.assertIn("模型输出格式异常", str(ctx.exception))
        self.assertNotIn("<think>", str(ctx.exception))                # 不泄露
        self.assertNotIn("cannot generate", str(ctx.exception))        # 不回显


class TestParseJsonContentReportPath(unittest.TestCase):
    def test_report_path_strips_think_too(self):                       # L3 顺带
        text = ("<think>analyzing report...</think>\n```json\n"
                '{"status":"ok","conclusion":"通过","risks":[],'
                '"retest_suggestions":[]}\n```')
        self.assertEqual(parse_json_content(text)["status"], "ok")
```

**覆盖矩阵**：

| PRD 用例 | 测试方法 | 函数 | 路径 |
|---|---|---|---|
| A1 纯 JSON | `test_a1_pure_json_baseline` | `_parse_spec_cases` | L1 |
| A2 `<think>` 前缀 | `test_a2_think_prefix_then_pure_json` | `_parse_spec_cases` | L1 |
| A3 `<think>` + ``` 围栏 | `test_a3_think_plus_fence` | `_parse_spec_cases` | L1 |
| A4 仅 ``` 围栏 | `test_a4_fence_only_no_think` | `_parse_spec_cases` | 既有（回退保护） |
| A5 中文 | `test_a5_chinese_unicode` | `_parse_spec_cases` | 既有（回退保护） |
| A6 多 `<think>` + 内含 `{` | `test_a6_multiple_think_blocks_with_braces_inside` | `_parse_spec_cases` | L1→L2 降级 |
| A7 错误文案不泄露 | `test_a7_only_think_no_json_raises_safe_error` | `_parse_spec_cases` | L1→L2 抛错 |
| L3 报告路径 | `test_report_path_strips_think_too` | `parse_json_content` | N7 顺带 |
| 工具直测 ×2 | `test_strip_simple` / `test_strip_multiple_with_braces_inside` | `strip_think_blocks` | 单元 |

**总计 9 条方法 8 个独立输入断言**，≥ PRD 要求的 7 条。

---

## 6. 共享知识（跨函数约定）

```
[SK-01] 错误文案统一：_parse_json_fragment 抛 AIProviderError('模型输出格式异常')，
        不再回显 snippet / LLM 原始前缀（A7 强制）

[SK-02] strip_think_blocks 调用约定：必须先于 strip_markdown_fence；幂等
        （L1/L2 各调一次作防御）

[SK-03] 正则常量复用：_THINK_BLOCK_RE 模块级预编译（三入口共用），函数内不 re.compile

[SK-04] 既有签名不变：_parse_spec_cases / _parse_json_fragment /
        parse_json_content / strip_markdown_fence 对外签名（参数 / 返回 /
        @staticmethod）保持；调用方零修改

[SK-05] 错误抛出位置："model returned unexpected JSON shape" /
        "model did not return a list of cases" 保留英文（schema 不符，非
        解析失败）；仅替换 _parse_json_fragment 末尾那一处
```

---

## 7. 不做清单（与 PRD N1–N7 对齐）

| # | 不做 | 架构侧保证 |
|---|---|---|
| **N1** | 不动 prompt / `_spec_generation_payload` | T1/T2 不触这些 |
| **N2** | 不换 LLM / 不动 `payload["thinking"]` | T1 不改 `_chat_completion_payload` / `_report_analysis_payload` |
| **N3** | 不新增第三方依赖 | T1 仅 `import re`（stdlib）；T2 沿用 `unittest` |
| **N4** | 不修前端错误展示 | 文档不涉 `frontend/` |
| **N5** | 不做 schema 深度校验 | 不引 `pydantic` / `jsonschema` |
| **N6** | 不回填历史失败 | 不动 `db.py` / worker 回扫 |
| **N7** | 不动 `_chat_completion_payload` / `_report_analysis_payload` | T1 仅改 `parse_json_content`（共用解析层） |

---

## 8. 待明确事项

| # | 事项 | 建议 |
|---|---|---|
| **Q1** | `strip_think_blocks` 是否只剥首段思考块？ | 当前全局剥（re.sub）已支持 A6 极端；如未来要"只剥首段"再加 anchor |
| **Q2** | 旧 QA 断言 `model returned invalid JSON for spec cases` 会挂（R6） | 严过关同步 QA 改断言；代码层不保留兼容字符串（避免双错误文案漂移） |
| **Q3** | `parse_json_content` 两条中文错误是否也归一为"模型输出格式异常"？ | **保持现状**——报告路径专用、且本身不泄露原文，归一会让报告页日志信息量下降 |
| **Q4** | LLM 改用 `<reasoning>` 标签怎么办（R5） | 本期不预防；下期按 PRD 7.1"只扩展白名单" |
| **Q5** | `strip_think_blocks` 是否抽到独立模块？ | **不抽**——只 `ai_service.py` 内部用；若 `worker.py` 也要用再评估 |

> 工程师按 T1 → T2 顺序执行；建议 squash 为 1 个 hotfix commit。回退成本：1 个 `git revert`。
