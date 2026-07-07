from __future__ import annotations

import asyncio
import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from runner.browser import close_browser, launch_browser, load_case, load_case_file, load_system
from runner.cases import run_case, run_case_data
from runner.reporting import write_report

BATCH_ORDER = [
    "TC-ICM-001",
    "TC-ICM-002",
    "TC-ICM-003",
    "TC-ICM-004",
    "TC-ICM-005",
    "TC-ICM-006",
    "TC-ICM-007",
    "TC-ICM-008",
    "TC-ICM-009",
    "TC-ICM-010",
    "TC-ICM-011",
    "TC-ICM-012",
]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ICM Playwright runner")
    parser.add_argument("command", choices=["run-case", "run-batch", "run-draft", "agent-explore"])
    parser.add_argument("arg")
    parser.add_argument("run_id", nargs="?")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--screenshot-policy", choices=["latest_plus_failed_archive", "always_archive"], default="latest_plus_failed_archive")
    parser.add_argument("--batch-range", default="TC-ICM-001..TC-ICM-012")
    # 路线 B · T5：单 case 失败时自动重试 N 次（0~3，默认 0 即不重试）
    parser.add_argument("--retry", type=int, default=0, help="失败重试次数（0~3，0=不重试）")
    return parser.parse_args(argv)


def _normalize_retry(value: int) -> int:
    """将用户输入的 --retry 限制到 0~3（PRD US-B1 / 架构 B1）。"""
    if value is None or value < 0:
        return 0
    if value > 3:
        return 3
    return int(value)


def _preload_system_for_launch(command: str, arg: str) -> dict[str, Any] | None:
    """路线 B · T6：launch_browser 前加载 system，用于加载 storage_state 复用登录会话。

    - run-case: 从单个 case_id 推导 system
    - run-batch: 从 BATCH_ORDER[0] 推导 system（所有 12 条用例同一 system）
    - 加载失败 → 返回 None（fallback 到默认 context，重新登录）
    """
    try:
        if command == "run-case":
            case_id = arg
        elif command == "run-batch":
            case_id = BATCH_ORDER[0]
        elif command == "run-draft":
            case_data = load_case_file(arg)
            return load_system(case_data["system"], case_data)
        elif command == "agent-explore":
            arg_path = Path(arg)
            case_data = load_case_file(arg_path) if arg_path.exists() else load_case(arg)
            return load_system(case_data["system"], case_data)
        else:
            return None
        case_data = load_case(case_id)
        return load_system(case_data["system"], case_data)
    except Exception as exc:
        print(f"[runner] preload system failed, fallback to fresh context: {exc}")
        return None


def _should_reuse_storage_state(command: str) -> bool:
    return False


def cases_for_batch(batch_range: str) -> list[str]:
    value = batch_range.strip()
    if not value or value == "TC-ICM-001..TC-ICM-012":
        return BATCH_ORDER
    if "," in value:
        selected = [item.strip().upper() for item in value.split(",") if item.strip()]
        return [case_id for case_id in BATCH_ORDER if case_id in selected]
    if ".." in value:
        start, end = [item.strip().upper() for item in value.split("..", 1)]
        try:
            start_index = BATCH_ORDER.index(start)
            end_index = BATCH_ORDER.index(end)
        except ValueError as exc:
            raise ValueError(f"Unsupported batch range: {batch_range}") from exc
        if start_index > end_index:
            raise ValueError(f"Unsupported descending batch range: {batch_range}")
        return BATCH_ORDER[start_index : end_index + 1]
    selected = value.upper()
    if selected in BATCH_ORDER:
        return [selected]
    raise ValueError(f"Unsupported batch range: {batch_range}")


async def main() -> int:
    args = parse_args(sys.argv[1:])
    keep_archive = args.screenshot_policy == "always_archive"
    max_retries = _normalize_retry(getattr(args, "retry", 0))

    # 路线 B · T6：提前加载首个 case 对应的 system，用于 launch_browser 加载 storage_state
    system_for_launch = _preload_system_for_launch(args.command, args.arg)

    exit_status = 0
    session = await launch_browser(
        headless=args.headless,
        system=system_for_launch,
        reuse_storage_state=_should_reuse_storage_state(args.command),
    )
    try:
        if args.command == "agent-explore":
            from runner.agent_explore import run_agent_explore

            run_id = args.run_id or f"{datetime.now():%Y%m%d-%H%M}-{args.arg.lower()}-agent-explore"
            result = await run_agent_explore(session.page, run_id, args.arg)
            if result.get("status") != "passed":
                exit_status = 1
        elif args.command == "run-batch":
            run_id = args.arg
            try:
                batch_cases = cases_for_batch(args.batch_range)
            except ValueError as exc:
                print(str(exc))
                return 1
            for case_id in batch_cases:
                case_run_id = f"{run_id}-{case_id.lower()}"
                print(f"::batch-case-start run_id={case_run_id} case_id={case_id}", flush=True)
                result = await run_case(
                    session.page,
                    case_run_id,
                    case_id,
                    keep_archive=keep_archive,
                    max_retries=max_retries,
                )
                write_report(
                    case_run_id,
                    result["case"],
                    result["status"],
                    result["screenshots"],
                    result.get("failure_point", ""),
                    result.get("error", ""),
                    result.get("observed_asset_path", ""),
                )
                print(f"::batch-case-end run_id={case_run_id} case_id={case_id} status={result['status']}", flush=True)
                if result["status"] != "passed":
                    exit_status = 1
        elif args.command == "run-case":
            run_id = args.run_id or f"{datetime.now():%Y%m%d-%H%M}-{args.arg.lower()}"
            result = await run_case(
                session.page,
                run_id,
                args.arg,
                keep_archive=keep_archive,
                max_retries=max_retries,
            )
            write_report(
                run_id,
                result["case"],
                result["status"],
                result["screenshots"],
                result.get("failure_point", ""),
                result.get("error", ""),
                result.get("observed_asset_path", ""),
            )
            if result["status"] != "passed":
                exit_status = 1
        elif args.command == "run-draft":
            case = load_case_file(args.arg)
            run_id = args.run_id or f"{datetime.now():%Y%m%d-%H%M}-{str(case.get('id', 'draft')).lower()}"
            result = await run_case_data(
                session.page,
                run_id,
                case,
                keep_archive=keep_archive,
                max_retries=max_retries,
            )
            write_report(
                run_id,
                result["case"],
                result["status"],
                result["screenshots"],
                result.get("failure_point", ""),
                result.get("error", ""),
                result.get("observed_asset_path", ""),
            )
            if result["status"] != "passed":
                exit_status = 1
    finally:
        await close_browser(session)
    return exit_status


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
