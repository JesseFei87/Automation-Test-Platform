from __future__ import annotations

import asyncio
import argparse
import sys
from datetime import datetime

from runner.browser import close_browser, launch_browser
from runner.cases import run_case
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
    parser.add_argument("command", choices=["run-case", "run-batch"])
    parser.add_argument("arg")
    parser.add_argument("run_id", nargs="?")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--screenshot-policy", choices=["latest_plus_failed_archive", "always_archive"], default="latest_plus_failed_archive")
    parser.add_argument("--batch-range", default="TC-ICM-001..TC-ICM-012")
    return parser.parse_args(argv)


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
    session = await launch_browser(headless=args.headless)
    try:
        if args.command == "run-batch":
            run_id = args.arg
            try:
                batch_cases = cases_for_batch(args.batch_range)
            except ValueError as exc:
                print(str(exc))
                return 1
            for case_id in batch_cases:
                case_run_id = f"{run_id}-{case_id.lower()}"
                result = await run_case(session.page, case_run_id, case_id, keep_archive=keep_archive)
                write_report(
                    case_run_id,
                    result["case"],
                    result["status"],
                    result["screenshots"],
                    result.get("failure_point", ""),
                    result.get("error", ""),
                    result.get("observed_asset_path", ""),
                )
        elif args.command == "run-case":
            run_id = args.run_id or f"{datetime.now():%Y%m%d-%H%M}-{args.arg.lower()}"
            result = await run_case(session.page, run_id, args.arg, keep_archive=keep_archive)
            write_report(
                run_id,
                result["case"],
                result["status"],
                result["screenshots"],
                result.get("failure_point", ""),
                result.get("error", ""),
                result.get("observed_asset_path", ""),
            )
    finally:
        await close_browser(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
