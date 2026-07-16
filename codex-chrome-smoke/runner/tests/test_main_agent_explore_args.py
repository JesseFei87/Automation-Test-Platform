import asyncio
import sys
from types import ModuleType, SimpleNamespace

from runner import main as runner_main
from runner.main import parse_args


def test_parse_args_accepts_agent_explore_case_and_run_id():
    args = parse_args(["agent-explore", "TC-ICM-001", "run-1"])

    assert args.command == "agent-explore"
    assert args.arg == "TC-ICM-001"
    assert args.run_id == "run-1"


def test_parse_args_accepts_refresh_element_knowledge_no_scan():
    args = parse_args([
        "refresh-element-knowledge",
        "--no-scan",
        "--library-path",
        "library.json",
        "--feedback-path",
        "feedback.json",
        "--output-path",
        "out.json",
    ])

    assert args.command == "refresh-element-knowledge"
    assert args.no_scan is True
    assert args.arg == ""
    assert args.library_path == "library.json"
    assert args.feedback_path == "feedback.json"
    assert args.output_path == "out.json"


def test_parse_args_accepts_refresh_element_knowledge_single_target():
    args = parse_args([
        "refresh-element-knowledge",
        "--target-url",
        "https://example.test/#/login",
        "--target-page-id",
        "login",
        "--target-name",
        "被测系统登录页",
    ])

    assert args.command == "refresh-element-knowledge"
    assert args.target_url == "https://example.test/#/login"
    assert args.target_page_id == "login"
    assert args.target_name == "被测系统登录页"


def test_main_refresh_element_knowledge_no_scan_does_not_launch_browser(monkeypatch):
    calls = []

    async def refresh_element_knowledge(**kwargs):
        calls.append(("refresh", kwargs))
        return {"element_count": 1}

    async def launch_browser(*args, **kwargs):
        raise AssertionError("no-scan refresh should not launch browser")

    monkeypatch.setattr(runner_main, "refresh_element_knowledge", refresh_element_knowledge)
    monkeypatch.setattr(runner_main, "launch_browser", launch_browser)
    monkeypatch.setattr(
        runner_main.sys,
        "argv",
        [
            "main.py",
            "refresh-element-knowledge",
            "--no-scan",
            "--library-path",
            "library.json",
            "--feedback-path",
            "feedback.json",
            "--output-path",
            "out.json",
            "--summary-path",
            "summary.json",
        ],
    )

    assert asyncio.run(runner_main.main()) == 0
    assert calls[0][0] == "refresh"
    kwargs = calls[0][1]
    assert kwargs["scan"] is False
    assert str(kwargs["library_path"]) == "library.json"
    assert str(kwargs["feedback_path"]) == "feedback.json"
    assert str(kwargs["output_path"]) == "out.json"
    assert str(kwargs["summary_path"]) == "summary.json"


def test_main_refresh_element_knowledge_target_url_uses_single_explicit_target(monkeypatch):
    calls = []
    page = object()

    async def refresh_element_knowledge(**kwargs):
        calls.append(("refresh", kwargs))
        return {"element_count": 1}

    async def launch_browser(headless, system, reuse_storage_state=True, **kwargs):
        calls.append(("launch", headless, system, reuse_storage_state))
        return SimpleNamespace(page=page)

    async def close_browser(session):
        calls.append(("close", session.page))

    monkeypatch.setattr(runner_main, "refresh_element_knowledge", refresh_element_knowledge)
    monkeypatch.setattr(runner_main, "launch_browser", launch_browser)
    monkeypatch.setattr(runner_main, "close_browser", close_browser)
    monkeypatch.setattr(
        runner_main.sys,
        "argv",
        [
            "main.py",
            "refresh-element-knowledge",
            "--target-url",
            "https://192.168.16.203:49187/#/login",
            "--target-page-id",
            "login",
            "--target-name",
            "被测系统登录页",
        ],
    )

    assert asyncio.run(runner_main.main()) == 0
    kwargs = calls[1][1]
    assert kwargs["targets"] == [
        {
            "page_id": "login",
            "name": "被测系统登录页",
            "route": "https://192.168.16.203:49187/#/login",
            "url": "https://192.168.16.203:49187/#/login",
        }
    ]
    assert kwargs["base_url"] == ""


def test_main_calls_agent_explore_branch_with_lazy_import(monkeypatch):
    calls = []
    page = object()
    fake_agent_explore = ModuleType("runner.agent_explore")

    async def run_agent_explore(received_page, run_id, case_arg):
        calls.append(("agent-explore", received_page, run_id, case_arg))
        return {"status": "passed"}

    async def launch_browser(headless, system, reuse_storage_state=True, **kwargs):
        calls.append(("launch", headless, system, reuse_storage_state))
        return SimpleNamespace(page=page)

    async def close_browser(session):
        calls.append(("close", session.page))

    fake_agent_explore.run_agent_explore = run_agent_explore
    monkeypatch.setitem(sys.modules, "runner.agent_explore", fake_agent_explore)
    monkeypatch.setattr(runner_main, "launch_browser", launch_browser)
    monkeypatch.setattr(runner_main, "close_browser", close_browser)
    monkeypatch.setattr(runner_main, "load_case", lambda case_id: {"id": case_id, "system": "icm-internal"})
    monkeypatch.setattr(runner_main, "load_system", lambda system_id, case=None: {"id": system_id})
    monkeypatch.setattr(runner_main.sys, "argv", ["main.py", "agent-explore", "TC-ICM-001", "run-1"])

    assert asyncio.run(runner_main.main()) == 0
    assert calls == [
        ("launch", False, {"id": "icm-internal"}, False),
        ("agent-explore", page, "run-1", "TC-ICM-001"),
        ("close", page),
    ]


def test_main_calls_run_case_without_reusing_storage_state(monkeypatch):
    calls = []
    page = object()

    async def launch_browser(headless, system, reuse_storage_state=True, **kwargs):
        calls.append(("launch", headless, system, reuse_storage_state))
        return SimpleNamespace(page=page)

    async def close_browser(session):
        calls.append(("close", session.page))

    async def run_case(received_page, run_id, case_id, keep_archive=False, max_retries=0):
        calls.append(("run-case", received_page, run_id, case_id, keep_archive, max_retries))
        return {
            "case": {"id": case_id, "title": case_id},
            "status": "passed",
            "screenshots": [],
            "failure_point": "",
            "error": "",
            "observed_asset_path": "",
        }

    monkeypatch.setattr(runner_main, "launch_browser", launch_browser)
    monkeypatch.setattr(runner_main, "close_browser", close_browser)
    monkeypatch.setattr(runner_main, "run_case", run_case)
    monkeypatch.setattr(runner_main, "write_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_main, "load_case", lambda case_id: {"id": case_id, "system": "icm-internal"})
    monkeypatch.setattr(runner_main, "load_system", lambda system_id, case=None: {"id": system_id})
    monkeypatch.setattr(runner_main.sys, "argv", ["main.py", "run-case", "TC-ICM-001", "run-1"])

    assert asyncio.run(runner_main.main()) == 0
    assert calls == [
        ("launch", False, {"id": "icm-internal"}, False),
        ("run-case", page, "run-1", "TC-ICM-001", False, 0),
        ("close", page),
    ]
