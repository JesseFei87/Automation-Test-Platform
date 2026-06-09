from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


STATUS_LABELS = {
    "queued": "Queued",
    "running": "Running",
    "passed": "Passed",
    "failed": "Failed",
}


def summarize_run_task(task: dict[str, Any]) -> dict[str, Any]:
    started_at = parse_utc(task.get("started_at"))
    finished_at = parse_utc(task.get("finished_at"))
    duration_seconds = int((finished_at - started_at).total_seconds()) if started_at and finished_at else None

    return {
        "display_name": task.get("case_id") or "Batch 001-012",
        "status_label": STATUS_LABELS.get(str(task.get("status", "")), str(task.get("status", "Unknown")).title()),
        "is_active": task.get("status") in {"queued", "running"},
        "artifact_ready": bool(task.get("report_path")),
        "duration_seconds": duration_seconds,
        "duration_label": format_duration(duration_seconds),
    }


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "--"
    minutes, remainder = divmod(max(seconds, 0), 60)
    return f"{minutes:02d}:{remainder:02d}"
