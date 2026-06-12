"""路线 A · T2 / T3 单测
- T2: compute_observed_asset_diff 纯函数 + GET /api/cases/{case_id}/observed-asset-diff endpoint
- T3: POST /api/cases/{case_id}/adoptions（accept + reject + 验证失败回滚）+ GET /api/cases/{case_id}/adoptions
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
from icm_platform.api import compute_observed_asset_diff


def _try_import_app():
    """尝试导入 app，遇到 openpyxl 缺失则跳过"""
    try:
        from icm_platform.api import app
        return app
    except Exception:  # noqa: BLE001
        return None


# 直接尝试 TestClient；缺失依赖则本文件中的 endpoint 测试会被 skip
_client_app = _try_import_app()


def _make_test_world():
    """在临时目录里搭建一个完整测试世界：DB + test-cases/icm + observed-assets"""
    folder = tempfile.mkdtemp()
    root = Path(folder)
    db_path = root / "test.sqlite3"
    case_dir = root / "test-cases" / "icm"
    observed_dir = root / "observed-assets"
    yaml_backup_dir = root / ".codex-tmp" / "yaml-backup"
    case_dir.mkdir(parents=True)
    observed_dir.mkdir(parents=True)
    return root, db_path, case_dir, observed_dir, yaml_backup_dir


VALID_YAML_TEXT = yaml.safe_dump(
    {
        "id": "TC-ICM-099",
        "system": "icm-internal",
        "title": "Adoption test",
        "status": "active",
        "steps": ["step 1"],
        "expected_results": ["result 1"],
        "automation_asset": {
            "operation_steps": ["manual step"],
            "selectors": {"x": "y"},
            "input_values": {"name": "Tester"},
            "assertions": ["assert1"],
        },
    },
    allow_unicode=True,
    sort_keys=False,
)


class PureDiffTests(unittest.TestCase):
    """T2 纯函数：compute_observed_asset_diff"""

    def test_kept_when_existing_and_observed_equivalent(self):
        existing = {"selectors": {"x": "y"}, "operation_steps": ["a"]}
        observed = {"selectors": {"x": "y"}, "operation_steps": ["a"], "source": "playwright_observed"}
        diff = compute_observed_asset_diff(existing, observed)
        self.assertEqual(diff["kept"].get("selectors"), {"x": "y"})
        self.assertEqual(diff["kept"].get("operation_steps"), ["a"])
        self.assertEqual(diff["added"], {})

    def test_kept_preserves_existing_when_observed_diverge(self):
        """现有 YAML 含 x:y，observed 含 x:y2 + new:z → kept.x=y（保留）"""
        existing = {"selectors": {"x": "y"}}
        observed = {"selectors": {"x": "y2", "new": "z"}}
        diff = compute_observed_asset_diff(existing, observed)
        self.assertEqual(diff["kept"]["selectors"], {"x": "y"})
        self.assertIn("new", diff["added"].get("selectors", {}))
        self.assertEqual(diff["added"]["selectors"]["new"], "z")

    def test_added_when_existing_empty(self):
        existing = {"selectors": {}, "input_values": {}}
        observed = {
            "operation_steps": ["a", "b"],
            "selectors": {"s": "v"},
            "input_values": {"k": "v"},
            "assertions": ["x"],
        }
        diff = compute_observed_asset_diff(existing, observed)
        self.assertEqual(diff["added"]["operation_steps"], ["a", "b"])
        self.assertEqual(diff["added"]["selectors"], {"s": "v"})
        self.assertEqual(diff["missing"], [])

    def test_missing_when_both_empty(self):
        diff = compute_observed_asset_diff({}, {})
        self.assertIn("automation_asset.operation_steps", diff["missing"])
        self.assertIn("automation_asset.assertions", diff["missing"])
        self.assertIn("automation_asset.selectors", diff["missing"])
        self.assertIn("automation_asset.input_values", diff["missing"])


@unittest.skipIf(_client_app is None, "openpyxl 等依赖未安装，跳过 endpoint 测试")
class EndpointTests(unittest.TestCase):
    """T2 + T3 endpoint 集成测试（直接调用函数 + FastAPI 路由包装）"""

    def setUp(self):
        self.world = _make_test_world()
        self.root, self.db_path, self.case_dir, self.observed_dir, self.yaml_backup_dir = self.world
        # 写入 case YAML
        case_path = self.case_dir / "tc-icm-099-generated.yaml"
        case_path.write_text(VALID_YAML_TEXT, encoding="utf-8")
        # 写入 observed JSON
        observed = {
            "source": "playwright_observed",
            "observed_at": "2026-06-09T00:00:00+00:00",
            "evidence": {"run_id": "ui-passed-1", "screenshots": []},
            "operation_steps": ["observed step", "step 2"],
            "selectors": {"x": "y2", "new": "z"},
            "input_values": {"name": "Tester", "extra": "v"},
            "assertions": ["assert1", "assert2"],
        }
        (self.observed_dir / "ui-passed-1.json").write_text(json.dumps(observed, ensure_ascii=False), encoding="utf-8")
        # 启动 DB
        self._patchers = [
            patch("icm_platform.db.DB_PATH", self.db_path),
            patch("icm_platform.db.DATA_DIR", self.root),
            patch("icm_platform.api.TEST_CASE_DIR", self.case_dir),
            patch("icm_platform.api.OBSERVED_ASSET_DIR", self.observed_dir),
            patch("icm_platform.api.YAML_BACKUP_DIR", self.yaml_backup_dir),
        ]
        for p in self._patchers:
            p.start()
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                "insert into run_tasks(id, mode, case_id, status, command, created_at) values (?, ?, ?, ?, ?, ?)",
                ("ui-passed-1", "run-case", "TC-ICM-099", "passed", "python -m runner.main", "2026-06-09T00:00:00"),
            )
        self.case_path = case_path

        from icm_platform import api as api_module
        self.api = api_module

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        shutil.rmtree(self.world[0], ignore_errors=True)

    # ---- T2 ----
    def test_get_observed_asset_diff_endpoint(self):
        body = self.api.get_observed_asset_diff("TC-ICM-099")
        self.assertEqual(body["case_id"], "TC-ICM-099")
        self.assertEqual(body["run_id"], "ui-passed-1")
        self.assertEqual(body["diff"]["kept"]["selectors"], {"x": "y"})
        self.assertIn("new", body["diff"]["added"]["selectors"])
        self.assertEqual(body["diff"]["missing"], [])

    def test_get_observed_asset_diff_404_when_no_passed_run(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            self.api.get_observed_asset_diff("TC-ICM-XXX")
        self.assertIn("404", str(caught.exception.status_code))

    # ---- T3 ----
    def test_post_adoption_accept(self):
        from icm_platform.api import AdoptionRequest
        req = AdoptionRequest(run_id="ui-passed-1", mode="accept")
        body = self.api.post_adoption("TC-ICM-099", req)
        self.assertEqual(body["mode"], "accept")
        self.assertGreater(body["asset_adoption_id"], 0)
        self.assertEqual(body["diff_summary"]["kept"], 4)  # 4 个字段都被保守保留（op_steps/selectors/input_values/assertions）
        self.assertEqual(body["diff_summary"]["added"], 4)  # 4 个字段都被标记差异（observed 都有变化）
        # 备份文件存在
        backups = list(self.yaml_backup_dir.glob("TC-ICM-099-*.yaml"))
        self.assertEqual(len(backups), 1, "backup file must be created")
        # YAML 落盘后，selectors.x 仍是 'y'（保守语义，不被 y2 覆盖）
        updated = yaml.safe_load(self.case_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["automation_asset"]["selectors"]["x"], "y")
        # automation_asset.source 来自 observed
        self.assertEqual(updated["automation_asset"]["source"], "playwright_observed")
        # asset_adoptions 表新增 1 行
        with db.connect() as conn:
            rows = conn.execute("select * from asset_adoptions where case_id = ?", ("TC-ICM-099",)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mode"], "accept")

    def test_post_adoption_reject(self):
        from icm_platform.api import AdoptionRequest
        original = self.case_path.read_text(encoding="utf-8")
        req = AdoptionRequest(run_id="ui-passed-1", mode="reject")
        body = self.api.post_adoption("TC-ICM-099", req)
        self.assertEqual(body["mode"], "reject")
        # YAML 不动
        self.assertEqual(self.case_path.read_text(encoding="utf-8"), original)
        # 无备份文件
        self.assertEqual(list(self.yaml_backup_dir.glob("TC-ICM-099-*.yaml")), [])
        # asset_adoptions 新增 1 行 reject
        with db.connect() as conn:
            rows = conn.execute("select * from asset_adoptions where case_id = ?", ("TC-ICM-099",)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["mode"], "reject")

    def test_post_adoption_validation_failure_rolls_back(self):
        from fastapi import HTTPException
        from icm_platform.api import AdoptionRequest
        # 写一个会让合并后校验失败的 yaml（automation_asset.operation_steps=[],assertions=[]）
        bad_yaml = {
            "id": "TC-ICM-099",
            "system": "icm-internal",
            "title": "Bad",
            "status": "active",
            "steps": ["a"],
            "expected_results": ["b"],
            "automation_asset": {
                "operation_steps": [],
                "selectors": {},
                "input_values": {},
                "assertions": [],
            },
        }
        self.case_path.write_text(yaml.safe_dump(bad_yaml, allow_unicode=True, sort_keys=False), encoding="utf-8")
        # observed 也提供空 → 合并后保持空 → validate_case_yaml 必失败
        bad_observed = {
            "source": "playwright_observed",
            "observed_at": "2026-06-09T00:00:00+00:00",
            "operation_steps": [],
            "selectors": {},
            "input_values": {},
            "assertions": [],
        }
        (self.observed_dir / "ui-passed-1.json").write_text(json.dumps(bad_observed, ensure_ascii=False), encoding="utf-8")
        req = AdoptionRequest(run_id="ui-passed-1", mode="accept")
        with self.assertRaises(HTTPException) as caught:
            self.api.post_adoption("TC-ICM-099", req)
        self.assertEqual(caught.exception.status_code, 400)
        # 备份被恢复，YAML 仍是 backup 内容（operation_steps=[]）
        restored = yaml.safe_load(self.case_path.read_text(encoding="utf-8"))
        self.assertEqual(restored["automation_asset"]["operation_steps"], [])

    def test_get_adoptions_returns_recent(self):
        from icm_platform.api import AdoptionRequest
        # 先写一条 reject
        self.api.post_adoption("TC-ICM-099", AdoptionRequest(run_id="ui-passed-1", mode="reject"))
        items = self.api.get_adoptions("TC-ICM-099", limit=3)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["mode"], "reject")
        self.assertEqual(items[0]["case_id"], "TC-ICM-099")


if __name__ == "__main__":
    unittest.main()
