"""P0 · 所属项目下拉化单测（增量 2026-06-10）

覆盖（基线 P0 验收 + T8）：
- 列表（空 → 2 条种子；非空 → 原样）
- 创建（name 必填、UNIQUE 冲突 → ValueError('conflict')）
- 删除（成功 / 404）
- 种子存在（启动幂等）
- 启动时 DDL 幂等（再调一次 init_db 不会报错）

不在本测试范围（按 ARCH §4 / T8 任务表）：
- GET /api/projects/{id}（ARCH 未列该端点）
- PATCH /api/projects/{id} 端到端（架构文档虽列了端点，但 T8 字面只列了
  "列表 / 创建 / 重复 name 拒绝 / 删除 / 种子存在"；为不越界，仅 db 层覆盖 PATCH）
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icm_platform import db


def _make_test_world():
    folder = tempfile.mkdtemp()
    root = Path(folder)
    db_path = root / "test.sqlite3"
    return root, db_path


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


class ProjectProfilesDbTests(unittest.TestCase):
    """db 层覆盖：纯函数（DDL 幂等 / 种子 / 列表 / 创建 / UNIQUE / 删除）。"""

    def setUp(self):
        self.world = _make_test_world()
        self.root, self.db_path = self.world
        self._patchers = [
            patch("icm_platform.db.DB_PATH", self.db_path),
            patch("icm_platform.db.DATA_DIR", self.root),
        ]
        for p in self._patchers:
            p.start()
        # 第一次 init_db 建表 + 种子
        db.init_db()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        shutil.rmtree(self.world[0], ignore_errors=True)

    def test_seed_inserted_on_empty_table(self):
        """启动时若 project_profiles 为空，插 2 条：ICM / DxONE，base_url 占位。"""
        rows = db.list_project_profiles()
        self.assertEqual(len(rows), 2)
        names = {row["name"] for row in rows}
        self.assertSetEqual(names, {"ICM", "DxONE"})
        for row in rows:
            self.assertEqual(row["base_url"], "https://icm.example.com")
            self.assertEqual(row["description"], "请在创建后修改")
            self.assertTrue(row["id"].startswith("proj-"))

    def test_seed_is_idempotent(self):
        """再次 init_db 不会重复插种子。"""
        db.init_db()
        rows = db.list_project_profiles()
        self.assertEqual(len(rows), 2, "二次 init_db 后仍只有 2 条种子")

    def test_init_db_is_idempotent(self):
        """DDL 幂等：再调一次 init_db 不抛错。"""
        try:
            db.init_db()
        except sqlite3.OperationalError as exc:  # pragma: no cover - 防御
            self.fail(f"init_db 二次调用应幂等，意外抛错：{exc}")

    def test_create_project_returns_dict_with_required_fields(self):
        created = db.create_project_profile({"name": "Alpha", "base_url": "https://alpha.example.com"})
        self.assertEqual(created["name"], "Alpha")
        self.assertEqual(created["base_url"], "https://alpha.example.com")
        self.assertIsNone(created["description"])
        self.assertTrue(created["id"].startswith("proj-"))
        self.assertTrue(created["created_at"])
        self.assertTrue(created["updated_at"])

    def test_create_project_strips_blank_optional_fields_to_none(self):
        created = db.create_project_profile(
            {"name": "Beta", "base_url": "  ", "description": ""}
        )
        self.assertIsNone(created["base_url"])
        self.assertIsNone(created["description"])

    def test_create_project_rejects_blank_name(self):
        with self.assertRaises(ValueError) as ctx:
            db.create_project_profile({"name": "   "})
        self.assertIn("invalid", str(ctx.exception))

    def test_create_project_rejects_duplicate_name(self):
        # ICM 是种子，已存在
        with self.assertRaises(ValueError) as ctx:
            db.create_project_profile({"name": "ICM"})
        self.assertIn("conflict", str(ctx.exception))

    def test_update_project_renames(self):
        created = db.create_project_profile({"name": "Gamma"})
        updated = db.update_project_profile(created["id"], {"name": "Gamma-2"})
        self.assertIsNotNone(updated)
        self.assertEqual(updated["name"], "Gamma-2")

    def test_update_project_returns_none_when_missing(self):
        result = db.update_project_profile("proj-nonexistent", {"name": "X"})
        self.assertIsNone(result)

    def test_update_project_rejects_blank_name(self):
        created = db.create_project_profile({"name": "Delta"})
        with self.assertRaises(ValueError) as ctx:
            db.update_project_profile(created["id"], {"name": "   "})
        self.assertIn("invalid", str(ctx.exception))

    def test_update_project_rejects_duplicate_name(self):
        a = db.create_project_profile({"name": "Eps"})
        with self.assertRaises(ValueError) as ctx:
            db.update_project_profile(a["id"], {"name": "ICM"})
        self.assertIn("conflict", str(ctx.exception))

    def test_delete_project_returns_true_then_false(self):
        created = db.create_project_profile({"name": "Zeta"})
        self.assertTrue(db.delete_project_profile(created["id"]))
        self.assertFalse(db.delete_project_profile(created["id"]))

    def test_delete_project_does_not_affect_seed(self):
        """删一个非种子项目后，2 条种子仍存在。"""
        db.create_project_profile({"name": "Eta"})
        self.assertEqual(len(db.list_project_profiles()), 3)
        db.delete_project_profile(next(p["id"] for p in db.list_project_profiles() if p["name"] == "Eta"))
        rows = db.list_project_profiles()
        self.assertEqual(len(rows), 2)
        self.assertSetEqual({p["name"] for p in rows}, {"ICM", "DxONE"})

    def test_get_project_profile_returns_dict_or_none(self):
        created = db.create_project_profile({"name": "Theta"})
        self.assertEqual(db.get_project_profile(created["id"])["name"], "Theta")
        self.assertIsNone(db.get_project_profile("proj-missing"))

    def test_list_orders_by_name_then_created_at(self):
        """list_project_profiles 应按 (name, created_at) 升序稳定排序。

        顺序：DxONE（D）< First（F）< ICM（I）< Second（S）。
        """
        db.create_project_profile({"name": "First"})
        db.create_project_profile({"name": "Second"})
        rows = db.list_project_profiles()
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["name"] for r in rows], ["DxONE", "First", "ICM", "Second"])


@unittest.skipIf(
    _client_app is None or _test_client_cls is None,
    "FastAPI 端点 / httpx 依赖未安装，跳过端点测试",
)
class ProjectProfilesEndpointTests(unittest.TestCase):
    """HTTP 端点层覆盖：列表 / 创建 / 重复 name → 409 / 删除 / 种子存在。"""

    def setUp(self):
        self.world = _make_test_world()
        self.root, self.db_path = self.world
        self._patchers = [
            patch("icm_platform.db.DB_PATH", self.db_path),
            patch("icm_platform.db.DATA_DIR", self.root),
        ]
        for p in self._patchers:
            p.start()
        db.init_db()
        from icm_platform import api as api_module
        self.api = api_module
        self.client = _test_client_cls(self.api.app)

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        shutil.rmtree(self.world[0], ignore_errors=True)

    def test_get_projects_returns_seeded_two(self):
        resp = self.client.get("/api/projects")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertSetEqual({row["name"] for row in data}, {"ICM", "DxONE"})

    def test_post_creates_project(self):
        resp = self.client.post(
            "/api/projects",
            json={"name": "NewOne", "base_url": "https://new.example.com"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["name"], "NewOne")
        self.assertEqual(body["base_url"], "https://new.example.com")
        self.assertTrue(body["id"].startswith("proj-"))

    def test_post_rejects_blank_name_400(self):
        resp = self.client.post("/api/projects", json={"name": "   "})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("name is required", resp.json()["detail"])

    def test_post_rejects_duplicate_name_409(self):
        resp = self.client.post("/api/projects", json={"name": "ICM"})
        self.assertEqual(resp.status_code, 409)
        self.assertIn("already exists", resp.json()["detail"])

    def test_delete_project(self):
        # 先建
        created = self.client.post("/api/projects", json={"name": "ToDelete"}).json()
        resp = self.client.delete(f"/api/projects/{created['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

    def test_delete_missing_returns_404(self):
        resp = self.client.delete("/api/projects/proj-nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_patch_renames_and_pads_description(self):
        # 先建
        created = self.client.post("/api/projects", json={"name": "Patchable"}).json()
        resp = self.client.patch(
            f"/api/projects/{created['id']}",
            json={"name": "Patched", "description": "补充说明"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["name"], "Patched")
        self.assertEqual(body["description"], "补充说明")

    def test_patch_missing_returns_404(self):
        resp = self.client.patch(
            "/api/projects/proj-nonexistent",
            json={"name": "X"},
        )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
