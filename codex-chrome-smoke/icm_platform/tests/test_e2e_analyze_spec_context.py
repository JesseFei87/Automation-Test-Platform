"""QA2 回归 · 端到端测试（增量 2026-06-10）

覆盖（基线 P0-6 / P1-2 / P1-3 端到端）：
- 通过 HTTP `POST /api/requirements/analyze-spec` 传 `project_id` + `context_info`
- 验证 LLM 收到的 prompt 同时含「项目信息」段（"Base URL: ..."）和「上下文信息」段（"环境URL: ..."）
- 验证落库的 `case_drafts.yaml` 顶层含 `context_info:` 键

区别于 `test_ai_prompt_context.py`（单测，仅调 `generate_cases_with_ai`）：
- 本测试走 HTTP 端点 `analyze_requirement_spec`，验证工程师在 §3 标的 3 端到端问题已修复
- 验证链路：HTTP body → `RequirementRequest` 校验 → `get_project_profile` → `generate_test_cases_spec(project=, context_info=)` → LLM payload
- 验证 `case_drafts.yaml` 持久化链路
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from icm_platform import db
from icm_platform.ai_service import AIService


def _try_import_app():
    try:
        from icm_platform.api import app
        return app
    except Exception:  # noqa: BLE001
        return None


def _try_import_testclient():
    try:
        from fastapi.testclient import TestClient
        return TestClient
    except Exception:  # noqa: BLE001
        return None


_client_app = _try_import_app()
_test_client_cls = _try_import_testclient()


_LLM_FAKE_CASES = {
    "cases": [
        {
            "id": "LOGIN_FUN_001",
            "title": "登录成功",
            "module": "登录",
            "priority": "P0",
            "type": "功能",
            "precondition": "env, data, account, config",
            "test_data": "user=admin",
            "steps": ["1. 打开登录页", "2. 输账号密码"],
            "expected": ["1. 跳首页"],
            "requirement_id": "REQ-001",
            "automation": "Yes",
            "author": "AI",
            "date": "2026-06-10",
            "note": "",
        }
    ]
}


def _make_fake_post_json(captured: dict):
    """构造 AIService._post_json 的 mock：捕获 payload，返回合法 chat completion。

    实例方法 mock 需要多接一个 self 参数（patch.object 不会自动绑定 self）。
    """
    def _fake(self, url, api_key, payload, timeout=60):  # noqa: ARG001
        captured["url"] = url
        captured["payload"] = payload
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_LLM_FAKE_CASES, ensure_ascii=False),
                    }
                }
            ]
        }
    return _fake


def _extract_user_content(payload: dict) -> dict:
    """从 LLM payload 里取出 user 消息里的 JSON 文本内容（prompt_sections 所在层）。"""
    messages = payload.get("messages") or []
    user_msg = next((m for m in messages if m.get("role") == "user"), None)
    if user_msg is None:
        raise AssertionError("LLM payload 缺 user message")
    return json.loads(user_msg["content"])


def _find_section(sections: list, title: str) -> dict | None:
    for sec in sections or []:
        if sec.get("title") == title:
            return sec
    return None


@unittest.skipIf(
    _client_app is None or _test_client_cls is None,
    "FastAPI 端点 / httpx 依赖未安装，跳过端到端测试",
)
class AnalyzeSpecE2ETests(unittest.TestCase):
    """端到端：HTTP → analyze_requirement_spec → LLM payload + 落库 case_drafts.yaml。"""

    def setUp(self):
        self.world = tempfile.mkdtemp()
        self.root = Path(self.world)
        self.db_path = self.root / "test.sqlite3"
        self._patchers = [
            patch("icm_platform.db.DB_PATH", self.db_path),
            patch("icm_platform.db.DATA_DIR", self.root),
        ]
        for p in self._patchers:
            p.start()
        db.init_db()
        # 拿种子 ICM 的 id（与 ARCH §3.1 一致）
        self.icm = next(
            p for p in db.list_project_profiles() if p["name"] == "ICM"
        )
        from icm_platform import api as api_module
        self.api = api_module
        self.client = _test_client_cls(api_module.app)
        # 临时 DB 没种子 ai_settings；patch api.get_ai_settings 绕开"请先保存 API Key"前置
        self._fake_settings = {
            "provider": "minimax-m3",
            "base_url": "http://127.0.0.1:9",
            "model": "MiniMax-M3",
            "api_key": "test-key",
        }
        self._settings_patcher = patch.object(
            api_module, "get_ai_settings", return_value=self._fake_settings
        )
        self._settings_patcher.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._settings_patcher.stop()
        shutil.rmtree(self.world, ignore_errors=True)

    # ---- 端到端 #1：项目 + 上下文双注入 LLM prompt（覆盖 P0-6 + P1-3 端到端） ----

    def test_e2e_project_and_context_both_injected_into_llm_prompt(self):
        """POST /api/requirements/analyze-spec 同时传项目与业务前置条件，
        断言 LLM 收到的 user prompt 文本同时含 'Base URL: https://icm.example.com' 和
        '环境URL: https://staging'。"""
        captured: dict = {}
        with patch.object(AIService, "_post_json", _make_fake_post_json(captured)):
            resp = self.client.post(
                "/api/requirements/analyze-spec",
                json={
                    "title": "登录页冒烟",
                    "document": "需求：登录页 + 退出。",
                    "project_id": self.icm["id"],
                    "context_info": {
                        "business_preconditions": "使用管理员角色",
                        "excluded": "",
                    },
                },
            )
        # 端点本身要 200
        self.assertEqual(resp.status_code, 200, resp.text)
        # 拦截到 LLM 调用
        self.assertIn("payload", captured, "_post_json 未被调用")
        # 把 payload 序列化成 JSON 字符串（端到端证据级别：raw LLM body）
        prompt_json_str = json.dumps(captured["payload"], ensure_ascii=False)
        # P0-6 端到端：项目段含 Base URL
        self.assertIn("项目信息", prompt_json_str)
        self.assertIn("Base URL: https://icm.example.com", prompt_json_str)
        # P1-3 端到端：上下文段含业务前置条件
        self.assertIn("上下文信息", prompt_json_str)
        self.assertIn("业务前置条件: 使用管理员角色", prompt_json_str)
        # 空字段不污染
        self.assertNotIn("测试账号", prompt_json_str)
        self.assertNotIn("排除范围", prompt_json_str)
        self.assertNotIn("参考文档", prompt_json_str)

    def test_e2e_prompt_sections_both_present_in_user_content(self):
        """更结构化的断言：把 user message content 解析回 dict，校验 sections 结构。"""
        captured: dict = {}
        with patch.object(AIService, "_post_json", _make_fake_post_json(captured)):
            resp = self.client.post(
                "/api/requirements/analyze-spec",
                json={
                    "title": "登录页冒烟",
                    "document": "需求：登录页 + 退出。",
                    "project_id": self.icm["id"],
                    "context_info": {
                        "business_preconditions": "已准备待审核数据",
                        "excluded": "",
                    },
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = _extract_user_content(captured["payload"])
        sections = data.get("prompt_sections") or []
        titles = [s["title"] for s in sections]
        # 两段都出现，且顺序：项目 → 上下文
        self.assertIn("项目信息", titles)
        self.assertIn("上下文信息", titles)
        self.assertLess(titles.index("项目信息"), titles.index("上下文信息"))

        proj = _find_section(sections, "项目信息")
        ctx = _find_section(sections, "上下文信息")
        self.assertIsNotNone(proj)
        self.assertIsNotNone(ctx)

        proj_rows = proj["rows"]
        self.assertTrue(any("Name: ICM" in r for r in proj_rows))
        self.assertTrue(any("Base URL: https://icm.example.com" in r for r in proj_rows))

        ctx_rows = ctx["rows"]
        self.assertTrue(any("业务前置条件: 已准备待审核数据" in r for r in ctx_rows))
        # 留空字段不出现
        self.assertFalse(any("排除范围" in r for r in ctx_rows))
        self.assertFalse(any("参考文档" in r for r in ctx_rows))

    # ---- 端到端 #2：context_info 持久化到 case_drafts.yaml 顶层（覆盖 P1-2 端到端） ----

    def test_e2e_context_info_persisted_to_case_drafts_yaml_top_level(self):
        """POST /api/requirements/analyze-spec 传精简后的 context_info，
        断言写出的 case_drafts.yaml 顶层含 context_info 键。"""
        ctx = {
            "business_preconditions": "已准备待审核数据",
            "excluded": "登录页",
        }
        captured: dict = {}
        with patch.object(AIService, "_post_json", _make_fake_post_json(captured)):
            resp = self.client.post(
                "/api/requirements/analyze-spec",
                json={
                    "title": "登录页冒烟",
                    "document": "需求：登录页 + 退出。",
                    "project_id": None,
                    "context_info": ctx,
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        drafts = body.get("drafts") or []
        self.assertEqual(len(drafts), 1, "应生成 1 条 spec 草稿")
        draft_id = drafts[0]["id"]
        # 从 DB 读 yaml
        with db.connect() as conn:
            row = conn.execute(
                "select yaml from case_drafts where id = ?", (draft_id,)
            ).fetchone()
        self.assertIsNotNone(row, f"case_drafts id={draft_id} 未落库")
        yaml_text = row["yaml"]
        parsed = yaml.safe_load(yaml_text)
        # 顶层必须含 context_info 键
        self.assertIn("context_info", parsed, f"yaml 顶层缺 context_info:\n{yaml_text}")
        self.assertEqual(parsed["context_info"], ctx)

    def test_empty_or_deprecated_context_is_not_persisted(self):
        with patch.object(AIService, "_post_json", _make_fake_post_json({})):
            resp = self.client.post(
                "/api/requirements/analyze-spec",
                json={
                    "title": "登录页冒烟",
                    "document": "需求：登录页。",
                    "project_id": self.icm["id"],
                    "context_info": {"business_preconditions": " ", "excluded": "", "test_account": "qa/secret"},
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        draft_id = resp.json()["drafts"][0]["id"]
        with db.connect() as conn:
            yaml_text = conn.execute("select yaml from case_drafts where id = ?", (draft_id,)).fetchone()["yaml"]

        self.assertNotIn("context_info", yaml.safe_load(yaml_text))
        self.assertNotIn("secret", yaml_text)


if __name__ == "__main__":
    unittest.main()
