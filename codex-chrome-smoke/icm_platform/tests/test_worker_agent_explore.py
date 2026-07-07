from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icm_platform import db
from icm_platform.api import RunRequest
from icm_platform.worker import ROOT, RunnerWorker


RUNNER_SETTINGS = {
    "browser_mode": "visible",
    "headless": False,
    "screenshot_policy": "always_archive",
    "batch_range": "TC-ICM-001..TC-ICM-002",
}


class AgentExploreWorkerTests(unittest.TestCase):
    def test_enqueue_agent_explore_requires_case_and_records_runner_command(self) -> None:
        with isolated_db() as db_path:
            worker = RunnerWorker()

            task = worker.enqueue("agent-explore", case_id="TC-ICM-013")

            self.assertEqual(task["mode"], "agent-explore")
            self.assertEqual(task["case_id"], "TC-ICM-013")
            with db.connect() as conn:
                row = conn.execute("select * from run_tasks where id = ?", (task["id"],)).fetchone()
            self.assertEqual(row["case_id"], "TC-ICM-013")
            self.assertIn("runner.main agent-explore TC-ICM-013", row["command"])
            self.assertIn(str(task["id"]), row["command"])
            self.assertEqual(db_path.exists(), True)

    def test_enqueue_agent_explore_rejects_missing_case_id(self) -> None:
        with isolated_db():
            with self.assertRaisesRegex(ValueError, "case_id is required for agent-explore"):
                RunnerWorker().enqueue("agent-explore")

    def test_enqueue_agent_explore_accepts_draft_id_and_records_yaml_path(self) -> None:
        with isolated_db() as db_path:
            with db.connect() as conn:
                conn.execute(
                    """
                    insert into requirements(title, document, status, created_at, updated_at)
                    values ('req', 'doc', 'draft', '2026-06-15T00:00:00Z', '2026-06-15T00:00:00Z')
                    """
                )
                requirement_id = conn.execute("select id from requirements").fetchone()["id"]
                conn.execute(
                    """
                    insert into case_drafts(requirement_id, title, yaml, status, created_at, updated_at)
                    values (?, 'draft case', 'id: DRAFT-AG-1
system: icm-internal
title: Draft AG
steps:
  - Open page
expected_results:
  - Page is visible
', 'draft', '2026-06-15T00:00:00Z', '2026-06-15T00:00:00Z')
                    """,
                    (requirement_id,),
                )
                draft_id = conn.execute("select id from case_drafts").fetchone()["id"]

            task = RunnerWorker().enqueue("agent-explore", draft_id=draft_id)

            with db.connect() as conn:
                row = conn.execute("select * from run_tasks where id = ?", (task["id"],)).fetchone()
            self.assertEqual(task["case_id"], "DRAFT-AG-1")
            self.assertEqual(row["case_id"], "DRAFT-AG-1")
            self.assertIn("runner.main agent-explore", row["command"])
            self.assertIn(str(db_path.parent / "draft_runs" / task["id"] / "case.yaml"), row["command"])

    def test_enqueue_agent_explore_infers_external_system_and_project_url_for_non_icm_draft(self) -> None:
        with isolated_db() as db_path:
            with db.connect() as conn:
                conn.execute(
                    """
                    insert into project_profiles(id, name, base_url, description, created_at, updated_at)
                    values ('proj-search', 'MyProject', 'https://bing.com', '', '2026-06-15T00:00:00Z', '2026-06-15T00:00:00Z')
                    """
                )
                conn.execute(
                    """
                    insert into requirements(title, document, status, project_id, created_at, updated_at)
                    values ('req', 'doc', 'draft', 'proj-search', '2026-06-15T00:00:00Z', '2026-06-15T00:00:00Z')
                    """
                )
                requirement_id = conn.execute("select id from requirements").fetchone()["id"]
                conn.execute(
                    """
                    insert into case_drafts(requirement_id, title, yaml, status, created_at, updated_at)
                    values (?, 'draft case', 'id: SEARCH_FUN_001
title: Search
steps:
  - Open bing
expected_results:
  - Search results visible
', 'draft', '2026-06-15T00:00:00Z', '2026-06-15T00:00:00Z')
                    """,
                    (requirement_id,),
                )
                draft_id = conn.execute("select id from case_drafts").fetchone()["id"]

            task = RunnerWorker().enqueue("agent-explore", draft_id=draft_id)
            draft_path = db_path.parent / "draft_runs" / task["id"] / "case.yaml"

            payload = draft_path.read_text(encoding="utf-8")

        self.assertIn("system: external-template", payload)
        self.assertIn("env_url: https://bing.com", payload)

    def test_enqueue_agent_self_heal_writes_child_draft_and_metadata(self) -> None:
        with isolated_db() as db_path:
            worker = RunnerWorker()
            task = worker.enqueue_agent_self_heal(
                "ui-parent-001",
                "id: LOGIN_FUN_003\nsystem: icm-internal\ntitle: login\nsteps:\n  - submit login\nexpected_results:\n  - login success\n",
                {
                    "parent_run_id": "ui-parent-001",
                    "trigger": "self_heal",
                    "failure_summary": "unknown ref: empty",
                    "healing_hint": "finish once login success signal appears",
                },
                case_id="LOGIN_FUN_003",
            )

            draft_dir = db_path.parent / "draft_runs" / task["id"]
            self.assertTrue((draft_dir / "case.yaml").exists())
            self.assertTrue((draft_dir / "healing-context.json").exists())
            with db.connect() as conn:
                row = conn.execute("select * from run_tasks where id = ?", (task["id"],)).fetchone()
            self.assertEqual(row["parent_run_id"], "ui-parent-001")
            self.assertEqual(row["trigger"], "self_heal")
            self.assertEqual(row["case_id"], "LOGIN_FUN_003")
            self.assertEqual(Path(row["healing_context_path"]).name, "healing-context.json")

    def test_run_agent_explore_invokes_runner_with_case_id_and_task_id(self) -> None:
        commands: list[list[str]] = []

        class FakeProcess:
            stdout = []

            def __init__(self, command: list[str], **_: object) -> None:
                commands.append(command)

            def wait(self) -> int:
                return 0

        with isolated_db():
            with db.connect() as conn:
                conn.execute(
                    """
                    insert into run_tasks(id, mode, case_id, status, command, created_at)
                    values ('ui-agent', 'agent-explore', 'TC-ICM-013', 'queued', '', '2026-06-15T00:00:00Z')
                    """
                )
            with patch("icm_platform.worker.subprocess.Popen", FakeProcess):
                RunnerWorker()._run("ui-agent")

        self.assertEqual(
            commands[0],
            [
                sys.executable,
                "-m",
                "runner.main",
                "agent-explore",
                "TC-ICM-013",
                "ui-agent",
                "--screenshot-policy",
                "always_archive",
                "--batch-range",
                "TC-ICM-001..TC-ICM-002",
            ],
        )

    def test_run_agent_explore_prefers_prepared_draft_yaml_path(self) -> None:
        commands: list[list[str]] = []

        class FakeProcess:
            stdout = []

            def __init__(self, command: list[str], **_: object) -> None:
                commands.append(command)

            def wait(self) -> int:
                return 0

        with isolated_db() as db_path:
            draft_path = db_path.parent / "draft_runs" / "ui-agent" / "case.yaml"
            draft_path.parent.mkdir(parents=True, exist_ok=True)
            draft_path.write_text("id: DRAFT-AG-1\nsystem: icm-internal\n", encoding="utf-8")
            with db.connect() as conn:
                conn.execute(
                    """
                    insert into run_tasks(id, mode, case_id, status, command, created_at)
                    values ('ui-agent', 'agent-explore', 'DRAFT-AG-1', 'queued', '', '2026-06-15T00:00:00Z')
                    """
                )
            with patch("icm_platform.worker.subprocess.Popen", FakeProcess):
                RunnerWorker()._run("ui-agent")

        self.assertEqual(commands[0][4], str(draft_path))

    def test_resolve_agent_explore_trace_path(self) -> None:
        with isolated_db():
            trace_path = ROOT / "reports" / "agent-explore" / "ui-agent" / "trace.json"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text("{}", encoding="utf-8")

            resolved = RunnerWorker()._resolve_report_path("ui-agent", "agent-explore", "TC-ICM-013")

        self.assertEqual(resolved, trace_path)
        trace_path.unlink(missing_ok=True)

    def test_api_run_request_accepts_agent_explore_mode(self) -> None:
        payload = RunRequest(mode="agent-explore", case_id="TC-ICM-013")

        self.assertEqual(payload.mode, "agent-explore")
        self.assertEqual(payload.case_id, "TC-ICM-013")

    def test_batch_progress_events_create_child_run_tasks(self) -> None:
        with isolated_db():
            with db.connect() as conn:
                conn.execute(
                    """
                    insert into run_tasks(id, mode, case_id, status, command, created_at)
                    values ('ui-batch', 'run-batch', null, 'running', '', '2026-06-26T00:00:00Z')
                    """
                )
            worker = RunnerWorker()
            worker._handle_batch_progress("ui-batch", "::batch-case-start run_id=ui-batch-tc-icm-001 case_id=TC-ICM-001")
            worker._handle_batch_progress("ui-batch", "::batch-case-end run_id=ui-batch-tc-icm-001 case_id=TC-ICM-001 status=passed")

            with db.connect() as conn:
                row = conn.execute("select * from run_tasks where id = 'ui-batch-tc-icm-001'").fetchone()

        self.assertEqual(row["parent_run_id"], "ui-batch")
        self.assertEqual(row["case_id"], "TC-ICM-001")
        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["return_code"], 0)


class isolated_db:
    def __init__(self) -> None:
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        self._patches: list[object] = []
        self.db_path: Path | None = None

    def __enter__(self) -> Path:
        self._tempdir = tempfile.TemporaryDirectory()
        root = Path(self._tempdir.name)
        self.db_path = root / "test.sqlite3"
        self._patches = [
            patch("icm_platform.db.DB_PATH", self.db_path),
            patch("icm_platform.db.DATA_DIR", root),
            patch("icm_platform.worker.DRAFT_RUN_DIR", root / "draft_runs"),
            patch("icm_platform.worker.get_platform_settings", lambda: {"runner": RUNNER_SETTINGS}),
        ]
        for item in self._patches:
            item.start()
        db.init_db()
        return self.db_path

    def __exit__(self, *_: object) -> None:
        for item in reversed(self._patches):
            item.stop()
        if self._tempdir:
            self._tempdir.cleanup()


if __name__ == "__main__":
    unittest.main()
