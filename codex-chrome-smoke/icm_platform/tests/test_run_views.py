from __future__ import annotations

import unittest

from icm_platform.worker import RunnerWorker
from icm_platform.run_views import summarize_run_task
from runner.main import cases_for_batch


class RunViewTests(unittest.TestCase):
    def test_runner_batch_range_parser(self) -> None:
        self.assertEqual(cases_for_batch("TC-ICM-001..TC-ICM-003"), ["TC-ICM-001", "TC-ICM-002", "TC-ICM-003"])
        self.assertEqual(cases_for_batch("TC-ICM-006"), ["TC-ICM-006"])
        self.assertEqual(cases_for_batch("TC-ICM-002, TC-ICM-004"), ["TC-ICM-002", "TC-ICM-004"])

    def test_worker_builds_runner_args_from_settings(self) -> None:
        args = RunnerWorker()._runner_args(
            {
                "browser_mode": "background",
                "headless": True,
                "screenshot_policy": "always_archive",
                "batch_range": "TC-ICM-006..TC-ICM-011",
            }
        )

        self.assertIn("--headless", args)
        self.assertEqual(args[args.index("--screenshot-policy") + 1], "always_archive")
        self.assertEqual(args[args.index("--batch-range") + 1], "TC-ICM-006..TC-ICM-011")

    def test_worker_browser_mode_overrides_legacy_headless_flag(self) -> None:
        args = RunnerWorker()._runner_args(
            {
                "browser_mode": "visible",
                "headless": True,
                "screenshot_policy": "latest_plus_failed_archive",
                "batch_range": "TC-ICM-001..TC-ICM-012",
            }
        )

        self.assertNotIn("--headless", args)

    def test_summarizes_running_task_for_execution_center(self) -> None:
        summary = summarize_run_task(
            {
                "id": "ui-123",
                "mode": "run-case",
                "case_id": "TC-ICM-012",
                "status": "running",
                "created_at": "2026-06-05T01:00:00Z",
                "started_at": "2026-06-05T01:01:00Z",
                "finished_at": None,
                "report_path": None,
                "error": None,
            }
        )

        self.assertEqual(summary["display_name"], "TC-ICM-012")
        self.assertEqual(summary["status_label"], "Running")
        self.assertTrue(summary["is_active"])
        self.assertFalse(summary["artifact_ready"])

    def test_summarizes_finished_batch_with_report_artifact(self) -> None:
        summary = summarize_run_task(
            {
                "id": "ui-batch",
                "mode": "run-batch",
                "case_id": None,
                "status": "passed",
                "created_at": "2026-06-05T01:00:00Z",
                "started_at": "2026-06-05T01:01:00Z",
                "finished_at": "2026-06-05T01:03:05Z",
                "report_path": "reports/runs/ui-batch-tc-icm-012.md",
                "error": "",
            }
        )

        self.assertEqual(summary["display_name"], "Batch 001-012")
        self.assertEqual(summary["status_label"], "Passed")
        self.assertFalse(summary["is_active"])
        self.assertTrue(summary["artifact_ready"])
        self.assertEqual(summary["duration_label"], "02:05")


if __name__ == "__main__":
    unittest.main()
