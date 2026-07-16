from __future__ import annotations

import sqlite3
import unittest

import yaml

from icm_platform.recorder import RecorderError, append_action, create_session, list_events, stop_session


class RecorderServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.session = create_session(
            self.conn,
            start_url="https://qa.example.test/login",
            allowed_origins=["https://qa.example.test"],
        )

    def tearDown(self):
        self.conn.close()

    def test_session_requires_start_origin_to_be_explicitly_allowlisted(self):
        with self.assertRaisesRegex(RecorderError, "allowlisted"):
            create_session(
                self.conn,
                start_url="https://qa.example.test/login",
                allowed_origins=["https://other.example.test"],
            )

    def test_action_prefers_stable_locator_and_redacts_sensitive_value(self):
        event = append_action(
            self.conn,
            self.session["id"],
            {
                "type": "fill",
                "name": "password",
                "value": "do-not-store-this",
                "locator_candidates": [
                    {"strategy": "css", "value": "#login > input:nth-child(2)", "unique": True},
                    {"strategy": "testid", "value": "login-password", "unique": True},
                ],
            },
        )
        self.assertEqual(event["action"]["selector"]["strategy"], "testid")
        self.assertEqual(event["action"]["value"], "${SECRET}")
        self.assertTrue(event["action"]["redacted"])

    def test_unstable_or_non_unique_locator_requires_review(self):
        event = append_action(
            self.conn,
            self.session["id"],
            {
                "type": "click",
                "locator_candidates": [{"strategy": "css", "value": "#root > button:nth-child(1)", "unique": True}],
            },
        )
        self.assertFalse(event["action"]["publishable"])
        self.assertTrue(event["action"]["review_required"])
        self.assertIn("nth-child", event["action"]["selector"]["reason"])

    def test_rejects_navigation_outside_allowlist_and_unconfirmed_download(self):
        with self.assertRaisesRegex(RecorderError, "not allowlisted"):
            append_action(self.conn, self.session["id"], {"type": "navigate", "url": "https://evil.example.test/"})
        with self.assertRaisesRegex(RecorderError, "requires explicit confirmation"):
            append_action(
                self.conn,
                self.session["id"],
                {"type": "download", "locator_candidates": [{"strategy": "text", "value": "Export", "unique": True}]},
            )

    def test_stop_generates_reviewable_dsl_and_python_candidate(self):
        append_action(self.conn, self.session["id"], {"type": "navigate", "url": "https://qa.example.test/login"})
        append_action(
            self.conn,
            self.session["id"],
            {"type": "fill", "value": "qa", "locator_candidates": [{"strategy": "label", "value": "Username", "unique": True}]},
        )
        append_action(
            self.conn,
            self.session["id"],
            {"type": "click", "locator_candidates": [{"strategy": "role", "value": "button:Login", "unique": True}]},
        )

        result = stop_session(self.conn, self.session["id"])

        self.assertEqual(result["status"], "stopped")
        self.assertEqual([event["sequence"] for event in result["events"]], [1, 2, 3])
        self.assertTrue(result["dsl"]["publishable"])
        self.assertTrue(result["dsl"]["requires_review"])
        self.assertEqual(yaml.safe_load(result["candidate_yaml"])["source"], "recorder")
        self.assertIn("await page.goto", result["candidate_python"])
        self.assertIn("get_by_label('Username')", result["candidate_python"])
        self.assertIn("get_by_role('button:Login')", result["candidate_python"])
        self.assertEqual(len(list_events(self.conn, self.session["id"])), 3)

    def test_stopped_session_cannot_accept_more_actions(self):
        stop_session(self.conn, self.session["id"])
        with self.assertRaisesRegex(RecorderError, "not active"):
            append_action(
                self.conn,
                self.session["id"],
                {"type": "click", "locator_candidates": [{"strategy": "text", "value": "Start", "unique": True}]},
            )


if __name__ == "__main__":
    unittest.main()
