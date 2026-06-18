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


def test_main_calls_agent_explore_branch_with_lazy_import(monkeypatch):
    calls = []
    page = object()
    fake_agent_explore = ModuleType("runner.agent_explore")

    async def run_agent_explore(received_page, run_id, case_arg):
        calls.append(("agent-explore", received_page, run_id, case_arg))
        return {"status": "passed"}

    async def launch_browser(headless, system):
        calls.append(("launch", headless, system))
        return SimpleNamespace(page=page)

    async def close_browser(session):
        calls.append(("close", session.page))

    fake_agent_explore.run_agent_explore = run_agent_explore
    monkeypatch.setitem(sys.modules, "runner.agent_explore", fake_agent_explore)
    monkeypatch.setattr(runner_main, "launch_browser", launch_browser)
    monkeypatch.setattr(runner_main, "close_browser", close_browser)
    monkeypatch.setattr(runner_main, "load_case", lambda case_id: {"id": case_id, "system": "icm-internal"})
    monkeypatch.setattr(runner_main, "load_system", lambda system_id: {"id": system_id})
    monkeypatch.setattr(runner_main.sys, "argv", ["main.py", "agent-explore", "TC-ICM-001", "run-1"])

    assert asyncio.run(runner_main.main()) == 0
    assert calls == [
        ("launch", False, {"id": "icm-internal"}),
        ("agent-explore", page, "run-1", "TC-ICM-001"),
        ("close", page),
    ]
