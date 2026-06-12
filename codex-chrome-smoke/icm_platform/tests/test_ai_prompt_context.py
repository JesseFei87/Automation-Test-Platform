"""P0 / P1 · ai_service prompt 注入项目 + 上下文段单测（增量 2026-06-10）

覆盖（基线 P0/P1 验收 + T9）：
- 项目段：name / base_url / description 任一非空 → 出现「## 项目信息」
- 上下文段：env_url / test_account / excluded / refs 任一非空 → 出现「## 上下文信息」
- 空字段不污染：4 子字段全空时「## 上下文信息」整段不出现
- 全空时（无 project + 无 context_info）→ prompt 不出现「## 项目信息」「## 上下文信息」段
- 单元函数 build_project_block / build_context_info_block / build_prompt_sections
  与 AIService._case_generation_payload 拼 prompt 的行为一致

通过 mock LLM（monkey-patch _post_json）拦截网络，验证 _case_generation_payload
输出的完整 prompt JSON。
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from icm_platform.ai_service import (
    AIService,
    build_context_info_block,
    build_project_block,
    build_prompt_sections,
)


def _capture_payload(monkey_payload_box: dict):
    """构造一个 mock _post_json：把 payload 存到 box，返回固定 chat completion。

    实例方法的 mock 函数需要多接一个 self 参数（patch.object 不会自动绑定 self）。
    """
    def _fake_post_json(self, url, api_key, payload, timeout=60):  # noqa: ARG001
        monkey_payload_box["url"] = url
        monkey_payload_box["payload"] = payload
        return {
            "choices": [
                {
                    "message": {
                        "content": "id: TC-ICM-DRAFT\ntitle: mock\nstatus: draft\ntype: 功能用例\npreconditions:\n  - mock\nsteps:\n  - mock step\nexpected_results:\n  - mock assert\nautomation_asset:\n  operation_steps: []\n  selectors: []\n  input_values: {}\n  assertions: []\n",
                    }
                }
            ]
        }
    return _fake_post_json


def _user_content(payload: dict) -> str:
    return payload["messages"][1]["content"]


class PromptSectionBuildersTests(unittest.TestCase):
    """build_project_block / build_context_info_block / build_prompt_sections 单元函数。"""

    # ---- project block ----

    def test_project_block_none_when_no_input(self):
        self.assertIsNone(build_project_block(None))
        self.assertIsNone(build_project_block({}))
        self.assertIsNone(build_project_block({"name": "  ", "base_url": None}))

    def test_project_block_emits_name_and_base_url(self):
        block = build_project_block(
            {"name": "ICM", "base_url": "https://icm.example.com", "description": "  "}
        )
        self.assertIsNotNone(block)
        self.assertEqual(block["title"], "项目信息")
        keys = [k for k, _ in block["rows"]]
        self.assertIn("Name", keys)
        self.assertIn("Base URL", keys)
        self.assertNotIn("Description", keys)

    def test_project_block_emits_description_when_present(self):
        block = build_project_block(
            {"name": "ICM", "base_url": "https://icm.example.com", "description": "test desc"}
        )
        keys = [k for k, _ in block["rows"]]
        self.assertIn("Description", keys)

    # ---- context_info block ----

    def test_context_block_none_when_all_empty(self):
        self.assertIsNone(build_context_info_block(None))
        self.assertIsNone(build_context_info_block({}))
        self.assertIsNone(
            build_context_info_block(
                {"env_url": "", "test_account": "  ", "excluded": None, "refs": ""}
            )
        )

    def test_context_block_emits_only_filled_rows(self):
        block = build_context_info_block(
            {
                "env_url": "https://stg.example.com",
                "test_account": "",
                "excluded": "登录页",
                "refs": "  ",
            }
        )
        self.assertIsNotNone(block)
        self.assertEqual(block["title"], "上下文信息")
        keys = [k for k, _ in block["rows"]]
        self.assertIn("环境URL", keys)
        self.assertIn("排除范围", keys)
        self.assertNotIn("测试账号", keys)
        self.assertNotIn("参考文档", keys)

    def test_context_block_emits_all_four(self):
        block = build_context_info_block(
            {
                "env_url": "https://stg",
                "test_account": "tester/123",
                "excluded": "登录",
                "refs": "https://wiki/ref",
            }
        )
        keys = [k for k, _ in block["rows"]]
        self.assertEqual(
            keys,
            ["环境URL", "测试账号", "排除范围", "参考文档"],
        )

    # ---- build_prompt_sections 分段函数 ----

    def test_sections_skip_empty_blocks(self):
        sections = build_prompt_sections(
            [
                None,
                {},
                {"title": "项目信息", "rows": []},
                {"title": "上下文信息", "rows": [("k", "  ")]},
            ]
        )
        self.assertEqual(sections, [])

    def test_sections_keeps_only_non_empty(self):
        sections = build_prompt_sections(
            [
                build_project_block({"name": "ICM", "base_url": "https://x"}),
                build_context_info_block({"env_url": "https://y"}),
                None,
            ]
        )
        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0]["title"], "项目信息")
        self.assertEqual(sections[1]["title"], "上下文信息")
        # 项目段 rows 含 "Name: ICM"（渲染为 "K: V"）
        project_rows = sections[0]["rows"]
        self.assertTrue(any("Name: ICM" in r for r in project_rows))
        self.assertTrue(any("Base URL: https://x" in r for r in project_rows))
        # 上下文段 rows 含 "环境URL: https://y"
        context_rows = sections[1]["rows"]
        self.assertTrue(any("环境URL: https://y" in r for r in context_rows))


class PromptInjectionTests(unittest.TestCase):
    """通过 mock LLM 调 generate_cases_with_ai 验证 prompt 包含 / 不包含期望段。"""

    def _settings(self) -> dict:
        return {
            "provider": "minimax-m3",
            "base_url": "http://127.0.0.1:9",
            "model": "MiniMax-M3",
            "api_key": "test-key",
        }

    def _run(self, project, context_info) -> dict:
        """调一次 generate_cases_with_ai，捕获 payload 后返回。"""
        captured: dict = {}
        service = AIService()
        with patch.object(AIService, "_post_json", _capture_payload(captured)):
            service.generate_cases_with_ai(
                test_points=[{"name": "T1", "category": "功能", "priority": "P1", "status": "待确认", "description": ""}],
                template="functional",
                title="mock",
                settings=self._settings(),
                project=project,
                context_info=context_info,
            )
        return captured["payload"]

    # ---- 项目段 ----

    def test_prompt_includes_project_section_when_project_has_data(self):
        payload = self._run(
            project={"name": "ICM", "base_url": "https://icm.example.com", "description": ""},
            context_info=None,
        )
        content = _user_content(payload)
        data = json.loads(content)
        sections = data.get("prompt_sections") or []
        titles = [s["title"] for s in sections]
        self.assertIn("项目信息", titles)
        rows = next(s for s in sections if s["title"] == "项目信息")["rows"]
        self.assertTrue(any("Name: ICM" in r for r in rows))
        self.assertTrue(any("Base URL: https://icm.example.com" in r for r in rows))
        # description 为空 → 不出现
        self.assertFalse(any("Description" in r for r in rows))

    def test_prompt_excludes_project_section_when_project_all_empty(self):
        payload = self._run(project={}, context_info=None)
        content = _user_content(payload)
        data = json.loads(content)
        sections = data.get("prompt_sections") or []
        titles = [s["title"] for s in sections]
        self.assertNotIn("项目信息", titles)

    def test_prompt_excludes_project_section_when_project_is_none(self):
        payload = self._run(project=None, context_info=None)
        content = _user_content(payload)
        data = json.loads(content)
        sections = data.get("prompt_sections") or []
        self.assertNotIn("项目信息", [s["title"] for s in sections])

    # ---- 上下文段 ----

    def test_prompt_includes_context_section_when_some_filled(self):
        payload = self._run(
            project=None,
            context_info={
                "env_url": "https://stg.example.com",
                "test_account": "",
                "excluded": "登录页",
                "refs": "",
            },
        )
        content = _user_content(payload)
        data = json.loads(content)
        sections = data.get("prompt_sections") or []
        titles = [s["title"] for s in sections]
        self.assertIn("上下文信息", titles)
        rows = next(s for s in sections if s["title"] == "上下文信息")["rows"]
        self.assertTrue(any("环境URL: https://stg.example.com" in r for r in rows))
        self.assertTrue(any("排除范围: 登录页" in r for r in rows))
        # 空字段不污染
        self.assertFalse(any("测试账号" in r for r in rows))
        self.assertFalse(any("参考文档" in r for r in rows))

    def test_prompt_excludes_context_section_when_all_blank(self):
        payload = self._run(
            project=None,
            context_info={
                "env_url": "",
                "test_account": "   ",
                "excluded": None,
                "refs": "",
            },
        )
        content = _user_content(payload)
        data = json.loads(content)
        sections = data.get("prompt_sections") or []
        self.assertNotIn("上下文信息", [s["title"] for s in sections])

    def test_prompt_excludes_context_section_when_none(self):
        payload = self._run(project=None, context_info=None)
        content = _user_content(payload)
        data = json.loads(content)
        sections = data.get("prompt_sections") or []
        self.assertNotIn("上下文信息", [s["title"] for s in sections])

    # ---- 全空时整段不污染 ----

    def test_prompt_no_sections_when_both_empty(self):
        """全空时 prompt 里完全不出现 '项目信息' / '上下文信息' 段。"""
        payload = self._run(project={}, context_info={})
        content = _user_content(payload)
        data = json.loads(content)
        # prompt_sections 字段要么缺失要么为空
        self.assertFalse(data.get("prompt_sections"))
        # 同时确认 raw JSON 字符串中也不含标题
        self.assertNotIn("项目信息", content)
        self.assertNotIn("上下文信息", content)

    # ---- _last_prompt 调试钩子 ----

    def test_last_prompt_attribute_exposed_for_debug(self):
        captured: dict = {}
        service = AIService()
        with patch.object(AIService, "_post_json", _capture_payload(captured)):
            service.generate_cases_with_ai(
                test_points=[{"name": "T1", "category": "功能", "priority": "P1", "status": "待确认", "description": ""}],
                template="functional",
                title="mock",
                settings=self._settings(),
                project={"name": "ICM", "base_url": "https://icm.example.com", "description": ""},
                context_info={"env_url": "https://stg", "test_account": "", "excluded": "", "refs": ""},
            )
        # 基线 P0 验收："可通过 ai_service._last_prompt 调试看到"
        self.assertTrue(getattr(service, "_last_prompt", ""))
        self.assertIn("项目信息", service._last_prompt)
        self.assertIn("上下文信息", service._last_prompt)


if __name__ == "__main__":
    unittest.main()
