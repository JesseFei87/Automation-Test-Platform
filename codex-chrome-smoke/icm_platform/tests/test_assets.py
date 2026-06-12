from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi import HTTPException

from icm_platform import db
from icm_platform.db import get_platform_settings, save_platform_settings
from icm_platform.api import merge_run_observed_asset
from icm_platform.assets import list_batch_child_reports


class AssetTests(unittest.TestCase):
    def test_platform_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "test.sqlite3"
            with patch("icm_platform.db.DB_PATH", db_path), patch("icm_platform.db.DATA_DIR", db_path.parent):
                db.init_db()
                saved = save_platform_settings(
                    {
                        "runner": {"browser_mode": "visible", "headless": True},
                        "asset_policy": {"observed_asset_enabled": False},
                        "environment": {"icm_base_url": "https://icm.example.test"},
                        "accounts": {"labo": {"username": "labo2", "password": "secret-one"}},
                    }
                )
                save_platform_settings({"accounts": {"labo": {"username": "labo3", "password": ""}}})
                loaded = get_platform_settings()
                raw = get_platform_settings(mask_secrets=False)

        self.assertEqual(saved["runner"]["browser_mode"], "visible")
        self.assertFalse(saved["runner"]["headless"])
        self.assertEqual(loaded["runner"]["queue_mode"], "serial")
        self.assertFalse(loaded["asset_policy"]["observed_asset_enabled"])
        self.assertEqual(loaded["asset_policy"]["merge_strategy"], "conservative")
        self.assertEqual(loaded["environment"]["icm_base_url"], "https://icm.example.test")
        self.assertEqual(loaded["accounts"]["labo"]["username"], "labo3")
        self.assertNotIn("password", loaded["accounts"]["labo"])
        self.assertEqual(loaded["accounts"]["labo"]["password_masked"], "****-one")
        self.assertEqual(raw["accounts"]["labo"]["password"], "secret-one")

    def test_lists_batch_children_with_pending_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            report_dir = Path(folder)
            (report_dir / "ui-batch-tc-icm-001.md").write_text(
                "\n".join(
                    [
                        "# ui-batch-tc-icm-001",
                        "- case name: TC-ICM-001 Login",
                        "- status: passed",
                        "- screenshot paths:",
                    ]
                ),
                encoding="utf-8",
            )
            (report_dir / "ui-batch-tc-icm-003.md").write_text(
                "\n".join(
                    [
                        "# ui-batch-tc-icm-003",
                        "- case name: TC-ICM-003 Device query",
                        "- status: failed",
                        "- screenshot paths:",
                    ]
                ),
                encoding="utf-8",
            )

            with patch("icm_platform.assets.REPORT_DIR", report_dir):
                children = list_batch_child_reports("ui-batch")

        self.assertEqual(len(children), 12)
        self.assertEqual(children[0]["case_id"], "TC-ICM-001")
        self.assertEqual(children[0]["status"], "passed")
        self.assertEqual(children[1]["case_id"], "TC-ICM-002")
        self.assertEqual(children[1]["status"], "pending")
        self.assertEqual(children[2]["case_id"], "TC-ICM-003")
        self.assertEqual(children[2]["status"], "failed")
        self.assertEqual(children[2]["run_id"], "ui-batch-tc-icm-003")

    def test_merge_observed_asset_requires_passed_run(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / "test.sqlite3"
            observed_dir = root / "observed-assets"
            observed_dir.mkdir()
            (observed_dir / "ui-failed.json").write_text(json.dumps({"operation_steps": []}), encoding="utf-8")

            with (
                patch("icm_platform.db.DB_PATH", db_path),
                patch("icm_platform.db.DATA_DIR", db_path.parent),
                patch("icm_platform.api.OBSERVED_ASSET_DIR", observed_dir),
            ):
                db.init_db()
                with db.connect() as conn:
                    conn.execute(
                        "insert into run_tasks(id, mode, case_id, status, command, created_at) values (?, ?, ?, ?, ?, ?)",
                        ("ui-failed", "run-case", "TC-ICM-099", "failed", "python -m runner.main", "2026-06-07T00:00:00"),
                    )
                with self.assertRaises(HTTPException) as caught:
                    merge_run_observed_asset("ui-failed")

        self.assertEqual(caught.exception.status_code, 400)

    def test_merge_observed_asset_updates_case_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / "test.sqlite3"
            case_dir = root / "test-cases" / "icm"
            observed_dir = root / "observed-assets"
            case_dir.mkdir(parents=True)
            observed_dir.mkdir()
            case_path = case_dir / "TC-ICM-099-generated.yaml"
            case_path.write_text(
                yaml.safe_dump(
                    {
                        "id": "TC-ICM-099",
                        "system": "icm-internal",
                        "title": "Observed asset merge",
                        "status": "draft",
                        "steps": ["do action"],
                        "expected_results": ["see result"],
                        "automation_asset": {
                            "operation_steps": ["manual step"],
                            "selectors": {"manual": ["text=Manual"]},
                            "input_values": {"name": "Tester"},
                            "assertions": ["manual assertion"],
                        },
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (observed_dir / "ui-passed.json").write_text(
                json.dumps(
                    {
                        "source": "playwright_observed",
                        "observed_at": "2026-06-07T00:00:00+00:00",
                        "evidence": {"run_id": "ui-passed", "screenshots": ["screenshots/latest/TC-ICM-099/03-final.png"]},
                        "operation_steps": ["observed step"],
                        "selectors": {"click_001": ["text=OK"]},
                        "input_values": {"fill_001": "value"},
                        "assertions": ["Text is visible: OK"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with (
                patch("icm_platform.db.DB_PATH", db_path),
                patch("icm_platform.db.DATA_DIR", db_path.parent),
                patch("icm_platform.api.TEST_CASE_DIR", case_dir),
                patch("icm_platform.api.OBSERVED_ASSET_DIR", observed_dir),
            ):
                db.init_db()
                with db.connect() as conn:
                    conn.execute(
                        "insert into run_tasks(id, mode, case_id, status, command, created_at) values (?, ?, ?, ?, ?, ?)",
                        ("ui-passed", "run-case", "TC-ICM-099", "passed", "python -m runner.main", "2026-06-07T00:00:00"),
                    )
                result = merge_run_observed_asset("ui-passed")
                updated = yaml.safe_load(case_path.read_text(encoding="utf-8"))

        self.assertEqual(result["case_id"], "TC-ICM-099")
        self.assertEqual(updated["automation_asset"]["status"], "verified")
        self.assertEqual(updated["automation_asset"]["source"], "playwright_observed")
        self.assertEqual(updated["automation_asset"]["evidence"]["run_id"], "ui-passed")
        self.assertEqual(updated["automation_asset"]["operation_steps"], ["manual step"])


if __name__ == "__main__":
    unittest.main()
