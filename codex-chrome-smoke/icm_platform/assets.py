from __future__ import annotations

from typing import Any

import yaml

from icm_platform.paths import REPORT_DIR, ROOT, SCREENSHOTS_LATEST_DIR, TEST_CASE_DIR

BATCH_CASE_ORDER = [
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


def list_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(TEST_CASE_DIR.glob("TC-ICM-*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cases.append(
            {
                "id": data.get("id", path.stem),
                "title": data.get("title", ""),
                "status": data.get("status", "ready"),
                "path": str(path.relative_to(TEST_CASE_DIR.parents[1])),
                "has_automation_asset": bool(data.get("automation_asset")),
            }
        )
    return cases


def list_reports(limit: int = 30) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in sorted(REPORT_DIR.glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        text = path.read_text(encoding="utf-8")
        meta = parse_report(text)
        reports.append(
            {
                "run_id": path.stem,
                "case_id": meta["case_id"],
                "case_name": meta["case_name"],
                "status": meta["status"],
                "path": str(path),
                "updated_at": path.stat().st_mtime,
                "screenshot_count": len(meta["screenshots"]),
            }
        )
    return reports


def read_report(run_id: str) -> str:
    path = REPORT_DIR / f"{run_id}.md"
    if not path.exists():
        raise FileNotFoundError(run_id)
    return path.read_text(encoding="utf-8")


def list_batch_child_reports(parent_run_id: str, case_ids: list[str] | None = None) -> list[dict[str, Any]]:
    existing: dict[str, dict[str, Any]] = {}
    for path in REPORT_DIR.glob(f"{parent_run_id}-tc-icm-*.md"):
        text = path.read_text(encoding="utf-8")
        meta = parse_report(text)
        if meta["case_id"]:
            existing[meta["case_id"]] = {
                "case_id": meta["case_id"],
                "case_name": meta["case_name"],
                "run_id": path.stem,
                "status": meta["status"],
                "report_path": str(path),
                "screenshot_count": len(meta["screenshots"]),
                "updated_at": path.stat().st_mtime,
            }

    children: list[dict[str, Any]] = []
    ordered_case_ids = case_ids or BATCH_CASE_ORDER
    for index, case_id in enumerate(ordered_case_ids, start=1):
        children.append(
            existing.get(
                case_id,
                {
                    "case_id": case_id,
                    "case_name": case_id,
                    "run_id": None,
                    "status": "pending",
                    "report_path": None,
                    "screenshot_count": 0,
                    "updated_at": None,
                },
            )
            | {"order": index}
        )
    return children


def latest_screenshots(case_id: str) -> list[str]:
    folder = SCREENSHOTS_LATEST_DIR / case_id
    if not folder.exists():
        return []
    return [str(path) for path in sorted(folder.glob("*.png"))]


def parse_report(markdown: str) -> dict[str, Any]:
    case_name = ""
    case_id = ""
    status = "unknown"
    observed_asset_path = ""
    screenshots: list[dict[str, str]] = []
    in_screenshots = False

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("- case name:"):
            case_name = line.split(":", 1)[1].strip()
            case_id = case_name.split(" ", 1)[0] if case_name else ""
        elif line.startswith("- status:"):
            status = line.split(":", 1)[1].strip()
        elif line.startswith("- observed asset path:"):
            observed_asset_path = line.split(":", 1)[1].strip()
        elif line == "- screenshot paths:":
            in_screenshots = True
        elif in_screenshots and line.startswith("- "):
            rel_path = line[2:].strip().replace("\\", "/")
            parts = rel_path.split("/")
            if len(parts) >= 4 and parts[0] == "screenshots" and parts[1] == "latest":
                shot_case_id = parts[2]
                filename = parts[-1]
                absolute = ROOT / rel_path
                screenshots.append(
                    {
                        "case_id": shot_case_id,
                        "filename": filename,
                        "path": str(absolute),
                        "url": f"/api/screenshots/latest/{shot_case_id}/{filename}",
                    }
                )

    return {
        "case_id": case_id,
        "case_name": case_name,
        "status": status,
        "observed_asset_path": "" if observed_asset_path == "none" else observed_asset_path,
        "screenshots": screenshots,
    }


def report_path_for_run(run_id: str):
    return REPORT_DIR / f"{run_id}.md"
