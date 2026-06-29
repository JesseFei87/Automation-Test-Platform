"""资产流通闭环（路线 D · 增量）单测

覆盖：
- 正常路径：从 reports/agent-explore/{run_id}/candidate_flow.py 调端点
  → 断言返回 dict 中 draft.id > 0，DB case_drafts 表有该行
- 失败路径：run_id 不存在 → 404（无 candidate_flow.py）
- 失败路径：candidate_flow.py 内容为空 → 400
- 副作用：DB 行 requirement_id 默认指向 ensure_manual_requirement 的"测试点思维导图手工维护"
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from icm_platform import db


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


CANDIDATE_FLOW_TEMPLATE = '''from __future__ import annotations

from runner.browser import click_first, ensure_text_visible, fill_first, goto_route


async def run(page, system, case) -> None:
    # Generated from successful Agent exploration. Review before registration.
    await fill_first(page, ['input[placeholder="密码"]'], '123456')
'''


def _make_test_world():
    folder = tempfile.mkdtemp()
    root = Path(folder)
    db_path = root / "test.sqlite3"
    agent_dir = root / "reports" / "agent-explore"
    agent_dir.mkdir(parents=True)
    return root, db_path, agent_dir


@unittest.skipIf(
    _client_app is None or _test_client_cls is None,
    "FastAPI / httpx 依赖未安装，跳过端点测试",
)
class PromoteCandidateEndpointTests(unittest.TestCase):
    """POST /api/runs/{run_id}/agent-explore/promote-candidate 端点集成测试。"""

    def setUp(self):
        self.world = _make_test_world()
        self.root, self.db_path, self.agent_dir = self.world
        self._patchers = [
            patch("icm_platform.db.DB_PATH", self.db_path),
            patch("icm_platform.db.DATA_DIR", self.root),
            patch("icm_platform.api.ROOT", self.root),
            patch("icm_platform.api.TEST_CASE_DIR", self.root / "test-cases" / "icm"),
            patch("icm_platform.api.DRAFT_RUN_DIR", self.root / "reports" / "draft-runs"),
            patch("icm_platform.api.REPORT_DIR", self.root / "reports" / "runs"),
            patch("icm_platform.api.SCREENSHOTS_RUNS_DIR", self.root / "screenshots" / "runs"),
            patch("icm_platform.api.EVIDENCE_ROOT", self.root / "reports" / "evidence"),
            patch("icm_platform.api.TRACE_ROOT", self.root / "reports" / "traces"),
            patch("icm_platform.worker.DRAFT_RUN_DIR", self.root / "reports" / "draft-runs"),
            patch(
                "icm_platform.worker.get_platform_settings",
                lambda: {
                    "runner": {
                        "browser_mode": "visible",
                        "headless": False,
                        "screenshot_policy": "always_archive",
                        "batch_range": "TC-ICM-001..TC-ICM-002",
                    }
                },
            ),
        ]
        for p in self._patchers:
            p.start()
        db.init_db()

        from icm_platform import api as api_module
        self.api = api_module
        self.client = _test_client_cls(api_module.app)

        # 写入一份真实 candidate_flow.py（与 agent-explore 实际产物一致）
        self.run_id = "ui-test-promote-001"
        run_dir = self.agent_dir / self.run_id
        run_dir.mkdir(parents=True)
        (run_dir / "candidate_flow.py").write_text(
            CANDIDATE_FLOW_TEMPLATE, encoding="utf-8"
        )

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        shutil.rmtree(self.world[0], ignore_errors=True)

    # ---- 正常路径 ----
    def test_promote_candidate_returns_draft_with_positive_id(self):
        """真实 candidate_flow.py → 调端点 → 返回 CaseDraft 详情，id > 0。"""
        resp = self.client.post(f"/api/runs/{self.run_id}/agent-explore/promote-candidate")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIn("id", body)
        self.assertGreater(body["id"], 0)
        # 返回字段对齐 case_draft_detail：包含 status / title / yaml
        self.assertEqual(body["status"], "draft")
        self.assertEqual(body["title"], self.run_id)
        self.assertEqual(body.get("template"), "spec")

    def test_promote_candidate_inserts_row_in_case_drafts(self):
        """DB case_drafts 表能查到该行；requirement_id 指向 ensure_manual_requirement 默认 requirement。"""
        resp = self.client.post(f"/api/runs/{self.run_id}/agent-explore/promote-candidate")
        self.assertEqual(resp.status_code, 200, resp.text)
        draft_id = resp.json()["id"]

        requirement_id = self.api.ensure_manual_requirement()
        with db.connect() as conn:
            row = conn.execute(
                "select id, title, status, yaml, requirement_id from case_drafts where id = ?",
                (draft_id,),
            ).fetchone()
        self.assertIsNotNone(row, "case_drafts 表里应该能找到刚插入的行")
        self.assertEqual(row["status"], "draft")
        self.assertEqual(row["title"], self.run_id)
        self.assertEqual(row["requirement_id"], self.api.ensure_manual_requirement())
        # yaml 字段是合法 YAML，包含步骤骨架占位
        parsed = yaml.safe_load(row["yaml"])
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed.get("title"), self.run_id)
        self.assertEqual(parsed.get("template"), "spec")
        self.assertEqual(parsed.get("source_run_id"), self.run_id)
        self.assertEqual(parsed.get("status"), "draft")
        self.assertIn("steps", parsed)
        self.assertTrue(any("candidate_flow" in str(s) for s in parsed["steps"]))

    # ---- 失败路径 ----
    def test_promote_candidate_404_when_run_id_missing(self):
        """run_id 在 agent-explore 目录下不存在 → 404。"""
        resp = self.client.post("/api/runs/ui-no-such-run-9999/agent-explore/promote-candidate")
        self.assertEqual(resp.status_code, 404)
        detail = resp.json().get("detail", "")
        self.assertIn("candidate flow not found", str(detail))

    def test_promote_candidate_400_when_file_empty(self):
        """candidate_flow.py 存在但内容为空 → 400。"""
        run_id = "ui-test-empty-file"
        run_dir = self.agent_dir / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "candidate_flow.py").write_text("   \n\n  ", encoding="utf-8")
        resp = self.client.post(f"/api/runs/{run_id}/agent-explore/promote-candidate")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("empty", resp.json().get("detail", ""))

    def test_promote_regression_writes_formal_case_and_flow(self):
        """通过的草稿 Agent Explore 能一次性沉淀正式 YAML 和候选 Python flow。"""
        draft_dir = self.root / "reports" / "draft-runs" / self.run_id
        draft_dir.mkdir(parents=True)
        draft_yaml = (
            "id: TC-ICM-099\n"
            "system: icm-internal\n"
            "title: promoted draft\n"
            "status: draft\n"
            "steps:\n"
            "  - fill password\n"
            "expected_results:\n"
            "  - pass\n"
            "automation_asset:\n"
            "  operation_steps:\n"
            "    - fill password\n"
            "  selectors:\n"
            "    password: input[type='password']\n"
            "  input_values:\n"
            "    password: '123456'\n"
            "  assertions:\n"
            "    - password masked\n"
        )
        (draft_dir / "case.yaml").write_text(draft_yaml, encoding="utf-8")
        requirement_id = self.api.ensure_manual_requirement()
        with db.connect() as conn:
            conn.execute(
                """
                insert into run_tasks(id, mode, case_id, status, command, created_at, report_path)
                values (?, 'agent-explore', 'TC-ICM-099', 'passed', '', '2026-06-16T00:00:00Z', ?)
                """,
                (self.run_id, str(self.root / "reports" / "agent-explore" / self.run_id / "trace.json")),
            )
            conn.execute(
                """
                insert into case_drafts(requirement_id, title, yaml, status, created_at, updated_at)
                values (?, 'promoted draft', ?, 'draft', '2026-06-16T00:00:00Z', '2026-06-16T00:00:00Z')
                """,
                (requirement_id, draft_yaml),
            )
        (self.root / "reports" / "agent-explore" / self.run_id / "trace.json").write_text(
            '{"ok": true, "status": "passed", "history": []}', encoding="utf-8"
        )

        resp = self.client.post(f"/api/runs/{self.run_id}/agent-explore/promote-regression")

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["case_id"], "TC-ICM-099")
        self.assertTrue(Path(body["case_path"]).exists())
        self.assertTrue(Path(body["flow_path"]).exists())
        self.assertIn("fill_first", Path(body["flow_path"]).read_text(encoding="utf-8"))
        with db.connect() as conn:
            row = conn.execute("select status, promoted_case_id from case_drafts where promoted_case_id = 'TC-ICM-099'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "promoted")

    def test_promote_regression_is_idempotent_after_success(self):
        """同一条通过的草稿 Agent Explore 重复点击沉淀按钮，应返回已有正式用例。"""
        self.test_promote_regression_writes_formal_case_and_flow()

        resp = self.client.post(f"/api/runs/{self.run_id}/agent-explore/promote-regression")

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["case_id"], "TC-ICM-099")

    def test_promote_regression_returns_existing_case_by_source_run_id(self):
        """即使草稿状态不可靠，也按正式 YAML 的 source_run_id 防重复沉淀。"""
        case_dir = self.root / "test-cases" / "icm"
        flow_dir = self.root / "runner" / "flows"
        case_dir.mkdir(parents=True)
        flow_dir.mkdir(parents=True)
        for case_id in ("TC-ICM-013", "TC-ICM-014"):
            (case_dir / f"{case_id.lower()}-generated.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": case_id,
                        "system": "icm-internal",
                        "title": "duplicate",
                        "status": "formal",
                        "steps": ["step"],
                        "expected_results": ["ok"],
                        "source_run_id": self.run_id,
                        "automation_asset": {
                            "operation_steps": ["step"],
                            "selectors": {"a": "b"},
                            "input_values": {},
                            "assertions": ["ok"],
                        },
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (flow_dir / f"icm_case_{case_id.rsplit('-', 1)[-1].lower()}.py").write_text(CANDIDATE_FLOW_TEMPLATE, encoding="utf-8")
        draft_dir = self.root / "reports" / "draft-runs" / self.run_id
        draft_dir.mkdir(parents=True)
        draft_yaml = "id: LOGIN_EXC_002\nsystem: icm-internal\ntitle: duplicate\nstatus: draft\nsteps:\n- step\nexpected:\n- ok\n"
        (draft_dir / "case.yaml").write_text(draft_yaml, encoding="utf-8")
        requirement_id = self.api.ensure_manual_requirement()
        with db.connect() as conn:
            conn.execute(
                """
                insert into run_tasks(id, mode, case_id, status, command, created_at, report_path)
                values (?, 'agent-explore', 'LOGIN_EXC_002', 'passed', '', '2026-06-16T00:00:00Z', ?)
                """,
                (self.run_id, str(self.root / "reports" / "agent-explore" / self.run_id / "trace.json")),
            )
            conn.execute(
                """
                insert into case_drafts(requirement_id, title, yaml, status, promoted_case_id, created_at, updated_at)
                values (?, 'duplicate', ?, 'promoted', 'TC-ICM-014', '2026-06-16T00:00:00Z', '2026-06-16T00:00:00Z')
                """,
                (requirement_id, draft_yaml),
            )
        (self.root / "reports" / "agent-explore" / self.run_id / "trace.json").write_text(
            '{"ok": true, "status": "passed", "history": []}', encoding="utf-8"
        )

        resp = self.client.post(f"/api/runs/{self.run_id}/agent-explore/promote-regression")

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["case_id"], "TC-ICM-013")

    def test_promote_regression_reuses_existing_case_by_source_draft_case_id(self):
        case_dir = self.root / "test-cases" / "icm"
        flow_dir = self.root / "runner" / "flows"
        case_dir.mkdir(parents=True)
        flow_dir.mkdir(parents=True)
        existing_case_id = "TC-ICM-021"
        existing_case_path = case_dir / f"{existing_case_id.lower()}-generated.yaml"
        existing_flow_path = flow_dir / "icm_case_021.py"
        existing_case_path.write_text(
            yaml.safe_dump(
                {
                    "id": existing_case_id,
                    "system": "icm-internal",
                    "title": "old device create",
                    "status": "formal",
                    "source_draft_case_id": "ICMDEV_FUN_001",
                    "source_run_id": "ui-old-run",
                    "steps": ["old step"],
                    "expected_results": ["old ok"],
                    "automation_asset": {
                        "operation_steps": ["old step"],
                        "selectors": {"a": "b"},
                        "input_values": {},
                        "assertions": ["old ok"],
                    },
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        existing_flow_path.write_text("OLD_FLOW = True\n", encoding="utf-8")

        draft_dir = self.root / "reports" / "draft-runs" / self.run_id
        draft_dir.mkdir(parents=True)
        draft_yaml = (
            "id: ICMDEV_FUN_001\n"
            "system: icm-internal\n"
            "title: create device\n"
            "status: draft\n"
            "steps:\n- create device\n"
            "expected_results:\n- ok\n"
        )
        (draft_dir / "case.yaml").write_text(draft_yaml, encoding="utf-8")
        requirement_id = self.api.ensure_manual_requirement()
        with db.connect() as conn:
            conn.execute(
                """
                insert into run_tasks(id, mode, case_id, status, command, created_at, report_path)
                values (?, 'agent-explore', 'ICMDEV_FUN_001', 'passed', '', '2026-06-16T00:00:00Z', ?)
                """,
                (self.run_id, str(self.root / "reports" / "agent-explore" / self.run_id / "trace.json")),
            )
            conn.execute(
                """
                insert into case_drafts(requirement_id, title, yaml, status, created_at, updated_at)
                values (?, 'create device', ?, 'draft', '2026-06-16T00:00:00Z', '2026-06-16T00:00:00Z')
                """,
                (requirement_id, draft_yaml),
            )
        (self.root / "reports" / "agent-explore" / self.run_id / "trace.json").write_text(
            '{"ok": true, "status": "passed", "history": [{"decision": {"action": "goto", "url": "#/hubble/device"}}]}',
            encoding="utf-8",
        )
        (self.root / "reports" / "agent-explore" / self.run_id / "candidate_flow.py").write_text(
            CANDIDATE_FLOW_TEMPLATE,
            encoding="utf-8",
        )

        resp = self.client.post(f"/api/runs/{self.run_id}/agent-explore/promote-regression")

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["case_id"], existing_case_id)
        self.assertIn("source_run_id", existing_case_path.read_text(encoding="utf-8"))
        self.assertNotIn("OLD_FLOW = True", existing_flow_path.read_text(encoding="utf-8"))

    def test_self_heal_agent_explore_creates_child_run(self):
        draft_dir = self.root / "reports" / "draft-runs" / self.run_id
        draft_dir.mkdir(parents=True)
        (draft_dir / "case.yaml").write_text(
            "id: LOGIN_FUN_003\nsystem: icm-internal\ntitle: login persists\nsteps:\n- submit login\nexpected_results:\n- still logged in\n",
            encoding="utf-8",
        )
        trace_path = self.root / "reports" / "agent-explore" / self.run_id / "trace.json"
        trace_path.write_text(
            '{"ok": false, "status": "failed", "error": "unknown ref: empty", "history": [{"step": 5, "decision": {"action": "press", "ref": ""}, "execution": {"error": "unknown ref: empty"}}], "evidence": {"events": {"latest": []}}}',
            encoding="utf-8",
        )
        with db.connect() as conn:
            conn.execute(
                """
                insert into run_tasks(id, mode, case_id, status, command, created_at, report_path)
                values (?, 'agent-explore', 'LOGIN_FUN_003', 'failed', '', '2026-06-17T00:00:00Z', ?)
                """,
                (self.run_id, str(trace_path)),
            )

        resp = self.client.post(f"/api/runs/{self.run_id}/agent-explore/self-heal")

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["parent_run_id"], self.run_id)
        self.assertEqual(body["trigger"], "self_heal")
        child_run_id = body["id"]
        with db.connect() as conn:
            row = conn.execute("select * from run_tasks where id = ?", (child_run_id,)).fetchone()
        self.assertEqual(row["parent_run_id"], self.run_id)
        self.assertEqual(row["trigger"], "self_heal")
        self.assertTrue((self.root / "reports" / "draft-runs" / child_run_id / "case.yaml").exists())
        self.assertTrue((self.root / "reports" / "draft-runs" / child_run_id / "healing-context.json").exists())

    def test_self_heal_rejects_non_agent_run(self):
        with db.connect() as conn:
            conn.execute(
                """
                insert into run_tasks(id, mode, case_id, status, command, created_at)
                values ('ui-worker-001', 'run-case', 'TC-ICM-001', 'failed', '', '2026-06-17T00:00:00Z')
                """
            )

        resp = self.client.post("/api/runs/ui-worker-001/agent-explore/self-heal")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("self heal", resp.json().get("detail", ""))

    def test_delete_run_removes_rows_and_execution_artifacts(self):
        run_id = "ui-delete-001"
        report_path = self.root / "reports" / "runs" / f"{run_id}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("# report", encoding="utf-8")
        (self.root / "reports" / "agent-explore" / run_id).mkdir(parents=True, exist_ok=True)
        (self.root / "reports" / "agent-explore" / run_id / "trace.json").write_text("{}", encoding="utf-8")
        (self.root / "reports" / "draft-runs" / run_id).mkdir(parents=True, exist_ok=True)
        (self.root / "reports" / "draft-runs" / run_id / "case.yaml").write_text("id: A", encoding="utf-8")
        (self.root / "reports" / "step-details").mkdir(parents=True, exist_ok=True)
        (self.root / "reports" / "step-details" / f"{run_id}.json").write_text("{}", encoding="utf-8")
        (self.root / "reports" / "evidence" / run_id).mkdir(parents=True, exist_ok=True)
        (self.root / "reports" / "evidence" / run_id / "events.jsonl").write_text("", encoding="utf-8")
        (self.root / "reports" / "traces" / run_id).mkdir(parents=True, exist_ok=True)
        (self.root / "reports" / "traces" / run_id / "trace.zip").write_text("zip", encoding="utf-8")
        (self.root / "screenshots" / "runs" / run_id).mkdir(parents=True, exist_ok=True)
        (self.root / "screenshots" / "runs" / run_id / "01.png").write_text("png", encoding="utf-8")
        with db.connect() as conn:
            conn.execute(
                """
                insert into run_tasks(id, mode, case_id, status, command, created_at, report_path)
                values (?, 'agent-explore', 'LOGIN_FUN_003', 'failed', '', '2026-06-17T00:00:00Z', ?)
                """,
                (run_id, str(report_path)),
            )
            conn.execute(
                """
                insert into run_logs(run_id, stream, line, created_at)
                values (?, 'stdout', 'line', '2026-06-17T00:00:01Z')
                """,
                (run_id,),
            )

        resp = self.client.delete(f"/api/runs/{run_id}")

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["run_id"], run_id)
        self.assertTrue(body["ok"])
        with db.connect() as conn:
            task = conn.execute("select * from run_tasks where id = ?", (run_id,)).fetchone()
            logs = conn.execute("select * from run_logs where run_id = ?", (run_id,)).fetchall()
        self.assertIsNone(task)
        self.assertEqual(logs, [])
        self.assertFalse(report_path.exists())
        self.assertFalse((self.root / "reports" / "agent-explore" / run_id).exists())
        self.assertFalse((self.root / "reports" / "draft-runs" / run_id).exists())
        self.assertFalse((self.root / "reports" / "step-details" / f"{run_id}.json").exists())
        self.assertFalse((self.root / "reports" / "evidence" / run_id).exists())
        self.assertFalse((self.root / "reports" / "traces" / run_id).exists())
        self.assertFalse((self.root / "screenshots" / "runs" / run_id).exists())


if __name__ == "__main__":
    unittest.main()
