from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from icm_platform import db


class RequirementAppendGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = tempfile.mkdtemp()
        self.root = Path(self.world)
        self.patchers = [
            patch("icm_platform.db.DB_PATH", self.root / "test.sqlite3"),
            patch("icm_platform.db.DATA_DIR", self.root),
        ]
        for patcher in self.patchers:
            patcher.start()
        db.init_db()
        from icm_platform import api

        self.api = api

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        shutil.rmtree(self.world, ignore_errors=True)

    def test_generation_appends_to_existing_requirement_and_continues_ids(self) -> None:
        now = db.utc_now()
        with db.connect() as conn:
            requirement_id = conn.execute(
                """
                insert into requirements(title, document, status, case_count, created_at, updated_at)
                values ('登录需求', '登录正文', 'analyzed', 2, ?, ?)
                """,
                (now, now),
            ).lastrowid
            for case_id in ("LOGIN_FUN_009", "LOGIN_EXC_013"):
                conn.execute(
                    """
                    insert into case_drafts(requirement_id, title, yaml, status, created_at, updated_at)
                    values (?, ?, ?, 'draft', ?, ?)
                    """,
                    (requirement_id, case_id, yaml.safe_dump({"id": case_id}), now, now),
                )

        generated = {
            "cases": [
                {"id": "LOGIN_FUN_001", "title": "正常登录"},
                {"id": "LOGIN_BND_002", "title": "边界登录"},
            ]
        }
        with (
            patch.object(self.api.ai_service, "generate_test_cases_spec", return_value=generated),
            patch.object(self.api, "get_ai_settings", return_value={"provider": "test"}),
        ):
            result = self.api.analyze_requirement_spec(
                self.api.RequirementRequest(
                    title="登录需求",
                    document="登录正文",
                    requirement_id=requirement_id,
                )
            )

        with db.connect() as conn:
            requirement_count = conn.execute("select count(*) from requirements").fetchone()[0]
            rows = conn.execute(
                "select yaml from case_drafts where requirement_id = ? order by id",
                (requirement_id,),
            ).fetchall()
            case_count = conn.execute(
                "select case_count from requirements where id = ?", (requirement_id,)
            ).fetchone()[0]

        self.assertEqual(requirement_count, 1)
        self.assertEqual([yaml.safe_load(row["yaml"])["id"] for row in rows], [
            "LOGIN_FUN_009",
            "LOGIN_EXC_013",
            "LOGIN_FUN_014",
            "LOGIN_BND_015",
        ])
        self.assertEqual(case_count, 4)
        self.assertEqual(result["requirement"]["id"], requirement_id)
        self.assertEqual(result["generated_cases"], 2)


if __name__ == "__main__":
    unittest.main()
