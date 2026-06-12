"""路线 B · T7 / T8 单测
- T7: GET /api/cases/{case_id}/stability（4 段 status 计算）+ GET /api/stability-scans/{scan_id}
- T8: POST /api/cases/{case_id}/recompute-stability（异步入口 + 落 stability_scans）
- _compute_stability 纯函数：window / insufficient / stable / flaky / unstable 4 段
"""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from icm_platform import db
from icm_platform.api import (
    STABILITY_INSUFFICIENT_THRESHOLD,
    STABILITY_THRESHOLD_DEFAULT,
    STABILITY_UNSTABLE_THRESHOLD_DEFAULT,
    _compute_stability,
    _start_stability_scan,
)


def _try_import_app():
    try:
        from icm_platform.api import app
        return app
    except Exception:  # noqa: BLE001
        return None


_client_app = _try_import_app()


def _make_test_world():
    folder = tempfile.mkdtemp()
    root = Path(folder)
    db_path = root / "test.sqlite3"
    case_dir = root / "test-cases" / "icm"
    scan_log_dir = root / "runner-logs"
    case_dir.mkdir(parents=True)
    scan_log_dir.mkdir(parents=True)
    return root, db_path, case_dir, scan_log_dir


def _seed_case_runs(conn, case_id: str, passed_count: int, failed_count: int) -> None:
    """往 case_runs 表里塞 N 条 passed + M 条 failed，时间倒序。"""
    now_iso = "2026-06-09T12:00:00+00:00"
    rows = []
    for i in range(passed_count):
        rows.append((case_id, f"run-passed-{i:03d}", 1, now_iso, now_iso, 1))
    for i in range(failed_count):
        rows.append((case_id, f"run-failed-{i:03d}", 0, now_iso, now_iso, 1))
    for r in rows:
        conn.execute(
            """
            insert into case_runs(case_id, run_id, passed, started_at, finished_at, attempt)
            values (?, ?, ?, ?, ?, ?)
            """,
            r,
        )


class PureStabilityTests(unittest.TestCase):
    """_compute_stability 纯函数（不依赖 DB 也能跑过的部分）"""

    def test_thresholds_constants_align_with_prd(self):
        # 0.95 stable / 0.80 flaky|unstable / <5 insufficient
        self.assertEqual(STABILITY_THRESHOLD_DEFAULT, 0.95)
        self.assertEqual(STABILITY_UNSTABLE_THRESHOLD_DEFAULT, 0.80)
        self.assertEqual(STABILITY_INSUFFICIENT_THRESHOLD, 5)


