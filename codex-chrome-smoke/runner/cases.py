from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from playwright.async_api import Page

from runner.asset_recorder import attach_asset_recorder, get_asset_recorder, write_observed_asset
from runner.evidence_recorder import attach_evidence_recorder, get_evidence_recorder
from runner.browser import (
    attach_case_runtime,
    ensure_logged_in,
    ensure_logged_out,
    finalize_screenshots,
    is_logged_in,
    load_case,
    load_system,
    open_login_page,
    save_storage_state,
    screenshot,
)
from runner.case_login import case_requires_authenticated_session, resolve_case_login_credentials
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
from runner.step_details import finalize_step_details, initialize_step_details

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


def _flow_path_for_case(case_id: str) -> Path:
    tail = case_id.rsplit("-", 1)[-1].lower()
    return Path(__file__).resolve().parent / "flows" / f"icm_case_{tail}.py"


def _load_dynamic_runner(case_id: str) -> CaseRunner | None:
    path = _flow_path_for_case(case_id)
    if not path.exists():
        return None
    module_name = f"runner.flows.dynamic_{path.stem}_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = getattr(module, "run", None)
    return run if callable(run) else None


# 路线 B：每次 attempt 写入 case_runs 表 + retry 日志
DB_PATH = Path(__file__).resolve().parents[1] / "platform-data" / "icm-platform.sqlite3"
RETRY_LOG_DIR = Path(__file__).resolve().parents[1] / "platform-data" / "runner-logs"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_case_run(case_id: str, run_id: str, status: str, started_at: str, finished_at: str, attempt: int) -> None:
    """落 case_runs 表。失败时仅打印，不中断用例执行（runner 不应因落库失败而崩）。"""
    if not DB_PATH.exists():
        return
    try:
        with sqlite3.connect(str(DB_PATH), timeout=5) as conn:
            conn.execute(
                """
                insert into case_runs(case_id, run_id, passed, started_at, finished_at, attempt)
                values (?, ?, ?, ?, ?, ?)
                """,
                (case_id, run_id, 1 if status == "passed" else 0, started_at, finished_at, attempt),
            )
    except sqlite3.OperationalError as exc:
        # 表结构可能还没初始化（init_db 未跑）
        print(f"[runner] case_runs write skipped: {exc}")
    except Exception as exc:  # pragma: no cover - 防御
        print(f"[runner] case_runs write failed: {exc}")


def _append_retry_log(run_id: str, message: str) -> None:
    """把 retry / 状态事件追加到 platform-data/runner-logs/{run_id}.log。"""
    try:
        RETRY_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = RETRY_LOG_DIR / f"{run_id}.log"
        with log_path.open("a", encoding="utf-8") as fp:
            fp.write(f"[{_utc_now_iso()}] {message}\n")
    except Exception:  # pragma: no cover - 防御
        pass


async def run_case(
    page: Page,
    run_id: str,
    case_id: str,
    keep_archive: bool = False,
    max_retries: int = 0,
) -> dict[str, Any]:
    """路线 B · T5：包裹 retry loop（max_retries=0~3）。每次 attempt 写 case_runs 表。

    - attempts = max_retries + 1（含首次执行）
    - 重试间隔固定 1 秒
    - 任一 attempt passed → 立即返回 passed；最后一次仍 failed 才标 failed
    - 全部失败时在 runner-logs/{run_id}.log 追加 `retry exhausted` 行
    """
    case = load_case(case_id)
    return await run_case_data(page, run_id, case, keep_archive=keep_archive, max_retries=max_retries)


