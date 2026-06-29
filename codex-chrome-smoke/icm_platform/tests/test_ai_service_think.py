"""P0 · ai_service 兼容 <think> 标签的解析层单测（hotfix 2026-06-10）

覆盖（PRD 5.1 全部 7 条 + L3 报告路径顺带 1 条 + 工具直测 2 条 = 9 条）：
- A1 纯 JSON 基线（既有路径，确保不回退）
- A2 <think> 前缀 + 纯 JSON（核心修复）
- A3 <think> + ```json 围栏 + JSON（真实复现路径）
- A4 仅 ```json 围栏（既有路径，不回退）
- A5 中文 unicode 字段
- A6 多 <think> 块 + 块内含 { 字符（极端）
- A7 仅 <think> 无 JSON → 错误文案"模型输出格式异常"，不泄露原文
- L3 parse_json_content 报告分析路径：同样剥 <think>
- 工具函数 strip_think_blocks 直测 2 条
"""
from __future__ import annotations

import unittest

from icm_platform.ai_service import (
    AIService,
    AIProviderError,
    _json_fragments,
    parse_json_content,
    strip_think_blocks,
)


class TestStripThinkBlocks(unittest.TestCase):
    def test_strip_simple(self):
        self.assertEqual(strip_think_blocks("<think>hello</think>{}"), "{}")

    def test_strip_multiple_with_braces_inside(self):
        text = ('<think>a {"b":"c"} first</think>middle'
                '<think>second with {"x":1} inside</think>{"x":1}')
        self.assertEqual(strip_think_blocks(text), 'middle{"x":1}')


class TestJsonFragments(unittest.TestCase):
    def test_extracts_complete_json_when_schema_text_contains_braces(self):
        text = 'schema {"id":"DEMO"} ignored\n{"cases":[{"id":"CASE_001"}]}\ntrailing {note}'
        self.assertIn('{"cases":[{"id":"CASE_001"}]}', _json_fragments(text))


class TestParseSpecCases(unittest.TestCase):
    def test_a1_pure_json_baseline(self):
        # A1 基线：纯 JSON 输入，修复后必须仍能处理（不回退）
        out = AIService._parse_spec_cases(
            '{"cases":[{"id":"BAIDU_FUN_001","title":"访问百度"}]}')
        self.assertEqual(out, [{"id": "BAIDU_FUN_001", "title": "访问百度"}])

    def test_a2_think_prefix_then_pure_json(self):
        # A2 核心修复：<think> 块 + 紧跟纯 JSON，剥除后必须能解析
        text = "<think>The user wants simple test cases.</think>" + \
               '{"cases":[{"id":"BAIDU_FUN_001"}]}'
        self.assertEqual(AIService._parse_spec_cases(text),
                         [{"id": "BAIDU_FUN_001"}])

    def test_a3_think_plus_fence(self):
        # A3 真实复现路径：<think> + ```json 围栏 + JSON
        text = "<think>...thinking content...</think>\n```json\n" + \
               '{"cases":[{"id":"BAIDU_FUN_001"}]}\n```'
        self.assertEqual(AIService._parse_spec_cases(text),
                         [{"id": "BAIDU_FUN_001"}])

    def test_a4_fence_only_no_think(self):
        # A4 既有路径（仅 ```json 围栏，无 <think>），修复后行为不变
        text = "```json\n" + '{"cases":[{"id":"BAIDU_FUN_001"}]}\n```'
        self.assertEqual(AIService._parse_spec_cases(text),
                         [{"id": "BAIDU_FUN_001"}])

    def test_a5_chinese_unicode(self):
        # A5 中文 unicode 路径：json.loads 行为未变
        text = ('{"cases":[{"id":"BAIDU_FUN_001",'
                '"title":"访问百度首页搜索123",'
                '"steps":["1. 打开百度","2. 输入123","3. 点击搜索"]}]}')
        out = AIService._parse_spec_cases(text)
        self.assertEqual(out[0]["title"], "访问百度首页搜索123")
        self.assertEqual(len(out[0]["steps"]), 3)

    def test_a6_multiple_think_blocks_with_braces_inside(self):
        # A6 极端：多个 <think> 块 + 块内含 { 字符 + 中间散文
        text = ("<think>first thought</think>一些散文"
                '<think>second that is long and crosses lines and '
                'contains some {"json": "like text"} inside</think>'
                '{"cases":[]}')
        self.assertEqual(AIService._parse_spec_cases(text), [])

    def test_a7_only_think_no_json_raises_safe_error(self):
        # A7 仅 <think> 无 JSON：抛 AIProviderError("模型输出格式异常")，不泄露原文
        with self.assertRaises(AIProviderError) as ctx:
            AIService._parse_spec_cases(
                "<think>I cannot generate cases for this request.</think>")
        self.assertIn("模型输出格式异常", str(ctx.exception))
        self.assertNotIn("<think>", str(ctx.exception))
        self.assertNotIn("cannot generate", str(ctx.exception))


class TestParseJsonContentReportPath(unittest.TestCase):
    def test_report_path_strips_think_too(self):
        # L3 顺带：报告分析路径 parse_json_content 同样剥 <think>
        text = ("<think>analyzing report...</think>\n```json\n"
                '{"status":"ok","conclusion":"通过","risks":[],'
                '"retest_suggestions":[]}\n```')
        self.assertEqual(parse_json_content(text)["status"], "ok")


if __name__ == "__main__":
    unittest.main()