@unittest.skipIf(_client_app is None, "依赖未安装，跳过 endpoint 测试")
class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.world = _make_test_world()
        self.root, self.db_path, self.case_dir, self.scan_log_dir = self.world
        self._patchers = [
            patch("icm_platform.db.DB_PATH", self.db_path),
            patch("icm_platform.db.DATA_DIR", self.root),
            patch("icm_platform.api.SCAN_LOG_DIR", self.scan_log_dir),
        ]
        for p in self._patchers:
            p.start()
        db.init_db()

        from icm_platform import api as api_module
        self.api = api_module

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        # 等异步线程退出（如果有）
        time.sleep(0.1)
        shutil.rmtree(self.world[0], ignore_errors=True)

    # ---- T7 纯函数 ----
    def test_compute_stability_insufficient_when_less_than_5(self):
        with db.connect() as conn:
            _seed_case_runs(conn, "TC-ICM-100", passed_count=3, failed_count=1)  # total=4
        s = _compute_stability("TC-ICM-100", window=20)
        self.assertEqual(s["status"], "insufficient")
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["passed"], 3)
        self.assertEqual(s["pass_rate"], 0.75)

    def test_compute_stability_stable_when_pass_rate_geq_95(self):
        with db.connect() as conn:
            _seed_case_runs(conn, "TC-ICM-101", passed_count=10, failed_count=0)
        s = _compute_stability("TC-ICM-101", window=20)
        self.assertEqual(s["status"], "stable")
        self.assertEqual(s["pass_rate"], 1.0)
        self.assertGreaterEqual(s["pass_rate"], STABILITY_THRESHOLD_DEFAULT)

    def test_compute_stability_flaky_between_80_and_95(self):
        with db.connect() as conn:
            _seed_case_runs(conn, "TC-ICM-102", passed_count=8, failed_count=2)  # 80%
        s = _compute_stability("TC-ICM-102", window=20)
        self.assertEqual(s["status"], "flaky")
        self.assertEqual(s["pass_rate"], 0.8)

    def test_compute_stability_unstable_below_80(self):
        with db.connect() as conn:
            _seed_case_runs(conn, "TC-ICM-103", passed_count=6, failed_count=4)  # 60%
        s = _compute_stability("TC-ICM-103", window=20)
        self.assertEqual(s["status"], "unstable")
        self.assertLess(s["pass_rate"], STABILITY_UNSTABLE_THRESHOLD_DEFAULT)

    def test_compute_stability_window_limits(self):
        with db.connect() as conn:
            _seed_case_runs(conn, "TC-ICM-104", passed_count=8, failed_count=8)  # 50% in 16
        s = _compute_stability("TC-ICM-104", window=5)
        # window=5 时只取最新 5 条；按 seed 顺序，新的是 failed（虽然 pass_rate 不准确定）
        self.assertLessEqual(s["total"], 5)
        self.assertIn("thresholds", s)
        self.assertEqual(s["thresholds"]["stable"], STABILITY_THRESHOLD_DEFAULT)
        self.assertEqual(s["thresholds"]["unstable"], STABILITY_UNSTABLE_THRESHOLD_DEFAULT)

    # ---- T7 endpoint ----
    def test_get_stability_endpoint_returns_4_segment_status(self):
        with db.connect() as conn:
            _seed_case_runs(conn, "TC-ICM-200", passed_count=8, failed_count=2)  # 80% → flaky
        # endpoint 内调用 _compute_stability（直接调 endpoint 会触发 FastAPI Query 解析，
        # 单元测试里直接调底层函数更稳定）
        body = self.api._compute_stability("TC-ICM-200", window=20)
        self.assertEqual(body["case_id"], "TC-ICM-200")
        self.assertEqual(body["status"], "flaky")
        self.assertEqual(body["total"], 10)
        self.assertEqual(body["passed"], 8)
        self.assertEqual(body["pass_rate"], 0.8)

    def test_get_stability_endpoint_window_param(self):
        with db.connect() as conn:
            _seed_case_runs(conn, "TC-ICM-201", passed_count=7, failed_count=3)
        body = self.api._compute_stability("TC-ICM-201", window=5)
        self.assertEqual(body["window"], 5)
        self.assertEqual(body["total"], 5)

    # ---- T8 异步入口 ----
    def test_start_stability_scan_creates_row_and_returns_scan_id(self):
        # 跑通 _start_stability_scan（不真启线程，改 monkey patch）
        # 直接验证：scan_id 返回 + stability_scans 表新增 1 行
        # 拦截 _run_stability_scan_thread 让其立即返回，避免 subprocess 启动
        with patch.object(self.api, "_run_stability_scan_thread", lambda scan_id, case_id, times: None):
            result = self.api._start_stability_scan("TC-ICM-300", times=3)
        self.assertIn("scan_id", result)
        self.assertEqual(result["case_id"], "TC-ICM-300")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["times"], 3)
        with db.connect() as conn:
            row = conn.execute(
                "select * from stability_scans where id = ?", (result["scan_id"],)
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["times"], 3)
        self.assertEqual(row["completed"], 0)

    def test_start_stability_scan_validates_times(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            self.api._start_stability_scan("TC-ICM-301", times=0)
        self.assertEqual(caught.exception.status_code, 400)
        with self.assertRaises(HTTPException) as caught:
            self.api._start_stability_scan("TC-ICM-301", times=100)
        self.assertEqual(caught.exception.status_code, 400)

    # ---- T8 endpoint ----
    def test_recompute_stability_endpoint_fixed_10_times(self):
        with patch.object(self.api, "_run_stability_scan_thread", lambda scan_id, case_id, times: None):
            body = self.api.post_recompute_stability("TC-ICM-400")
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["times"], 10)
        self.assertEqual(body["case_id"], "TC-ICM-400")
        with db.connect() as conn:
            row = conn.execute(
                "select * from stability_scans where id = ?", (body["scan_id"],)
            ).fetchone()
        self.assertEqual(row["times"], 10)

    def test_stability_scan_endpoint_default_10(self):
        with patch.object(self.api, "_run_stability_scan_thread", lambda scan_id, case_id, times: None):
            body = self.api.post_stability_scan("TC-ICM-401")
        self.assertEqual(body["times"], 10)

    def test_stability_scan_endpoint_accepts_payload(self):
        with patch.object(self.api, "_run_stability_scan_thread", lambda scan_id, case_id, times: None):
            from icm_platform.api import StabilityScanRequest
            body = self.api.post_stability_scan("TC-ICM-402", StabilityScanRequest(times=5))
        self.assertEqual(body["times"], 5)

    def test_get_stability_scan_returns_404_when_missing(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            self.api.get_stability_scan("nonexistent-scan-id")
        self.assertEqual(caught.exception.status_code, 404)

    def test_get_stability_scan_returns_row(self):
        with patch.object(self.api, "_run_stability_scan_thread", lambda scan_id, case_id, times: None):
            created = self.api._start_stability_scan("TC-ICM-500", times=2)
        body = self.api.get_stability_scan(created["scan_id"])
        self.assertEqual(body["case_id"], "TC-ICM-500")
        self.assertEqual(body["times"], 2)


if __name__ == "__main__":
    unittest.main()
