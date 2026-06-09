from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from icm_platform import db
from icm_platform.api import (
    CaseDraftPatchRequest,
    PromoteDraftRequest,
    SelectedTestPointsRequest,
    TestPointCreateRequest,
    TestPointPatchRequest,
    TestPointReorderRequest,
    TestPointReorderUpdate,
    ValidateDraftRequest,
    case_drafts,
    create_test_point,
    generate_cases_from_test_points,
    promote_case_draft,
    test_points,
    update_case_draft,
    update_test_point,
    update_test_points_order,
    validate_case_draft,
    validate_case_yaml,
)


class TestPointsModelTests(unittest.TestCase):
    def test_init_db_adds_mindmap_and_case_draft_columns(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "test.sqlite3"
            with patch("icm_platform.db.DB_PATH", db_path), patch("icm_platform.db.DATA_DIR", db_path.parent):
                db.init_db()
                with db.connect() as conn:
                    point_columns = {row["name"] for row in conn.execute("pragma table_info(test_points)").fetchall()}
                    draft_columns = {row["name"] for row in conn.execute("pragma table_info(case_drafts)").fetchall()}

        self.assertIn("parent_id", point_columns)
        self.assertIn("sort_order", point_columns)
        self.assertIn("module", point_columns)
        self.assertIn("source", point_columns)
        self.assertIn("updated_at", point_columns)
        self.assertIn("template", draft_columns)
        self.assertIn("source_test_point_ids", draft_columns)
        self.assertIn("promoted_case_id", draft_columns)
        self.assertIn("promoted_path", draft_columns)

    def test_create_patch_and_reorder_test_point_mindmap_fields(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "test.sqlite3"
            with patch("icm_platform.db.DB_PATH", db_path), patch("icm_platform.db.DATA_DIR", db_path.parent):
                db.init_db()
                parent = create_test_point(
                    TestPointCreateRequest(name="parent point", category="功能", priority="P0", module="remote help", source="manual")
                )
                child = create_test_point(
                    TestPointCreateRequest(
                        name="child point",
                        category="边界",
                        priority="P1",
                        parent_id=parent["id"],
                        module="remote help",
                        source="mindmap_edit",
                        sort_order=7,
                    )
                )

                update_test_point(child["id"], TestPointPatchRequest(module="ticket handling", source="case_asset"))
                update_test_points_order(
                    TestPointReorderRequest(
                        updates=[
                            TestPointReorderUpdate(id=parent["id"], parent_id=None, sort_order=2, module="remote help"),
                            TestPointReorderUpdate(id=child["id"], parent_id=parent["id"], sort_order=1, module="ticket handling"),
                        ]
                    )
                )
                points = test_points(status="confirmed")

        child_point = next(point for point in points if point["id"] == child["id"])
        self.assertEqual(child_point["parent_id"], parent["id"])
        self.assertEqual(child_point["sort_order"], 1)
        self.assertEqual(child_point["module"], "ticket handling")
        self.assertEqual(child_point["source"], "case_asset")

    def test_generate_cases_keeps_sort_order(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "test.sqlite3"
            with patch("icm_platform.db.DB_PATH", db_path), patch("icm_platform.db.DATA_DIR", db_path.parent):
                db.init_db()
                second = create_test_point(TestPointCreateRequest(name="second", sort_order=2))
                first = create_test_point(TestPointCreateRequest(name="first", sort_order=1))
                result = generate_cases_from_test_points(SelectedTestPointsRequest(test_point_ids=[second["id"], first["id"]]))

        self.assertLess(result["yaml"].find("first"), result["yaml"].find("second"))

    def test_case_draft_lifecycle_and_promote_safety(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / "test.sqlite3"
            case_dir = root / "test-cases" / "icm"
            with (
                patch("icm_platform.db.DB_PATH", db_path),
                patch("icm_platform.db.DATA_DIR", db_path.parent),
                patch("icm_platform.api.TEST_CASE_DIR", case_dir),
            ):
                db.init_db()
                point = create_test_point(TestPointCreateRequest(name="remote help request", sort_order=1))
                generated = generate_cases_from_test_points(
                    SelectedTestPointsRequest(
                        test_point_ids=[point["id"]],
                        template="e2e",
                        title="remote help e2e draft",
                        generator="rule",
                    )
                )
                valid_yaml = """
id: TC-ICM-DRAFT
title: remote help e2e draft
status: draft
type: e2e
steps:
  - open remote help request entry
expected_results:
  - remote help request is created
automation_asset:
  operation_steps:
    - open remote help request entry
  selectors:
    - text=请求协助
  input_values:
    contact: Tester
  assertions:
    - request record exists
""".strip()
                updated = update_case_draft(generated["draft_id"], CaseDraftPatchRequest(title="edited draft", yaml=valid_yaml))
                promoted = promote_case_draft(
                    generated["draft_id"],
                    PromoteDraftRequest(case_id="TC-ICM-099", filename="tc-icm-099-generated.yaml"),
                )
                drafts = case_drafts()
                promoted_file_exists = (case_dir / "tc-icm-099-generated.yaml").exists()

        self.assertEqual(updated["title"], "edited draft")
        self.assertEqual(promoted["status"], "promoted")
        self.assertEqual(promoted["promoted_case_id"], "TC-ICM-099")
        self.assertTrue(promoted_file_exists)
        self.assertEqual(drafts[0]["source_test_point_ids"], [point["id"]])

    def test_validate_case_yaml_blocks_incomplete_automation_asset(self) -> None:
        invalid = """
id: TC-ICM-DRAFT
title: incomplete draft
status: draft
steps:
  - do something
expected_results:
  - see result
automation_asset:
  operation_steps: []
  selectors: []
  input_values: {}
  assertions: []
""".strip()
        result = validate_case_yaml(invalid)

        self.assertFalse(result["valid"])
        self.assertIn("automation_asset.operation_steps must be a non-empty list", result["errors"])
        self.assertIn("automation_asset.selectors must be a non-empty list or mapping", result["errors"])
        self.assertIn("automation_asset.assertions must be a non-empty list", result["errors"])

    def test_promote_rejects_invalid_case_draft_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / "test.sqlite3"
            case_dir = root / "test-cases" / "icm"
            with (
                patch("icm_platform.db.DB_PATH", db_path),
                patch("icm_platform.db.DATA_DIR", db_path.parent),
                patch("icm_platform.api.TEST_CASE_DIR", case_dir),
            ):
                db.init_db()
                point = create_test_point(TestPointCreateRequest(name="remote help request", sort_order=1))
                generated = generate_cases_from_test_points(
                    SelectedTestPointsRequest(
                        test_point_ids=[point["id"]],
                        template="e2e",
                        title="remote help e2e draft",
                        generator="rule",
                    )
                )
                validation = validate_case_draft(generated["draft_id"], ValidateDraftRequest(case_id="TC-ICM-100"))
                with self.assertRaises(HTTPException) as caught:
                    promote_case_draft(generated["draft_id"], PromoteDraftRequest(case_id="TC-ICM-100"))

        self.assertFalse(validation["valid"])
        self.assertEqual(caught.exception.status_code, 400)
        self.assertFalse((case_dir / "tc-icm-100-generated.yaml").exists())


if __name__ == "__main__":
    unittest.main()