async def run_case_data(
    page: Page,
    run_id: str,
    case: dict[str, Any],
    keep_archive: bool = False,
    max_retries: int = 0,
) -> dict[str, Any]:
    case_id = str(case.get("id") or "")
    system = load_system(case["system"], case)
    apply_runtime_case_inputs(case, system)
    run_started_at = _utc_now_iso()
    initialize_step_details(run_id, case, mode="worker")

    # 防御：max_retries 限制 0~3（与 PRD US-B1 / main.py --retry 一致）
    if max_retries < 0:
        max_retries = 0
    if max_retries > 3:
        max_retries = 3

    attempts = max_retries + 1
    final_status = "failed"
    final_attempt_no = 0
    last_result: dict[str, Any] | None = None

    runner = CASE_RUNNERS.get(case_id) or _load_dynamic_runner(case_id)
    if runner is None:
        error = f"Unsupported case: {case_id}. No Python flow is registered for this draft yet."
        result = {
            "case": case,
            "system": system,
            "screenshots": [],
            "observed_asset_path": "",
            "status": "failed",
            "failure_point": error,
            "error": error,
            "attempts": 0,
            "max_retries": max_retries,
        }
        finalize_step_details(run_id, case, result, started_at=run_started_at, finished_at=_utc_now_iso(), mode="worker")
        return result

    for attempt_no in range(1, attempts + 1):
        # attempt > 1 时先清理 page 状态再重试
        if attempt_no > 1:
            try:
                await page.context.clear_cookies()
            except Exception:
                pass
            try:
                await page.goto("about:blank")
            except Exception:
                pass
            _append_retry_log(
                run_id,
                f"retry attempt={attempt_no}/{attempts} case_id={case_id}",
            )

        # 每次 attempt 独立：runtime 标记 + asset recorder
        attach_case_runtime(page, run_id, case_id)
        attach_asset_recorder(page, run_id, case_id)
        evidence = attach_evidence_recorder(page, run_id, case_id)
        await evidence.start(page)
        await ensure_logged_out(page, system)
        await open_login_page(page, system)
        if case_requires_authenticated_session(case):
            username, password = resolve_case_login_credentials(case, system)
            if not username or not password:
                raise RuntimeError(f"{case_id} requires an authenticated session but no login credentials were resolved")
            await ensure_logged_in(page, system, username=username, password=password)
        await screenshot(page, run_id, case_id, "01-entry.png")
        shot_names: list[str] = ["01-entry.png"]
        failure_point = ""
        error = ""

        try:
            evidence.event(page, "case_start", f"started {case_id} attempt {attempt_no}")
            await runner(page, system, case)
            status = "passed"
            evidence.event(page, "case_passed", f"passed {case_id} attempt {attempt_no}")
        except Exception as exc:
            status = "failed"
            failure_point = traceback.format_exc(limit=3)
            error = str(exc)
            evidence.event(page, "case_failed", f"failed {case_id} attempt {attempt_no}", error=error)
        finally:
            active_page = getattr(page, "_case_page", page)
            active_evidence = get_evidence_recorder(active_page) or evidence
            captured_stages = set(getattr(page, "_case_captured_stages", set()))
            captured_stages.update(getattr(active_page, "_case_captured_stages", set()))
            shot_names.extend(sorted(name for name in captured_stages if name.startswith("step-") and name.endswith(".png")))
            if "02-action.png" in captured_stages:
                shot_names.append("02-action.png")
            else:
                await screenshot(active_page, run_id, case_id, "02-action.png")
                shot_names.append("02-action.png")
            await screenshot(active_page, run_id, case_id, "03-final.png")
            shot_names.append("03-final.png")
            if status == "failed":
                await active_evidence.dom_snapshot(active_page, "failure.html")
            await active_evidence.stop(active_page)

        shots = finalize_screenshots(
            run_id, case_id, shot_names, keep_archive=keep_archive or status == "failed"
        )
        recorder = get_asset_recorder(page)
        for shot in shots:
            recorder.screenshot(shot)
        observed_asset_path = write_observed_asset(recorder, status)

        # 路线 B · T6：若当前仍处于登录态，best-effort 保存 storage_state
        # （仅在已登录时落盘，避免污染 storage_state 为"已登出"快照）
        try:
            if await is_logged_in(page, system):
                await save_storage_state(page.context, system)
        except Exception:
            pass

        # 落 case_runs（attempt 字段从 1 开始）
        started_at = _utc_now_iso()
        finished_at = _utc_now_iso()
        _record_case_run(case_id, run_id, status, started_at, finished_at, attempt_no)

        last_result = {
            "case": case,
            "system": system,
            "screenshots": shots,
            "observed_asset_path": str(observed_asset_path),
            "status": status,
            "failure_point": failure_point,
            "error": error,
        }
        final_status = status
        final_attempt_no = attempt_no

        if status == "passed":
            if attempt_no > 1:
                _append_retry_log(
                    run_id,
                    f"retry recovered case_id={case_id} attempt={attempt_no}/{attempts}",
                )
            break

        # 未通过且还有 retry 余量：sleep 1s
        if attempt_no < attempts:
            await asyncio.sleep(1)

    # 全部 attempts 失败
    if final_status == "failed" and attempts > 1:
        _append_retry_log(
            run_id,
            f"retry exhausted case_id={case_id} attempts={final_attempt_no}/{attempts} last_error={last_result.get('error', '') if last_result else ''}",
        )

    if last_result is None:
        # 理论上不会到这里（runner 必为非 None，已在循环前 raise）
        return {
            "case": case,
            "system": system,
            "screenshots": [],
            "observed_asset_path": "",
            "status": "failed",
            "failure_point": "",
            "error": "no result",
            "attempts": 0,
            "max_retries": max_retries,
        }

    run_finished_at = _utc_now_iso()
    last_result["final_url"] = getattr(page, "url", "")
    finalize_step_details(
        run_id,
        case,
        last_result,
        started_at=run_started_at,
        finished_at=run_finished_at,
        mode="worker",
    )

    return {
        **last_result,
        "attempts": final_attempt_no,
        "max_retries": max_retries,
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
