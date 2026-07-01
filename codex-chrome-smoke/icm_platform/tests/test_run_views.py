from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icm_platform import db
from icm_platform import api as api_module
from icm_platform.worker import RunnerWorker
from icm_platform.run_views import summarize_run_task
from runner.main import cases_for_batch


class RunViewTests(unittest.TestCase):
    def test_synthetic_agent_logs_include_complete_evidence_history(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            evidence_root = Path(folder) / "evidence"
            run_root = evidence_root / "ui-full-log"
            run_root.mkdir(parents=True)
            events = [
                {
                    "kind": "screenshot",
                    "message": f"captured screenshot agent-step-{index:02d}.png",
                    "created_at": f"2026-06-30T09:38:{index:02d}Z",
                    "url": "https://example.test/page",
                }
                for index in range(1, 16)
            ]
            (run_root / "events.jsonl").write_text(
                "\n".join(json.dumps(item) for item in events) + "\n",
                encoding="utf-8",
            )
            (run_root / "console.jsonl").write_text("", encoding="utf-8")

            with patch("icm_platform.api.EVIDENCE_ROOT", evidence_root):
                logs = api_module._synthetic_logs_from_evidence("ui-full-log")

        self.assertEqual(len(logs), 15)
        self.assertIn("agent-step-01.png", logs[0]["line"])
        self.assertIn("agent-step-15.png", logs[-1]["line"])

    def test_runner_batch_range_parser(self) -> None:
        self.assertEqual(cases_for_batch("TC-ICM-001..TC-ICM-003"), ["TC-ICM-001", "TC-ICM-002", "TC-ICM-003"])
        self.assertEqual(cases_for_batch("TC-ICM-006"), ["TC-ICM-006"])
        self.assertEqual(cases_for_batch("TC-ICM-002, TC-ICM-004"), ["TC-ICM-002", "TC-ICM-004"])

    def test_worker_builds_runner_args_from_settings(self) -> None:
        args = RunnerWorker()._runner_args(
            {
                "browser_mode": "background",
                "headless": True,
                "screenshot_policy": "always_archive",
                "batch_range": "TC-ICM-006..TC-ICM-011",
            }
        )

        self.assertIn("--headless", args)
        self.assertEqual(args[args.index("--screenshot-policy") + 1], "always_archive")
        self.assertEqual(args[args.index("--batch-range") + 1], "TC-ICM-006..TC-ICM-011")

    def test_worker_browser_mode_overrides_legacy_headless_flag(self) -> None:
        args = RunnerWorker()._runner_args(
            {
                "browser_mode": "visible",
                "headless": True,
                "screenshot_policy": "latest_plus_failed_archive",
                "batch_range": "TC-ICM-001..TC-ICM-012",
            }
        )

        self.assertNotIn("--headless", args)

    def test_worker_prepares_draft_run_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / "test.sqlite3"
            draft_run_dir = root / "draft-runs"
            with (
                patch("icm_platform.db.DB_PATH", db_path),
                patch("icm_platform.db.DATA_DIR", db_path.parent),
                patch("icm_platform.worker.DRAFT_RUN_DIR", draft_run_dir),
            ):
                db.init_db()
                with db.connect() as conn:
                    conn.execute(
                        """
                        insert into requirements(id, title, document, status, created_at, updated_at)
                        values (1, 'req', 'doc', 'draft', '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z')
                        """
                    )
                    conn.execute(
                        """
                        insert into case_drafts(id, requirement_id, title, yaml, status, created_at, updated_at)
                        values (7, 1, 'draft case', 'id: TC-ICM-001\nsystem: icm-internal\ntitle: Draft run\n', 'draft', '2026-06-12T00:00:00Z', '2026-06-12T00:00:00Z')
                        """
                    )
                task = RunnerWorker().enqueue("run-draft", draft_id=7)
                draft_path = draft_run_dir / task["id"] / "case.yaml"

                self.assertEqual(task["mode"], "run-draft")
                self.assertEqual(task["case_id"], "TC-ICM-001")
                self.assertTrue(draft_path.exists())
                self.assertIn("id: TC-ICM-001", draft_path.read_text(encoding="utf-8"))

    def test_summarizes_running_task_for_execution_center(self) -> None:
        summary = summarize_run_task(
            {
                "id": "ui-123",
                "mode": "run-case",
                "case_id": "TC-ICM-012",
                "status": "running",
                "created_at": "2026-06-05T01:00:00Z",
                "started_at": "2026-06-05T01:01:00Z",
                "finished_at": None,
                "report_path": None,
                "error": None,
            }
        )

        self.assertEqual(summary["display_name"], "TC-ICM-012")
        self.assertEqual(summary["status_label"], "Running")
        self.assertTrue(summary["is_active"])
        self.assertFalse(summary["artifact_ready"])

    def test_summarizes_finished_batch_with_report_artifact(self) -> None:
        summary = summarize_run_task(
            {
                "id": "ui-batch",
                "mode": "run-batch",
                "case_id": None,
                "status": "passed",
                "created_at": "2026-06-05T01:00:00Z",
                "started_at": "2026-06-05T01:01:00Z",
                "finished_at": "2026-06-05T01:03:05Z",
                "report_path": "reports/runs/ui-batch-tc-icm-012.md",
                "error": "",
            }
        )

        self.assertEqual(summary["display_name"], "Batch 001-012")
        self.assertEqual(summary["status_label"], "Passed")
        self.assertFalse(summary["is_active"])
        self.assertTrue(summary["artifact_ready"])
        self.assertEqual(summary["duration_label"], "02:05")

    def test_report_screenshots_include_run_archive_without_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run_dir = root / "ui-agent"
            run_dir.mkdir(parents=True)
            (run_dir / "01-entry.png").write_bytes(b"png")

            with patch.object(api_module, "SCREENSHOTS_RUNS_DIR", root):
                screenshots = api_module._report_screenshots({"id": "ui-agent", "case_id": "TC-ICM-001"}, "")

        self.assertEqual(len(screenshots), 1)
        self.assertEqual(screenshots[0]["url"], "/api/screenshots/runs/ui-agent/01-entry.png")

    def test_agent_run_uses_evidence_as_log_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            evidence_root = root / "evidence"
            run_root = evidence_root / "ui-agent"
            run_root.mkdir(parents=True, exist_ok=True)
            (run_root / "events.jsonl").write_text(
                '{"created_at":"2026-06-16T10:00:00Z","kind":"agent_action","message":"executed fill","value":"test","url":"https://example.test/login"}\n',
                encoding="utf-8",
            )
            (run_root / "console.jsonl").write_text(
                '{"created_at":"2026-06-16T10:00:01Z","level":"info","text":"after login click"}\n',
                encoding="utf-8",
            )
            (run_root / "network.jsonl").write_text("", encoding="utf-8")

            with (
                patch.object(api_module, "EVIDENCE_ROOT", evidence_root),
                patch.object(api_module, "TRACE_ROOT", root / "traces"),
                patch("runner.evidence_recorder.ROOT", root),
                patch("runner.evidence_recorder.EVIDENCE_ROOT", evidence_root),
                patch("runner.evidence_recorder.TRACE_ROOT", root / "traces"),
            ):
                logs = api_module._synthetic_logs_from_evidence("ui-agent")

        self.assertEqual(len(logs), 2)
        self.assertIn("executed fill", logs[0]["line"])
        self.assertIn("after login click", logs[1]["line"])

    def test_build_agent_steps_prefers_case_step_titles_for_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            draft_run_dir = root / "draft-runs"
            run_id = "ui-agent-case-step"
            run_dir = draft_run_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "case.yaml").write_text(
                "\n".join(
                    [
                        "id: ICMDEV_FUN_001",
                        "system: icm-internal",
                        "steps:",
                        "  - 1. 访问登录页并使用 admin 登录",
                        "  - 2. 在左侧导航栏点击 ICM，再点击设备信息",
                    ]
                ),
                encoding="utf-8",
            )
            agent_explore = {
                "trace": {
                    "ok": False,
                    "final_url": "https://example.test/#/index",
                    "history": [
                        {
                            "step": 1,
                            "decision": {"action": "fill", "ref": "e2", "value": "admin", "reason": "fill username from case test data"},
                            "observation": {"url": "https://example.test/#/login", "visibleText": ["登录"], "interactives": [{"ref": "e2", "text": "账号", "selector": "#username"}]},
                            "execution": {"result": "filled"},
                        },
                        {
                            "step": 2,
                            "decision": {"action": "click", "ref": "e5", "reason": "click ICM in left sidebar and open device information"},
                            "observation": {"url": "https://example.test/#/index", "visibleText": ["ICM", "设备信息"], "interactives": [{"ref": "e5", "text": "ICM | 设备信息", "selector": ".el-submenu__title"}]},
                            "execution": {"result": "clicked"},
                        },
                    ],
                }
            }
            with patch.object(api_module, "DRAFT_RUN_DIR", draft_run_dir):
                steps = api_module._build_agent_steps(agent_explore, [], [], run_id, {"case_id": "ICMDEV_FUN_001"})

        self.assertEqual(steps[0]["title"], "用例步骤 1 - 访问登录页并使用 admin 登录")
        self.assertEqual(steps[1]["title"], "用例步骤 2 - 在左侧导航栏点击 ICM，再点击设备信息")
        self.assertIn("点击", steps[1]["summary"])

    def test_build_agent_steps_maps_login_actions_to_following_case_steps(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            draft_run_dir = root / "draft-runs"
            run_id = "ui-agent-login-step"
            run_dir = draft_run_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "case.yaml").write_text(
                "\n".join(
                    [
                        "id: LOGIN_FUN_002",
                        "system: icm-internal",
                        "steps:",
                        "  - 1. 访问 https://example.test/#/login?redirect=%2Fredirect",
                        "  - 2. 输入账号 test 密码 123456",
                        "  - 3. 点击【登录】按钮",
                    ]
                ),
                encoding="utf-8",
            )
            agent_explore = {
                "trace": {
                    "ok": False,
                    "history": [
                        {
                            "step": 1,
                            "decision": {"action": "fill", "ref": "e2", "value": "test", "reason": "fill username from case test data"},
                            "observation": {"url": "https://example.test/#/login", "visibleText": ["登录"], "interactives": [{"ref": "e2", "text": "账号", "selector": "#username"}]},
                            "execution": {"result": "filled"},
                        },
                        {
                            "step": 2,
                            "decision": {"action": "fill", "ref": "e3", "value": "123456", "reason": "fill password from case test data"},
                            "observation": {"url": "https://example.test/#/login", "visibleText": ["登录"], "interactives": [{"ref": "e3", "text": "密码", "selector": "#password"}]},
                            "execution": {"result": "filled"},
                        },
                        {
                            "step": 3,
                            "decision": {"action": "click", "ref": "e4", "reason": "click the 登录 button to submit login form"},
                            "observation": {"url": "https://example.test/#/login", "visibleText": ["登录"], "interactives": [{"ref": "e4", "text": "登录", "selector": "#login"}]},
                            "execution": {"result": "clicked"},
                        },
                        {
                            "step": 4,
                            "decision": {"action": "wait", "ref": "", "reason": "waiting for login to complete and redirect to /redirect page"},
                            "observation": {"url": "https://example.test/#/login", "visibleText": ["登录中..."], "interactives": []},
                            "execution": {"result": "waited"},
                        },
                    ],
                }
            }
            with patch.object(api_module, "DRAFT_RUN_DIR", draft_run_dir):
                steps = api_module._build_agent_steps(agent_explore, [], [], run_id, {"case_id": "LOGIN_FUN_002"})

        self.assertEqual(steps[0]["title"], "用例步骤 2 - 输入账号 test 密码 123456")
        self.assertEqual(steps[1]["title"], "用例步骤 2 - 输入账号 test 密码 123456")
        self.assertEqual(steps[2]["title"], "用例步骤 3 - 点击【登录】按钮")
        self.assertEqual(steps[3]["summary"], "等待登录完成并跳转到目标页面")


    def test_build_agent_steps_uses_stage_source_steps_first(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            draft_run_dir = root / "draft-runs"
            run_id = "ui-agent-stage-step"
            run_dir = draft_run_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "case.yaml").write_text(
                "\n".join(
                    [
                        "id: ICMDEV_FUN_001",
                        "system: icm-internal",
                        "steps:",
                        "  - 登录系统",
                        "  - 进入设备信息页面",
                        "  - 填写新增设备表单",
                        "  - 点击确定并断言新增成功",
                    ]
                ),
                encoding="utf-8",
            )
            agent_explore = {
                "trace": {
                    "ok": True,
                    "plan": {
                        "stages": [
                            {"stage_id": "stage-login", "source_steps": [1]},
                            {"stage_id": "stage-nav", "source_steps": [2]},
                            {"stage_id": "stage-form", "source_steps": [3]},
                            {"stage_id": "stage-assert", "source_steps": [4]},
                        ]
                    },
                    "history": [
                        {"step": 1, "stage_id": "stage-login", "decision": {"action": "fill", "reason": "login"}, "observation": {}, "execution": {"result": "ok"}},
                        {"step": 2, "stage_id": "stage-nav", "decision": {"action": "goto", "reason": "open device"}, "observation": {}, "execution": {"result": "ok"}},
                        {"step": 3, "stage_id": "stage-form", "decision": {"action": "click", "reason": "submit dialog"}, "observation": {}, "execution": {"result": "ok"}},
                        {"step": 4, "stage_id": "stage-assert", "decision": {"action": "assert_text", "reason": "assert result"}, "observation": {}, "execution": {"result": "ok"}},
                    ],
                }
            }
            with patch.object(api_module, "DRAFT_RUN_DIR", draft_run_dir):
                steps = api_module._build_agent_steps(agent_explore, [], [], run_id, {"case_id": "ICMDEV_FUN_001"})

        self.assertEqual(
            [step["title"] for step in steps],
            [
                "用例步骤 1 - 登录系统",
                "用例步骤 2 - 进入设备信息页面",
                "用例步骤 3 - 填写新增设备表单",
                "用例步骤 4 - 点击确定并断言新增成功",
            ],
        )

    def test_build_agent_steps_prefers_step_screenshot_name(self) -> None:
        agent_explore = {
            "trace": {
                "ok": True,
                "history": [
                    {"step": 1, "decision": {"action": "click"}, "observation": {}, "execution": {"result": "ok", "screenshot_name": "agent-step-02.png"}},
                    {"step": 2, "decision": {"action": "click"}, "observation": {}, "execution": {"result": "ok", "screenshot_name": "agent-step-01.png"}},
                ],
            }
        }
        screenshots = [
            {"filename": "agent-step-01.png", "url": "/api/screenshots/runs/ui/agent-step-01.png"},
            {"filename": "agent-step-02.png", "url": "/api/screenshots/runs/ui/agent-step-02.png"},
        ]

        steps = api_module._build_agent_steps(agent_explore, [], screenshots, "ui-agent", {"case_id": "ICMDEV_BND_003"})

        self.assertEqual(steps[0]["screenshot_url"], "/api/screenshots/runs/ui/agent-step-02.png")
        self.assertEqual(steps[1]["screenshot_url"], "/api/screenshots/runs/ui/agent-step-01.png")

    def test_build_agent_steps_maps_stage_local_steps_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            draft_run_dir = root / "draft-runs"
            run_id = "ui-agent-local-step"
            run_dir = draft_run_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "case.yaml").write_text(
                "\n".join(
                    [
                        "id: ICMDEV_BND_003",
                        "system: icm-internal",
                        "steps:",
                        "  - 打开添加设备信息弹窗",
                        "  - 在设备名称输入框输入16个字符BCDEFGHIJKLMNOPQ",
                        "  - 填写其他必填合法字段",
                        "  - 点击【确定】",
                    ]
                ),
                encoding="utf-8",
            )
            agent_explore = {
                "trace": {
                    "ok": True,
                    "plan": {"stages": [{"stage_id": "stage-3", "source_steps": [1, 2, 3, 4]}]},
                    "history": [
                        {"step": 1, "stage_id": "stage-3", "stage_local_step": 1, "decision": {"action": "click", "reason": "打开弹窗"}, "observation": {}, "execution": {"result": "dialog_opened", "screenshot_name": "agent-step-01.png"}},
                        {"step": 2, "stage_id": "stage-3", "stage_local_step": 2, "decision": {"action": "fill", "value": "BCDEFGHIJKLMNOPQ", "reason": "填写设备名称"}, "observation": {}, "execution": {"result": "device_name_filled", "screenshot_name": "agent-step-02.png"}},
                    ],
                }
            }
            screenshots = [
                {"filename": "agent-step-01.png", "url": "/api/screenshots/runs/ui/agent-step-01.png"},
                {"filename": "agent-step-02.png", "url": "/api/screenshots/runs/ui/agent-step-02.png"},
            ]
            with patch.object(api_module, "DRAFT_RUN_DIR", draft_run_dir):
                steps = api_module._build_agent_steps(agent_explore, [], screenshots, run_id, {"case_id": "ICMDEV_BND_003"})

        self.assertEqual(steps[0]["title"], "用例步骤 1 - 打开添加设备信息弹窗")
        self.assertEqual(steps[1]["title"], "用例步骤 2 - 在设备名称输入框输入16个字符BCDEFGHIJKLMNOPQ")
        self.assertEqual(steps[1]["command_output"], [
            "[action] 在设备名称输入框输入16个字符BCDEFGHIJKLMNOPQ",
            "[result] device_name_filled",
            "[value] BCDEFGHIJKLMNOPQ",
            "[screenshot] agent-step-02.png",
        ])

    def test_build_agent_steps_marks_last_step_failed_when_trace_failed_without_step_error(self) -> None:
        agent_explore = {
            "trace": {
                "ok": False,
                "status": "failed",
                "error": "no assertion signal matched on current page",
                "history": [
                    {"step": 1, "decision": {"action": "click", "reason": "open dialog"}, "observation": {}, "execution": {"result": "dialog_opened"}},
                    {"step": 2, "decision": {"action": "assert_text", "reason": "verify error tip"}, "observation": {}, "execution": {"result": "assert_checked"}},
                ],
            }
        }

        steps = api_module._build_agent_steps(agent_explore, [], [], "ui-agent-failed", {"case_id": "ICMDEV_EXC_009"})

        self.assertEqual(steps[0]["status"], "completed")
        self.assertEqual(steps[1]["status"], "failed")

    def test_build_unified_run_detail_exposes_agent_stage_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / "test.sqlite3"
            report_root = root / "reports"
            agent_root = report_root / "agent-explore" / "ui-agent-stage"
            agent_root.mkdir(parents=True, exist_ok=True)
            (agent_root / "trace.json").write_text(
                """
                {
                  "ok": false,
                  "status": "running",
                  "plan": {"planner_version": "v1", "case_id": "ICMDEV_FUN_001", "stages": [{"stage_id": "stage-1", "index": 1, "name": "登录系统", "scene_type": "login", "strategy": "login_guard"}]},
                  "stage_runs": [{"stage_id": "stage-1", "index": 1, "name": "登录系统", "scene_type": "login", "strategy": "login_guard", "fallback_used": false, "status": "running"}],
                  "current_stage_id": "stage-1",
                  "current_stage_name": "登录系统",
                  "current_strategy": "login_guard"
                }
                """,
                encoding="utf-8",
            )
            with (
                patch("icm_platform.db.DB_PATH", db_path),
                patch("icm_platform.db.DATA_DIR", db_path.parent),
                patch.object(api_module, "ROOT", root),
                patch.object(api_module, "REPORT_DIR", report_root),
                patch.object(api_module, "DRAFT_RUN_DIR", root / "draft-runs"),
                patch("runner.evidence_recorder.ROOT", root),
                patch("runner.evidence_recorder.EVIDENCE_ROOT", report_root / "evidence"),
                patch("runner.evidence_recorder.TRACE_ROOT", report_root / "traces"),
            ):
                db.init_db()
                with db.connect() as conn:
                    conn.execute(
                        """
                        insert into run_tasks(id, mode, case_id, status, command, created_at)
                        values ('ui-agent-stage', 'agent-explore', 'ICMDEV_FUN_001', 'running', '', '2026-06-22T00:00:00Z')
                        """
                    )
                detail = api_module._build_unified_run_detail("ui-agent-stage")

        self.assertEqual(detail["current_stage_name"], "登录系统")
        self.assertEqual(detail["current_strategy"], "login_guard")
        self.assertEqual(detail["agent_plan"]["planner_version"], "v1")
        self.assertEqual(detail["agent_stage_runs"][0]["status"], "running")

    def test_build_unified_run_detail_summarizes_batch_children(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / "test.sqlite3"
            report_dir = root / "reports" / "runs"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "ui-batch-tc-icm-001.md").write_text(
                "\n".join(["# child 1", "- case name: TC-ICM-001 Login", "- status: passed", "- screenshot paths:"]),
                encoding="utf-8",
            )
            (report_dir / "ui-batch-tc-icm-002.md").write_text(
                "\n".join(["# child 2", "- case name: TC-ICM-002 Home", "- status: failed", "- screenshot paths:"]),
                encoding="utf-8",
            )
            with (
                patch("icm_platform.db.DB_PATH", db_path),
                patch("icm_platform.db.DATA_DIR", db_path.parent),
                patch.object(api_module, "REPORT_DIR", report_dir),
                patch("icm_platform.assets.REPORT_DIR", report_dir),
                patch.object(api_module, "SCREENSHOTS_RUNS_DIR", root / "screenshots" / "runs"),
                patch("runner.evidence_recorder.EVIDENCE_ROOT", root / "reports" / "evidence"),
                patch("runner.evidence_recorder.TRACE_ROOT", root / "reports" / "traces"),
            ):
                db.init_db()
                with db.connect() as conn:
                    conn.execute(
                        """
                        insert into run_tasks(id, mode, case_id, status, command, created_at, started_at, finished_at)
                        values ('ui-batch', 'run-batch', null, 'failed', '', '2026-06-26T00:00:00Z', '2026-06-26T00:00:00Z', '2026-06-26T00:02:00Z')
                        """
                    )
                detail = api_module._build_unified_run_detail("ui-batch")

        self.assertEqual(detail["case_name"], "Batch 001-012")
        self.assertEqual(detail["raw_report"].count("TC-ICM-"), 12)
        self.assertEqual(len(detail["steps"]), 12)
        self.assertEqual(detail["steps"][0]["step_index"], 1)
        self.assertEqual(detail["steps"][0]["step_code"], "ui-batch-tc-icm-001")
        self.assertIn("TC-ICM-001", detail["steps"][0]["title"])
        self.assertEqual(detail["steps"][0]["status"], "completed")
        self.assertEqual(detail["steps"][1]["status"], "failed")
        self.assertEqual(detail["steps"][1]["error_message"], "子用例失败")
        self.assertIn("ui-batch-tc-icm-002.md", detail["steps"][1]["command_output"][1])


if __name__ == "__main__":
    unittest.main()
