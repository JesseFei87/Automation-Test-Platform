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

    def test_running_report_screenshots_do_not_fall_back_to_case_latest(self) -> None:
        with patch.object(api_module, "latest_screenshots", return_value=["screenshots/latest/TC-ICM-001/03-final.png"]):
            screenshots = api_module._report_screenshots(
                {"id": "ui-running", "case_id": "TC-ICM-001", "status": "running"},
                "",
            )

        self.assertEqual(screenshots, [])

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
                        "  - 3. click login button",
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
                            "observation": {"url": "https://example.test/#/login", "visibleText": ["登录涓?.."], "interactives": []},
                            "execution": {"result": "waited"},
                        },
                    ],
                }
            }
            with patch.object(api_module, "DRAFT_RUN_DIR", draft_run_dir):
                steps = api_module._build_agent_steps(agent_explore, [], [], run_id, {"case_id": "LOGIN_FUN_002"})

        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0]["title"], "用例步骤 1 - 访问 https://example.test/#/login?redirect=%2Fredirect")
        self.assertEqual(steps[1]["title"], "用例步骤 2 - 输入账号 test 密码 123456")
        self.assertEqual(steps[2]["title"], "用例步骤 3 - click login button")
        self.assertEqual(steps[2]["summary"], "等待登录完成并跳转到目标页面")


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
                        "  - 在设备名称输入框输入16个字符CDEFGHIJKLMNOPQ",
                        "  - 填写其他必填合法字段",
                        "  - click confirm button",
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
        self.assertEqual(steps[1]["title"], "用例步骤 2 - 在设备名称输入框输入16个字符CDEFGHIJKLMNOPQ")
        self.assertEqual(steps[1]["command_output"], [
            "[action] 在设备名称输入框输入16个字符CDEFGHIJKLMNOPQ",
            "[result] device_name_filled",
            "[value] BCDEFGHIJKLMNOPQ",
            "[screenshot] agent-step-02.png",
        ])


    def test_build_agent_steps_binds_expected_results_back_to_original_case_steps(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            draft_run_dir = root / "draft-runs"
            run_id = "ui-agent-assertion-stage"
            run_dir = draft_run_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "case.yaml").write_text(
                "\n".join(
                    [
                        "id: USRMGT_FUN_002",
                        "system: icm-internal",
                        "steps:",
                        "  - login icm",
                        "  - open user management",
                        "  - hover row more menu",
                        "  - click configure server device option",
                        "expected_results:",
                        "  - configure page opened",
                        "  - configure page title visible",
                        "  - breadcrumb contains configure entry",
                        "  - page content shows server and device sections",
                    ]
                ),
                encoding="utf-8",
            )
            agent_explore = {
                "trace": {
                    "ok": True,
                    "plan": {
                        "stages": [
                            {"stage_id": "stage-menu", "source_steps": [3, 4], "strategy": "user_row_menu"},
                            {"stage_id": "stage-assert", "source_steps": [4], "strategy": "detail_assert"},
                        ]
                    },
                    "history": [
                        {"step": 4, "stage_id": "stage-menu", "stage_local_step": 2, "decision": {"action": "click", "reason": "click menu item"}, "observation": {}, "execution": {"result": "user_row_menu_item_clicked", "screenshot_name": "agent-step-04.png"}},
                        {"step": 5, "stage_id": "stage-assert", "stage_local_step": 1, "decision": {"action": "assert_text", "value": "configure", "reason": "verify page opened"}, "observation": {}, "execution": {"result": "detail_assert_passed", "screenshot_name": "agent-step-05.png"}},
                        {"step": 6, "stage_id": "stage-assert", "stage_local_step": 2, "decision": {"action": "assert_text", "value": "configure", "reason": "verify page title"}, "observation": {}, "execution": {"result": "detail_assert_passed", "screenshot_name": "agent-step-06.png"}},
                        {"step": 7, "stage_id": "stage-assert", "stage_local_step": 3, "decision": {"action": "assert_text", "value": "configure", "reason": "verify breadcrumb"}, "observation": {}, "execution": {"result": "detail_assert_passed", "screenshot_name": "agent-step-07.png"}},
                        {"step": 8, "stage_id": "stage-assert", "stage_local_step": 4, "decision": {"action": "finish", "reason": "stage complete"}, "observation": {}, "execution": {"result": "finished", "screenshot_name": "agent-step-08.png"}},
                    ],
                }
            }
            screenshots = [
                {"filename": "agent-step-04.png", "url": "/api/screenshots/runs/ui/agent-step-04.png"},
                {"filename": "agent-step-05.png", "url": "/api/screenshots/runs/ui/agent-step-05.png"},
                {"filename": "agent-step-06.png", "url": "/api/screenshots/runs/ui/agent-step-06.png"},
                {"filename": "agent-step-07.png", "url": "/api/screenshots/runs/ui/agent-step-07.png"},
                {"filename": "agent-step-08.png", "url": "/api/screenshots/runs/ui/agent-step-08.png"},
            ]
            with patch.object(api_module, "DRAFT_RUN_DIR", draft_run_dir):
                steps = api_module._build_agent_steps(agent_explore, [], screenshots, run_id, {"case_id": "USRMGT_FUN_002"})

        self.assertEqual(len(steps), 4)
        self.assertEqual(steps[0]["title"], "用例步骤 1 - login icm")
        self.assertEqual(steps[1]["title"], "用例步骤 2 - open user management")
        self.assertEqual(steps[2]["title"], "用例步骤 3 - hover row more menu")
        self.assertEqual(steps[3]["title"], "用例步骤 4 - click configure server device option")
        self.assertEqual(steps[0]["expected_result"], "configure page opened")
        self.assertEqual(steps[1]["expected_result"], "configure page title visible")
        self.assertEqual(steps[2]["expected_result"], "breadcrumb contains configure entry")
        self.assertEqual(steps[3]["expected_result"], "page content shows server and device sections")
        self.assertEqual(steps[0]["expected_result_status"], "completed")
        self.assertEqual(steps[1]["expected_result_status"], "completed")
        self.assertEqual(steps[2]["expected_result_status"], "completed")
        self.assertEqual(steps[3]["expected_result_status"], "queued")
        self.assertTrue(steps[0]["actual_result"])
        self.assertTrue(steps[3]["actual_result"])
        self.assertEqual(steps[0]["assertion_checks"][0]["status"], "completed")
        self.assertEqual(steps[0]["assertion_checks"][0]["evidence_source"], "decision.value")
        self.assertEqual(steps[0]["assertion_checks"][0]["actual"], "configure")
        self.assertEqual(steps[3]["assertion_checks"][0]["status"], "queued")

    def test_build_agent_steps_keeps_range_expected_result_pending_until_bound_step_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            draft_run_dir = root / "draft-runs"
            run_id = "ui-agent-range-assertion"
            run_dir = draft_run_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "case.yaml").write_text(
                "\n".join(
                    [
                        "id: USRMGT_BND_003",
                        "system: icm-internal",
                        "steps:",
                        "  - click add button",
                        "  - observe popup dialog",
                        "expected_results:",
                        "  - 1-2. dialog opened",
                    ]
                ),
                encoding="utf-8",
            )
            agent_explore = {
                "trace": {
                    "ok": True,
                    "plan": {
                        "stages": [
                            {"stage_id": "stage-dialog", "source_steps": [1, 2], "strategy": "dialog_form_fill"},
                            {"stage_id": "stage-assert", "source_steps": [2], "strategy": "detail_assert"},
                        ]
                    },
                    "history": [
                        {
                            "step": 1,
                            "stage_id": "stage-dialog",
                            "stage_local_step": 1,
                            "decision": {"action": "click", "reason": "open dialog"},
                            "observation": {},
                            "execution": {"result": "dialog_trigger_clicked", "screenshot_name": "agent-step-01.png"},
                        },
                        {
                            "step": 2,
                            "stage_id": "stage-assert",
                            "stage_local_step": 1,
                            "decision": {"action": "assert_text", "value": "添加设备信息", "reason": "verify dialog opened"},
                            "observation": {"visibleText": ["添加设备信息"]},
                            "execution": {"result": "detail_assert_passed", "screenshot_name": "agent-step-02.png"},
                        },
                    ],
                }
            }
            screenshots = [
                {"filename": "agent-step-01.png", "url": "/api/screenshots/runs/ui/agent-step-01.png"},
                {"filename": "agent-step-02.png", "url": "/api/screenshots/runs/ui/agent-step-02.png"},
            ]
            with patch.object(api_module, "DRAFT_RUN_DIR", draft_run_dir):
                steps = api_module._build_agent_steps(agent_explore, [], screenshots, run_id, {"case_id": "USRMGT_BND_003"})

        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["expected_result"], "dialog opened")
        self.assertEqual(steps[0]["expected_result_status"], "queued")
        self.assertTrue(steps[0]["actual_result"])
        self.assertEqual(steps[1]["expected_result"], "dialog opened")
        self.assertEqual(steps[1]["expected_result_status"], "completed")
        self.assertEqual(steps[1]["actual_result"], "添加设备信息")
        self.assertEqual(steps[0]["assertion_checks"][0]["status"], "queued")
        self.assertEqual(steps[1]["assertion_checks"][0]["status"], "completed")
        self.assertEqual(steps[1]["assertion_checks"][0]["actual"], "添加设备信息")

    def test_evaluate_assertion_check_accepts_user_device_bound_for_checkbox_checked(self) -> None:
        evaluated = api_module._evaluate_assertion_check(
            {"type": "checkbox_checked", "expected": "4?????????????"},
            {
                "decision": {"value": "DxI(2)"},
                "execution": {"result": "user_device_bound"},
                "observation": {"url": "https://example.test/#/system/user-auth/server/4", "visibleText": ["????????"]},
            },
            {},
        )

        self.assertEqual(evaluated["status"], "completed")
        self.assertEqual(evaluated["actual"], "DxI(2)")
        self.assertEqual(evaluated["evidence_source"], "execution.result")

    def test_evaluate_assertion_check_accepts_account_switch_for_login_page_expectation(self) -> None:
        evaluated = api_module._evaluate_assertion_check(
            {"type": "url_contains", "expected": "#/login"},
            {
                "decision": {"reason": "????????? test ????"},
                "execution": {"result": "account_switch_passed"},
                "observation": {"url": "https://example.test/#/index", "visibleText": ["??"]},
            },
            {},
        )

        self.assertEqual(evaluated["status"], "completed")
        self.assertEqual(evaluated["evidence_source"], "execution.result")

    def test_build_assertion_checks_maps_login_and_logout_expectations(self) -> None:
        checks = api_module._build_assertion_checks("??????????")
        self.assertIn(("url_contains", "#/index"), {(item["type"], item["expected"]) for item in checks})
        self.assertIn(("login_success", "??????????"), {(item["type"], item["expected"]) for item in checks})

        logout_checks = api_module._build_assertion_checks("?????")
        self.assertIn(("url_contains", "#/login"), {(item["type"], item["expected"]) for item in logout_checks})

    def test_evaluate_assertion_check_accepts_account_switch_passed_for_login_success(self) -> None:
        evaluated = api_module._evaluate_assertion_check(
            {"type": "login_success", "expected": "test??????"},
            {
                "decision": {"action": "finish"},
                "execution": {"result": "account_switch_passed"},
                "observation": {"url": "https://example.test/#/index", "visibleText": ["??"]},
            },
            {},
        )

        self.assertEqual(evaluated["status"], "completed")
        self.assertEqual(evaluated["evidence_source"], "execution.result")

    def test_build_agent_steps_keeps_logout_and_relogin_as_two_step_assertions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            draft_run_dir = root / "draft-runs"
            run_id = "ui-agent-account-switch"
            run_dir = draft_run_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "case.yaml").write_text(
                "\n".join(
                    [
                        "id: USRMGT_FUN_001",
                        "system: icm-internal",
                        "steps:",
                        "  - ????",
                        "  - ??test/123456??",
                        "expected_results:",
                        "  - ?????",
                        "  - test??????",
                    ]
                ),
                encoding="utf-8",
            )
            agent_explore = {
                "trace": {
                    "ok": True,
                    "plan": {
                        "stages": [
                            {"stage_id": "stage-switch", "source_steps": [1, 2], "strategy": "account_switch"},
                        ]
                    },
                    "history": [
                        {
                            "step": 1,
                            "stage_id": "stage-switch",
                            "stage_local_step": 1,
                            "decision": {"action": "click", "reason": "????????????"},
                            "observation": {"url": "https://example.test/#/login?redirect=%2Fredirect", "visibleText": ["??"]},
                            "execution": {"result": "logged_out_to_login", "screenshot_name": "agent-step-01.png"},
                        },
                        {
                            "step": 2,
                            "stage_id": "stage-switch",
                            "stage_local_step": 2,
                            "decision": {"action": "click", "reason": "?? test ????"},
                            "observation": {"url": "https://example.test/#/icm", "visibleText": ["???"]},
                            "execution": {"result": "account_switch_passed", "screenshot_name": "agent-step-02.png"},
                        },
                    ],
                }
            }
            screenshots = [
                {"filename": "agent-step-01.png", "url": "/api/screenshots/runs/ui/agent-step-01.png"},
                {"filename": "agent-step-02.png", "url": "/api/screenshots/runs/ui/agent-step-02.png"},
            ]
            with patch.object(api_module, "DRAFT_RUN_DIR", draft_run_dir):
                steps = api_module._build_agent_steps(agent_explore, [], screenshots, run_id, {"case_id": "USRMGT_FUN_001"})

        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["expected_result_status"], "completed")
        self.assertTrue(steps[0]["actual_result"])
        self.assertEqual(steps[1]["expected_result_status"], "completed")
        self.assertEqual(steps[1]["status"], "completed")

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

    def test_build_agent_steps_keeps_active_assertion_miss_pending(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            draft_run_dir = root / "draft-runs"
            run_id = "ui-agent-active-assertion"
            run_dir = draft_run_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "case.yaml").write_text(
                "\n".join(
                    [
                        "id: USRMGT_FUN_002",
                        "system: icm-internal",
                        "steps:",
                        "  - Open target menu",
                        "expected_results:",
                        "  - Target page loaded",
                    ]
                ),
                encoding="utf-8",
            )
            agent_explore = {
                "trace": {
                    "ok": False,
                    "status": "running",
                    "plan": {
                        "stages": [
                            {"stage_id": "stage-assert", "source_steps": [1], "strategy": "detail_assert"},
                        ]
                    },
                    "history": [
                        {
                            "step": 1,
                            "stage_id": "stage-assert",
                            "stage_local_step": 1,
                            "decision": {"action": "assert_text", "reason": "verify target page"},
                            "observation": {"url": "https://example.test/#/system/user", "visibleText": ["Loading"]},
                            "execution": {"result": "assert_checked", "screenshot_name": "agent-step-01.png"},
                        },
                    ],
                }
            }

            with patch.object(api_module, "DRAFT_RUN_DIR", draft_run_dir):
                steps = api_module._build_agent_steps(agent_explore, [], [], run_id, {"case_id": "USRMGT_FUN_002"})

        self.assertEqual(steps[0]["expected_result_status"], "queued")
        self.assertEqual(steps[0]["assertion_checks"][0]["status"], "queued")
        self.assertEqual(steps[0]["status"], "running")

    def test_build_agent_steps_uses_immediate_following_history_as_assertion_evidence_when_current_step_misses_menu_text(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            draft_run_dir = root / "draft-runs"
            run_id = "ui-agent-menu-evidence-forward"
            run_dir = draft_run_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "case.yaml").write_text(
                "\n".join(
                    [
                        "id: USRMGT_FUN_002",
                        "system: icm-internal",
                        "steps:",
                        "  - 登录ICM系统",
                        "  - 进入系统管理-用户管理",
                        "  - 鼠标悬停在用户test所在行上《更多按钮",
                        "  - 在下拉菜单中，点击'配置服务器和设备'选项",
                        "expected_results:",
                        "  - 登录成功",
                        "  - 用户列表正常展示",
                        "  - 弹出下拉菜单包含'配置服务器和设备'项",
                        "  - 弹出配置服务器和设备弹窗，弹窗内含用户基本信息、服务器信息、绑定设备信息三个区块",
                    ]
                ),
                encoding="utf-8",
            )
            agent_explore = {
                "trace": {
                    "ok": True,
                    "history": [
                        {
                            "step": 1,
                            "decision": {"action": "click", "reason": "登录ICM"},
                            "observation": {"url": "https://example.test/#/index", "visibleText": ["首页"]},
                            "execution": {"result": "login_guard_passed", "screenshot_name": "agent-step-01.png"},
                        },
                        {
                            "step": 2,
                            "decision": {"action": "goto", "reason": "进入系统管理-用户管理"},
                            "observation": {"url": "https://example.test/#/system/user", "visibleText": ["用户管理"]},
                            "execution": {"result": "route_opened", "screenshot_name": "agent-step-02.png"},
                        },
                        {
                            "step": 3,
                            "decision": {"action": "hover", "reason": "悬停用户 test 行内更多按钮"},
                            "observation": {
                                "url": "https://example.test/#/system/user",
                                "visibleText": ["智控中台", "首页", "系统管理"],
                            },
                            "execution": {"result": "user_row_menu_opened", "screenshot_name": "agent-step-03.png"},
                        },
                        {
                            "step": 4,
                            "decision": {"action": "click", "reason": "点击 配置服务器和设备 选项"},
                            "observation": {
                                "url": "https://example.test/#/system/user-auth/server/4",
                                "visibleText": ["首页 用户管理 配置服务器和设备", "基本信息", "服务器信息"],
                            },
                            "execution": {"result": "user_row_menu_item_clicked", "screenshot_name": "agent-step-04.png"},
                        },
                    ],
                }
            }
            screenshots = [
                {"filename": "agent-step-01.png", "url": "/api/screenshots/runs/ui/agent-step-01.png"},
                {"filename": "agent-step-02.png", "url": "/api/screenshots/runs/ui/agent-step-02.png"},
                {"filename": "agent-step-03.png", "url": "/api/screenshots/runs/ui/agent-step-03.png"},
                {"filename": "agent-step-04.png", "url": "/api/screenshots/runs/ui/agent-step-04.png"},
            ]
            with patch.object(api_module, "DRAFT_RUN_DIR", draft_run_dir):
                steps = api_module._build_agent_steps(agent_explore, [], screenshots, run_id, {"case_id": "USRMGT_FUN_002"})

        self.assertEqual(steps[2]["expected_result_status"], "completed")
        self.assertEqual(steps[2]["status"], "completed")
        self.assertEqual(steps[2]["assertion_checks"][0]["status"], "completed")

    def test_build_agent_steps_falls_back_to_reason_before_generic_step_title(self) -> None:
        agent_explore = {
            "trace": {
                "ok": False,
                "history": [
                    {
                        "step": 1,
                        "decision": {"action": "click", "reason": "登录ICM"},
                        "observation": {},
                        "execution": {"result": "login_guard_passed"},
                    }
                ],
            }
        }

        steps = api_module._build_agent_steps(agent_explore, [], [], "ui-agent-fallback", {"case_id": "UNKNOWN_CASE"})

        self.assertEqual(steps[0]["title"], "登录ICM")
        self.assertEqual(steps[0]["summary"], "登录ICM")

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

    def test_build_unified_run_detail_reconciles_failed_steps_back_to_stage_status(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / "test.sqlite3"
            report_root = root / "reports"
            agent_root = report_root / "agent-explore" / "ui-agent-stage-failed"
            agent_root.mkdir(parents=True, exist_ok=True)
            (agent_root / "trace.json").write_text(
                """
                {
                  "ok": true,
                  "status": "completed",
                  "plan": {
                    "planner_version": "v1",
                    "case_id": "USRMGT_FUN_001",
                    "stages": [
                      {"stage_id": "stage-4", "index": 4, "name": "绑定设备", "scene_type": "list", "strategy": "user_device_binding", "source_steps": [4, 5]}
                    ]
                  },
                  "stage_runs": [
                    {"stage_id": "stage-4", "index": 4, "name": "绑定设备", "scene_type": "list", "strategy": "user_device_binding", "fallback_used": false, "status": "completed"}
                  ]
                }
                """,
                encoding="utf-8",
            )
            fake_steps = [
                {"step_index": 1, "status": "completed", "title": "登录"},
                {"step_index": 2, "status": "completed", "title": "进入页面"},
                {"step_index": 3, "status": "completed", "title": "打开菜单"},
                {"step_index": 4, "status": "failed", "title": "勾选四台设备"},
                {"step_index": 5, "status": "failed", "title": "保存配置"},
            ]
            with (
                patch("icm_platform.db.DB_PATH", db_path),
                patch("icm_platform.db.DATA_DIR", db_path.parent),
                patch.object(api_module, "ROOT", root),
                patch.object(api_module, "REPORT_DIR", report_root),
                patch.object(api_module, "DRAFT_RUN_DIR", root / "draft-runs"),
                patch("runner.evidence_recorder.ROOT", root),
                patch("runner.evidence_recorder.EVIDENCE_ROOT", report_root / "evidence"),
                patch("runner.evidence_recorder.TRACE_ROOT", report_root / "traces"),
                patch.object(api_module, "_build_agent_steps", return_value=fake_steps),
            ):
                db.init_db()
                with db.connect() as conn:
                    conn.execute(
                        """
                        insert into run_tasks(id, mode, case_id, status, command, created_at)
                        values ('ui-agent-stage-failed', 'agent-explore', 'USRMGT_FUN_001', 'completed', '', '2026-07-03T00:00:00Z')
                        """
                    )
                detail = api_module._build_unified_run_detail("ui-agent-stage-failed")

        self.assertEqual(detail["steps"][3]["status"], "failed")
        self.assertEqual(detail["agent_stage_runs"][0]["status"], "failed")

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
        self.assertTrue(detail["steps"][1]["error_message"])
        self.assertIn("ui-batch-tc-icm-002.md", detail["steps"][1]["command_output"][1])

    # ===== E.3 _build_assertion_checks AI 兜底回归测试 =====

    def test_build_assertion_checks_default_no_ai_fallback(self) -> None:
        with patch.object(api_module, "ai_service") as mocked_ai, patch.object(api_module, "get_ai_settings") as mocked_settings:
            checks = api_module._build_assertion_checks("user is created successfully")
        self.assertTrue(all(c["type"] == "text_contains" for c in checks))
        mocked_ai.parse_assertions_with_ai.assert_not_called()
        mocked_settings.assert_not_called()

    def test_build_assertion_checks_ai_fallback_replaces_text_contains(self) -> None:
        ai_checks = [{"type": "page_title_contains", "expected": "user list", "label": "页面标题", "status": "queued", "actual": "", "evidence_source": "", "reason": "", "match_mode": "contains", "source": "ai"}]
        settings = {"provider": "minimax-m3", "model": "MiniMax-M3", "base_url": "", "api_key": "sk-test"}
        with (
            patch.object(api_module, "get_ai_settings", return_value=settings),
            patch.object(api_module, "load_cached_assertion_analysis", return_value=None),
            patch.object(api_module, "ai_service") as mocked_ai,
            patch.object(api_module, "save_assertion_analysis"),
        ):
            mocked_ai.parse_assertions_with_ai.return_value = ai_checks
            checks = api_module._build_assertion_checks("user is created successfully", ai_fallback=True)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["type"], "page_title_contains")
        self.assertEqual(checks[0]["source"], "ai")

    def test_build_assertion_checks_ai_fallback_caches_result(self) -> None:
        ai_checks = [{"type": "text_contains", "expected": "hello", "label": "文本", "status": "queued", "actual": "", "evidence_source": "", "reason": "", "match_mode": "contains", "source": "ai"}]
        settings = {"provider": "minimax-m3", "model": "MiniMax-M3", "base_url": "", "api_key": "sk-test"}
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "test.sqlite3"
            with (
                patch("icm_platform.db.DB_PATH", db_path),
                patch("icm_platform.db.DATA_DIR", db_path.parent),
                patch.object(api_module, "get_ai_settings", return_value=settings),
                patch.object(api_module, "ai_service") as mocked_ai,
            ):
                db.init_db()
                mocked_ai.parse_assertions_with_ai.return_value = ai_checks
                first = api_module._build_assertion_checks("user is created", ai_fallback=True)
                second = api_module._build_assertion_checks("user is created", ai_fallback=True)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(mocked_ai.parse_assertions_with_ai.call_count, 1)

    def test_build_assertion_checks_ai_fallback_degrades_on_provider_error(self) -> None:
        settings = {"provider": "minimax-m3", "model": "MiniMax-M3", "base_url": "", "api_key": "sk-test"}
        with (
            patch.object(api_module, "get_ai_settings", return_value=settings),
            patch.object(api_module, "load_cached_assertion_analysis", return_value=None),
            patch.object(api_module, "ai_service") as mocked_ai,
            patch.object(api_module, "save_assertion_analysis"),
        ):
            from icm_platform.ai_service import AIProviderError
            mocked_ai.parse_assertions_with_ai.side_effect = AIProviderError("timeout")
            checks = api_module._build_assertion_checks("user is created successfully", ai_fallback=True)
        self.assertTrue(all(c["type"] == "text_contains" for c in checks))

    def test_build_assertion_checks_ai_fallback_degrades_on_config_error(self) -> None:
        settings = {"provider": "minimax-m3", "model": "MiniMax-M3", "base_url": "", "api_key": ""}
        with (
            patch.object(api_module, "get_ai_settings", return_value=settings),
            patch.object(api_module, "load_cached_assertion_analysis", return_value=None),
            patch.object(api_module, "ai_service") as mocked_ai,
        ):
            from icm_platform.ai_service import AIConfigurationError
            mocked_ai.parse_assertions_with_ai.side_effect = AIConfigurationError("no api key")
            checks = api_module._build_assertion_checks("user is created successfully", ai_fallback=True)
        self.assertTrue(all(c["type"] == "text_contains" for c in checks))

    def test_build_assertion_checks_ai_fallback_skipped_when_rule_matches(self) -> None:
        with patch.object(api_module, "ai_service") as mocked_ai:
            checks = api_module._build_assertion_checks("弹窗已打开，显示新增设备对话框", ai_fallback=True)
        self.assertTrue(any(c["type"] != "text_contains" for c in checks))
        mocked_ai.parse_assertions_with_ai.assert_not_called()

    # ===== E.5 求值器新 type 测试 =====

    def _eval_check(self, check: dict, item: dict, trace: dict = None) -> dict:
        trace = trace or {}
        return api_module._evaluate_assertion_check(check, item, trace)

    def test_evaluate_unknown_type_contains_match(self) -> None:
        item = {"observation": {"visibleText": ["Configure Page"]}, "execution": {"result": ""}, "decision": {}}
        check = {"type": "page_title_contains", "expected": "configure", "match_mode": "contains"}
        result = self._eval_check(check, item)
        self.assertEqual(result["status"], "completed")

    def test_evaluate_unknown_type_contains_miss(self) -> None:
        item = {"observation": {"visibleText": ["Dashboard"]}, "execution": {"result": ""}, "decision": {}}
        check = {"type": "page_title_contains", "expected": "configure", "match_mode": "contains"}
        result = self._eval_check(check, item)
        self.assertEqual(result["status"], "failed")

    def test_evaluate_unknown_type_not_contains(self) -> None:
        item = {"observation": {"visibleText": ["Dashboard"]}, "execution": {"result": ""}, "decision": {}}
        check = {"type": "error_message_visible", "expected": "error", "match_mode": "not_contains"}
        result = self._eval_check(check, item)
        self.assertEqual(result["status"], "completed")

    def test_evaluate_unknown_type_equals(self) -> None:
        item = {"observation": {"visibleText": ["configure"]}, "execution": {"result": ""}, "decision": {}}
        check = {"type": "page_title_equals", "expected": "configure", "match_mode": "equals"}
        result = self._eval_check(check, item)
        self.assertEqual(result["status"], "completed")

    def test_evaluate_unknown_type_regex(self) -> None:
        item = {"observation": {"visibleText": ["config01 page"]}, "execution": {"result": ""}, "decision": {}}
        check = {"type": "page_id_contains", "expected": r"config\d+", "match_mode": "regex"}
        result = self._eval_check(check, item)
        self.assertEqual(result["status"], "completed")

    def test_evaluate_unknown_type_regex_invalid(self) -> None:
        item = {"observation": {"visibleText": ["test"]}, "execution": {"result": ""}, "decision": {}}
        check = {"type": "page_id_contains", "expected": "[invalid", "match_mode": "regex"}
        result = self._eval_check(check, item)
        self.assertEqual(result["status"], "queued")
        self.assertIn("regex", result["reason"])

    def test_evaluate_unknown_type_uses_decision_value_when_no_visible_text(self) -> None:
        item = {"observation": {}, "execution": {"result": "detail_assert_passed"}, "decision": {"value": "configure"}}
        check = {"type": "page_title_contains", "expected": "configure page opened", "match_mode": "contains"}
        result = self._eval_check(check, item)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["evidence_source"], "decision.value")

    def test_evaluate_unknown_type_error_priority(self) -> None:
        item = {"observation": {"visibleText": ["test"]}, "execution": {"result": "", "error": "boom"}, "decision": {}}
        check = {"type": "page_title_contains", "expected": "test", "match_mode": "contains"}
        result = self._eval_check(check, item)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["evidence_source"], "execution.error")

    def test_evaluate_known_type_ignores_match_mode(self) -> None:
        item = {"observation": {"visibleText": ["status: online"]}, "execution": {"result": ""}, "decision": {}}
        check = {"type": "field_value", "expected": "online", "match_mode": "not_contains", "field": "状态"}
        result = self._eval_check(check, item)
        self.assertEqual(result["status"], "completed")

    # ===== 宽松匹配测试 =====

    def test_loose_text_match_strict(self) -> None:
        from icm_platform.api import _loose_text_match
        facts = {"haystack": "hello world", "visible_texts": ["hello"], "interactive_texts": []}
        matched, strength = _loose_text_match("hello", facts)
        self.assertTrue(matched)
        self.assertEqual(strength, "strict")

    def test_loose_text_match_substring(self) -> None:
        from icm_platform.api import _loose_text_match
        facts = {"haystack": "基本信息 服务器信息", "visible_texts": ["基本信息"], "interactive_texts": []}
        matched, strength = _loose_text_match("用户基本信息", facts)
        self.assertTrue(matched)
        self.assertEqual(strength, "loose_substring")

    def test_loose_text_match_overlap(self) -> None:
        from icm_platform.api import _loose_text_match
        facts = {"haystack": "绑定的设备信息", "visible_texts": ["绑定的设备信息"], "interactive_texts": []}
        matched, strength = _loose_text_match("绑定设备信息", facts)
        self.assertTrue(matched)
        self.assertEqual(strength, "loose_overlap")

    def test_loose_text_match_no_match(self) -> None:
        from icm_platform.api import _loose_text_match
        facts = {"haystack": "智控中台 首页", "visible_texts": ["智控中台", "首页"], "interactive_texts": []}
        matched, strength = _loose_text_match("登录成功", facts)
        self.assertFalse(matched)
        self.assertEqual(strength, "")

    def test_evaluate_section_visible_loose_match(self) -> None:
        item = {"observation": {"visibleText": ["基本信息"]}, "execution": {"result": ""}, "decision": {}}
        check = {"type": "section_visible", "expected": "用户基本信息", "match_mode": "contains"}
        result = self._eval_check(check, item)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result.get("match_strength"), "loose_substring")

    def test_evaluate_not_contains_stays_strict(self) -> None:
        item = {"observation": {"visibleText": ["error message"]}, "execution": {"result": ""}, "decision": {}}
        check = {"type": "error_message_visible", "expected": "error", "match_mode": "not_contains"}
        result = self._eval_check(check, item)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result.get("match_strength"), "strict")

    # ===== 上下文 AI 再解析测试 =====

    def test_build_page_context_returns_none_for_sparse(self) -> None:
        from icm_platform.api import _build_page_context
        item = {"observation": {"visibleText": ["a"]}, "execution": {}, "decision": {}}
        self.assertIsNone(_build_page_context(item))

    def test_build_page_context_returns_context(self) -> None:
        from icm_platform.api import _build_page_context
        item = {"observation": {"visibleText": ["a", "b", "c", "d"], "url": "http://test/#/index"}, "execution": {}, "decision": {}}
        ctx = _build_page_context(item)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["url"], "http://test/#/index")
        self.assertEqual(len(ctx["visible_texts"]), 4)

    def test_context_signature_empty_for_none(self) -> None:
        from icm_platform.api import _context_signature
        self.assertEqual(_context_signature(None), "")

    def test_context_signature_differs(self) -> None:
        from icm_platform.api import _context_signature
        sig1 = _context_signature({"url": "#/a", "visible_texts": ["a"]})
        sig2 = _context_signature({"url": "#/b", "visible_texts": ["a"]})
        self.assertNotEqual(sig1, sig2)

    def test_expected_text_hash_backward_compat(self) -> None:
        from icm_platform.api import expected_text_hash
        from hashlib import sha256
        old = sha256("test".encode("utf-8")).hexdigest()
        new = expected_text_hash("test", "")
        self.assertEqual(old, new)

    def test_expected_text_hash_with_context(self) -> None:
        from icm_platform.api import expected_text_hash
        h1 = expected_text_hash("test", "ctx1")
        h2 = expected_text_hash("test", "ctx2")
        h3 = expected_text_hash("test", "")
        self.assertNotEqual(h1, h2)
        self.assertNotEqual(h1, h3)

    def test_assertion_parsing_payload_without_context(self) -> None:
        from icm_platform.ai_service import AIService
        service = AIService()
        payload = service._assertion_parsing_payload("MiniMax-M3", "test", "minimax-m3")
        user_content = payload["messages"][1]["content"]
        self.assertIn("expected_text", user_content)
        self.assertNotIn("page_evidence", user_content)

    def test_assertion_parsing_payload_with_context(self) -> None:
        import json as _json
        from icm_platform.ai_service import AIService
        service = AIService()
        ctx = {"url": "#/index", "visible_texts": ["首页", "系统管理"], "interactive_texts": []}
        payload = service._assertion_parsing_payload("MiniMax-M3", "test", "minimax-m3", page_context=ctx)
        user_content = _json.loads(payload["messages"][1]["content"])
        self.assertIn("page_evidence", user_content)
        self.assertEqual(user_content["page_evidence"]["url"], "#/index")


if __name__ == "__main__":
    unittest.main()
