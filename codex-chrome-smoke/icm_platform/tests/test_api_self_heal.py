from __future__ import annotations

import unittest
from unittest.mock import patch

from icm_platform.api import (
    _build_self_heal_context,
    _classify_self_heal_failure,
    _self_heal_hint,
)


class ClassifySelfHealFailureTests(unittest.TestCase):
    def test_unknown_ref_maps_to_locator_drift(self) -> None:
        result = _classify_self_heal_failure({"error": "unknown ref: empty", "history": []}, [])
        self.assertEqual(result["category"], "locator_drift")
        self.assertEqual(result["evidence"], "unknown ref: empty")

    def test_no_assertion_signal_maps_to_locator_drift(self) -> None:
        result = _classify_self_heal_failure({"error": "no assertion signal matched on current page", "history": []}, [])
        self.assertEqual(result["category"], "locator_drift")

    def test_login_keyword_maps_to_logic_understanding(self) -> None:
        result = _classify_self_heal_failure({"error": "login failed", "history": []}, [])
        self.assertEqual(result["category"], "logic_understanding")

    def test_credential_keyword_maps_to_logic_understanding(self) -> None:
        result = _classify_self_heal_failure({"error": "invalid credential", "history": []}, [])
        self.assertEqual(result["category"], "logic_understanding")

    def test_timeout_maps_to_timing(self) -> None:
        result = _classify_self_heal_failure({"error": "timeout waiting for selector", "history": []}, [])
        self.assertEqual(result["category"], "timing")

    def test_timed_out_maps_to_timing(self) -> None:
        result = _classify_self_heal_failure({"error": "action timed out", "history": []}, [])
        self.assertEqual(result["category"], "timing")

    def test_agent_action_failed_maps_to_unrecoverable(self) -> None:
        result = _classify_self_heal_failure({"error": "agent_action_failed: click", "history": []}, [])
        self.assertEqual(result["category"], "unrecoverable")

    def test_unknown_error_maps_to_unknown(self) -> None:
        result = _classify_self_heal_failure({"error": "some random failure", "history": []}, [])
        self.assertEqual(result["category"], "unknown")

    def test_empty_error_falls_back_to_last_history(self) -> None:
        trace = {
            "error": "",
            "history": [
                {"step": 1, "decision": {"action": "click"}, "execution": {"result": "ok"}},
                {"step": 2, "decision": {"action": "assert"}, "execution": {"error": "unknown ref: x"}},
            ],
        }
        result = _classify_self_heal_failure(trace, [])
        self.assertEqual(result["category"], "locator_drift")
        self.assertEqual(result["evidence"], "unknown ref: x")


class SelfHealHintTests(unittest.TestCase):
    def test_hint_contains_diagnosis_recovery_and_stop_sections(self) -> None:
        hint = _self_heal_hint({"error": "unknown ref: empty", "history": []}, [])
        self.assertIn("失败诊断：", hint)
        self.assertIn("- Category: locator_drift", hint)
        self.assertIn("- 证据: unknown ref: empty", hint)
        self.assertIn("恢复策略（按 Category 选一条）：", hint)
        self.assertIn("locator_drift（定位漂移）：重新观察页面", hint)
        self.assertIn("timing（时序问题）：等待 1-3 秒", hint)
        self.assertIn("logic_understanding（业务理解偏差）：重读用例步骤", hint)
        self.assertIn("unrecoverable（不可恢复）：不要重试", hint)
        self.assertIn("停止条件（任一命中立刻 finish）：", hint)
        self.assertIn("已是第 3 次重试。", hint)
        self.assertIn("visibleText 已包含任意一条 Expected results。", hint)
        self.assertIn("失败信号与上一轮 Category 相同。", hint)

    def test_hint_uses_login_category_for_login_error(self) -> None:
        hint = _self_heal_hint({"error": "login failed", "history": []}, [])
        self.assertIn("- Category: logic_understanding", hint)
        self.assertIn("- 证据: login failed", hint)

    def test_hint_handles_empty_evidence_gracefully(self) -> None:
        hint = _self_heal_hint({"error": "", "history": []}, [])
        self.assertIn("- Category: unknown", hint)
        self.assertIn("- 证据: (no explicit error captured)", hint)


class BuildSelfHealContextTests(unittest.TestCase):
    def test_context_includes_diagnosis_and_budget(self) -> None:
        with patch("icm_platform.api.evidence_summary", return_value={"events": {"latest": []}}):
            ctx = _build_self_heal_context(
                "parent-123",
                {"error": ""},
                {"error": "no assertion signal matched", "history": [{"step": 1, "execution": {"error": "x"}}]},
            )
        self.assertEqual(ctx["parent_run_id"], "parent-123")
        self.assertEqual(ctx["trigger"], "self_heal")
        self.assertEqual(ctx["attempt_index"], 1)
        self.assertEqual(ctx["max_attempts"], 3)
        self.assertEqual(ctx["diagnosis"]["category"], "locator_drift")
        self.assertIn("no assertion signal matched", ctx["diagnosis"]["evidence"])
        self.assertIn("失败诊断：", ctx["healing_hint"])
        self.assertEqual(len(ctx["last_history"]), 1)

    def test_context_propagates_unknown_category_when_no_signal(self) -> None:
        with patch("icm_platform.api.evidence_summary", return_value={"events": {"latest": []}}):
            ctx = _build_self_heal_context(
                "parent-456",
                {"error": ""},
                {"error": "totally opaque failure", "history": []},
            )
        self.assertEqual(ctx["diagnosis"]["category"], "unknown")
        self.assertIn("totally opaque failure", ctx["diagnosis"]["evidence"])
