"""路线 B · T5 单测：runner.cases.run_case() 的 retry loop 行为。

不启动浏览器（playwright 太重）；用 FakePage 模拟 page 行为。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runner import cases as cases_module


class FakePage:
    """替代 playwright.Page 的最小 fake。

    - 每次调用 .context.clear_cookies() / .goto("about:blank") 都成功
    - .context 提供 browser 引用
    """

    def __init__(self) -> None:
        self.clears = 0
        self.gotos: list[str] = []
        self.context = self
        self.browser = self

    async def clear_cookies(self) -> None:
        self.clears += 1

    async def goto(self, url: str) -> None:
        self.gotos.append(url)


class _FakeRecorder:
    def __init__(self) -> None:
        self.shots: list[str] = []

    def screenshot(self, path: str) -> None:
        self.shots.append(path)


def _make_test_db():
    folder = Path(tempfile.mkdtemp())
    db_path = folder / "test.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        create table if not exists case_runs (
          id integer primary key autoincrement,
          case_id text not null,
          run_id text not null,
          passed integer not null,
          started_at text not null,
          finished_at text not null,
          attempt integer default 1
        );
        """
    )
    conn.commit()
    return db_path, conn, folder


def _patch_db(db_path: Path, db_folder: Path):
    return [
        patch.object(cases_module, "DB_PATH", db_path),
        patch.object(cases_module, "RETRY_LOG_DIR", db_folder / "runner-logs"),
    ]


def _stub_dependencies(monkey_attempt_runner):
    """Stub 掉 run_case 内部依赖的真实副作用（load_case/load_system/open_login_page/screenshot/...）。"""
    case = {
        "id": "TC-ICM-FAKE",
        "system": "icm-internal",
        "title": "fake",
        "status": "active",
        "automation_asset": {"input_values": {}},
    }
    system = {"id": "icm-internal", "base_url": "http://example.com", "entry_url": "/login", "credentials": {"username": "u", "password": "p"}, "account_fields": {"username_label": "用户名", "password_label": "密码", "submit_button": "登录"}, "login_state_check": {"logged_in_signals": []}, "_runtime_environment": {}, "_runtime_accounts": {}}
    return [
        patch.object(cases_module, "load_case", lambda case_id: case),
        patch.object(cases_module, "load_system", lambda system_id: system),
        patch.object(cases_module, "apply_runtime_case_inputs", lambda c, s: None),
        patch.object(cases_module, "attach_case_runtime", lambda page, run_id, case_id: None),
        patch.object(cases_module, "open_login_page", lambda page, system: asyncio.sleep(0)),
        patch.object(cases_module, "screenshot", lambda page, run_id, case_id, name: asyncio.sleep(0)),
        patch.object(cases_module, "finalize_screenshots", lambda run_id, case_id, names, keep_archive: ["a.png"]),
        patch.object(cases_module, "get_asset_recorder", lambda page: _FakeRecorder()),
        patch.object(cases_module, "attach_asset_recorder", lambda page, run_id, case_id: _FakeRecorder()),
        patch.object(cases_module, "write_observed_asset", lambda rec, status: Path("/tmp/observed.json")),
        patch.object(cases_module, "is_logged_in", _async_return(False)),
        patch.object(cases_module, "save_storage_state", _async_return(None)),
        patch.object(cases_module, "CASE_RUNNERS", {"TC-ICM-FAKE": monkey_attempt_runner}),
    ]


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


