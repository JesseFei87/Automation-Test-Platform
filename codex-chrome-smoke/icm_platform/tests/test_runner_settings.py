from __future__ import annotations

import unittest

from icm_platform.db import normalize_runner_settings
from icm_platform.worker import RunnerWorker


class RunnerSettingsTests(unittest.TestCase):
    def test_normalize_runner_settings_clamps_playwright_options(self) -> None:
        settings = normalize_runner_settings({
            "browser_mode": "visible",
            "viewport_mode": "window",
            "viewport_width": 1,
            "viewport_height": 99999,
            "maximize_window": 1,
            "ignore_https_errors": 0,
        })

        self.assertEqual(settings["viewport_mode"], "window")
        self.assertEqual(settings["viewport_width"], 320)
        self.assertEqual(settings["viewport_height"], 4320)
        self.assertTrue(settings["maximize_window"])
        self.assertFalse(settings["ignore_https_errors"])
        self.assertFalse(settings["headless"])

    def test_worker_passes_playwright_options_to_runner(self) -> None:
        args = RunnerWorker()._runner_args({
            "browser_mode": "visible",
            "viewport_mode": "window",
            "viewport_width": 1920,
            "viewport_height": 1080,
            "maximize_window": True,
            "ignore_https_errors": True,
        })

        self.assertIn("--maximize-window", args)
        self.assertIn("--ignore-https-errors", args)
        self.assertEqual(args[args.index("--viewport-mode") + 1], "window")
        self.assertEqual(args[args.index("--viewport-width") + 1], "1920")
        self.assertEqual(args[args.index("--viewport-height") + 1], "1080")


if __name__ == "__main__":
    unittest.main()
