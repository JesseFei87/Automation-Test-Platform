from __future__ import annotations

import unittest

from icm_platform.recorder_locator_recovery import LocatorCandidate, choose_recovered_locator


def valid(strategy: str = "css", value: str = ".message-drawer > .message-icon-wrapper") -> LocatorCandidate:
    return LocatorCandidate(
        strategy=strategy,
        value=value,
        unique=True,
        visible=True,
        enabled=True,
        covers_click_point=True,
        trial_clickable=True,
    )


class RecorderLocatorRecoveryTests(unittest.TestCase):
    def test_returns_browser_validated_candidate_and_marks_ai_origin(self) -> None:
        decision = choose_recovered_locator([valid()])

        self.assertIsNone(decision.reason)
        self.assertEqual(decision.candidate.as_recorder_candidate()["recovered_by"], "ai")

    def test_score_can_reorder_candidates_but_cannot_bypass_validation(self) -> None:
        rejected = valid(value=".message-icon-wrapper:nth-child(2)")
        accepted = valid(value="//div[@class='message-drawer']/div[@tabindex='0']", strategy="xpath")
        decision = choose_recovered_locator([accepted, rejected], score=lambda items: reversed(items))

        self.assertEqual(decision.candidate, accepted)

    def test_rejects_generated_tooltip_scope_and_embedded_image_selectors(self) -> None:
        for selector in (
            "div[data-v-0ca9477f]",
            ".el-tooltip-7095",
            "img[src='data:image/png;base64,abc']",
            "//div[2]",
        ):
            with self.subTest(selector=selector):
                decision = choose_recovered_locator([valid(value=selector)])
                self.assertIsNone(decision.candidate)
                self.assertIn("fragile", decision.reason)

    def test_requires_unique_visible_enabled_click_point_and_trial_click(self) -> None:
        for field in ("unique", "visible", "enabled", "covers_click_point", "trial_clickable"):
            with self.subTest(field=field):
                values = valid().__dict__.copy()
                values[field] = False
                decision = choose_recovered_locator([LocatorCandidate(**values)])
                self.assertIsNone(decision.candidate)
                self.assertIsNotNone(decision.reason)

    def test_rejects_non_css_xpath_and_empty_ai_output(self) -> None:
        decision = choose_recovered_locator([valid(strategy="text")])
        self.assertIsNone(decision.candidate)
        self.assertIn("CSS or XPath", decision.reason)
        self.assertIsNone(choose_recovered_locator([]).candidate)


if __name__ == "__main__":
    unittest.main()