class RetryLoopTests(unittest.TestCase):
    def setUp(self):
        self.db_path, self.conn, self.db_folder = _make_test_db()
        self._db_patchers = _patch_db(self.db_path, self.db_folder)
        for p in self._db_patchers:
            p.start()

    def tearDown(self):
        for p in self._db_patchers:
            p.stop()
        try:
            self.conn.close()
        except Exception:
            pass

    def _run_async(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)

    def test_max_retries_0_runs_once(self):
        calls = {"n": 0}

        async def runner(page, system, case):
            calls["n"] += 1
            # 正常通过
            return None

        patchers = _stub_dependencies(runner)
        for p in patchers:
            p.start()
        try:
            page = FakePage()
            result = self._run_async(
                cases_module.run_case(page, "rid-001", "TC-ICM-FAKE", keep_archive=False, max_retries=0)
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["attempts"], 1)
            self.assertEqual(calls["n"], 1)
            # 落库 1 行 attempt=1 passed=1
            with sqlite3.connect(str(self.db_path)) as conn:
                rows = conn.execute("select * from case_runs").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][1], "TC-ICM-FAKE")  # case_id
            self.assertEqual(rows[0][2], "rid-001")  # run_id
            self.assertEqual(rows[0][3], 1)  # passed
            self.assertEqual(rows[0][6], 1)  # attempt
        finally:
            for p in patchers:
                p.stop()

    def test_max_retries_2_runs_3_times_on_persistent_failure(self):
        calls = {"n": 0}

        async def runner(page, system, case):
            calls["n"] += 1
            raise RuntimeError(f"attempt {calls['n']} failed")

        patchers = _stub_dependencies(runner)
        for p in patchers:
            p.start()
        try:
            page = FakePage()
            result = self._run_async(
                cases_module.run_case(page, "rid-002", "TC-ICM-FAKE", keep_archive=False, max_retries=2)
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["attempts"], 3)  # 1 首次 + 2 retry
            self.assertEqual(calls["n"], 3)
            # attempt 1 + 2 + 3
            with sqlite3.connect(str(self.db_path)) as conn:
                rows = conn.execute(
                    "select attempt, passed from case_runs order by attempt"
                ).fetchall()
            self.assertEqual([r[0] for r in rows], [1, 2, 3])
            self.assertEqual([r[1] for r in rows], [0, 0, 0])
            # retry 日志含 retry exhausted
            log_path = self.db_folder / "runner-logs" / "rid-002.log"
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("retry exhausted", content)
            self.assertIn("attempts=3/3", content)
        finally:
            for p in patchers:
                p.stop()

    def test_retry_recovers_on_second_attempt(self):
        """第 2 次 attempt 成功 → 返回 passed，attempts=2"""
        calls = {"n": 0}

        async def runner(page, system, case):
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("transient network error")
            return None

        patchers = _stub_dependencies(runner)
        for p in patchers:
            p.start()
        try:
            page = FakePage()
            result = self._run_async(
                cases_module.run_case(page, "rid-003", "TC-ICM-FAKE", keep_archive=False, max_retries=3)
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["attempts"], 2)
            self.assertEqual(calls["n"], 2)
            with sqlite3.connect(str(self.db_path)) as conn:
                rows = conn.execute(
                    "select attempt, passed from case_runs order by attempt"
                ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], 1)
            self.assertEqual(rows[0][1], 0)
            self.assertEqual(rows[1][0], 2)
            self.assertEqual(rows[1][1], 1)
            # retry 日志含 "retry recovered"
            log_path = self.db_folder / "runner-logs" / "rid-003.log"
            self.assertTrue(log_path.exists())
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("retry recovered", content)
        finally:
            for p in patchers:
                p.stop()

    def test_max_retries_clamped_to_3(self):
        """run_case 自身也防御性 clamp max_retries 到 0~3"""
        calls = {"n": 0}

        async def runner(page, system, case):
            calls["n"] += 1
            raise RuntimeError("fail")

        patchers = _stub_dependencies(runner)
        for p in patchers:
            p.start()
        try:
            page = FakePage()
            result = self._run_async(
                cases_module.run_case(page, "rid-004", "TC-ICM-FAKE", keep_archive=False, max_retries=10)
            )
            # 10 被 clamp 到 3，所以 attempts=4（1+3）
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["attempts"], 4)
            self.assertEqual(calls["n"], 4)
        finally:
            for p in patchers:
                p.stop()

    def test_retry_clears_cookies_between_attempts(self):
        """attempt > 1 时应清空 cookies + goto about:blank"""
        calls = {"n": 0}

        async def runner(page, system, case):
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("transient")
            return None

        patchers = _stub_dependencies(runner)
        for p in patchers:
            p.start()
        try:
            page = FakePage()
            self._run_async(
                cases_module.run_case(page, "rid-005", "TC-ICM-FAKE", keep_archive=False, max_retries=2)
            )
            # attempt 2 触发清空
            self.assertGreaterEqual(page.clears, 1)
            self.assertIn("about:blank", page.gotos)
        finally:
            for p in patchers:
                p.stop()

    def test_max_retries_negative_clamps_to_0(self):
        """max_retries=-1 视为 0，只跑 1 次"""
        calls = {"n": 0}

        async def runner(page, system, case):
            calls["n"] += 1
            return None

        patchers = _stub_dependencies(runner)
        for p in patchers:
            p.start()
        try:
            page = FakePage()
            result = self._run_async(
                cases_module.run_case(page, "rid-006", "TC-ICM-FAKE", keep_archive=False, max_retries=-1)
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["attempts"], 1)
            self.assertEqual(calls["n"], 1)
        finally:
            for p in patchers:
                p.stop()


if __name__ == "__main__":
    unittest.main()
