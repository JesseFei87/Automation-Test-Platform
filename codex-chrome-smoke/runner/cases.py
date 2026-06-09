from __future__ import annotations

import traceback
from typing import Any, Awaitable, Callable

from playwright.async_api import Page

from runner.asset_recorder import attach_asset_recorder, write_observed_asset
from runner.browser import attach_case_runtime, finalize_screenshots, load_case, load_system, open_login_page, screenshot
from runner.flows.icm_case_001 import run as run_case_001
from runner.flows.icm_case_002 import run as run_case_002
from runner.flows.icm_case_003 import run as run_case_003
from runner.flows.icm_case_004 import run as run_case_004
from runner.flows.icm_case_005 import run as run_case_005
from runner.flows.icm_case_006 import run as run_case_006
from runner.flows.icm_case_007 import run as run_case_007
from runner.flows.icm_case_008 import run as run_case_008
from runner.flows.icm_case_009 import run as run_case_009
from runner.flows.icm_case_010 import run as run_case_010
from runner.flows.icm_case_011 import run as run_case_011
from runner.flows.icm_case_012 import run as run_case_012

CaseRunner = Callable[[Page, dict[str, Any], dict[str, Any]], Awaitable[None]]

CASE_RUNNERS: dict[str, CaseRunner] = {
    "TC-ICM-001": run_case_001,
    "TC-ICM-002": run_case_002,
    "TC-ICM-003": run_case_003,
    "TC-ICM-004": run_case_004,
    "TC-ICM-005": run_case_005,
    "TC-ICM-006": run_case_006,
    "TC-ICM-007": run_case_007,
    "TC-ICM-008": run_case_008,
    "TC-ICM-009": run_case_009,
    "TC-ICM-010": run_case_010,
    "TC-ICM-011": run_case_011,
    "TC-ICM-012": run_case_012,
}


async def run_case(page: Page, run_id: str, case_id: str, keep_archive: bool = False) -> dict[str, Any]:
    case = load_case(case_id)
    system = load_system(case["system"])
    apply_runtime_case_inputs(case, system)
    shot_names: list[str] = []
    failure_point = ""
    error = ""

    attach_case_runtime(page, run_id, case_id)
    recorder = attach_asset_recorder(page, run_id, case_id)
    await open_login_page(page, system)
    await screenshot(page, run_id, case_id, "01-entry.png")
    shot_names.append("01-entry.png")

    runner = CASE_RUNNERS.get(case_id)
    if runner is None:
        raise KeyError(f"Unsupported case: {case_id}")

    try:
        await runner(page, system, case)
        status = "passed"
    except Exception as exc:
        status = "failed"
        failure_point = traceback.format_exc(limit=3)
        error = str(exc)
    finally:
        active_page = getattr(page, "_case_page", page)
        captured_stages = set(getattr(page, "_case_captured_stages", set()))
        captured_stages.update(getattr(active_page, "_case_captured_stages", set()))
        if "02-action.png" in captured_stages:
            shot_names.append("02-action.png")
        else:
            await screenshot(active_page, run_id, case_id, "02-action.png")
            shot_names.append("02-action.png")
        await screenshot(active_page, run_id, case_id, "03-final.png")
        shot_names.append("03-final.png")

    shots = finalize_screenshots(run_id, case_id, shot_names, keep_archive=keep_archive or status == "failed")
    for shot in shots:
        recorder.screenshot(shot)
    observed_asset_path = write_observed_asset(recorder, status)

    return {
        "case": case,
        "system": system,
        "screenshots": shots,
        "observed_asset_path": str(observed_asset_path),
        "status": status,
        "failure_point": failure_point,
        "error": error,
    }


def apply_runtime_case_inputs(case: dict[str, Any], system: dict[str, Any]) -> None:
    asset = case.setdefault("automation_asset", {})
    values = asset.setdefault("input_values", {})
    environment = system.get("_runtime_environment") or {}
    accounts = system.get("_runtime_accounts") or {}
    labo = accounts.get("labo") or {}
    jesse = accounts.get("jesse") or {}
    tester = accounts.get("tester") or {}

    if tester.get("username"):
        values["tester_user"] = tester["username"]
        values["username"] = tester["username"]
    if tester.get("password"):
        values["password"] = tester["password"]
    if labo.get("username"):
        values["labo_username"] = labo["username"]
    if labo.get("password"):
        values["labo_password"] = labo["password"]
    if jesse.get("username"):
        values["jesse_username"] = jesse["username"]
    if jesse.get("password"):
        values["jesse_password"] = jesse["password"]
    if environment.get("dev_login_url"):
        values["jesse_login_url"] = environment["dev_login_url"]
    if environment.get("remote_help_url"):
        values["remote_help_url"] = environment["remote_help_url"]
