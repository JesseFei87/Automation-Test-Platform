from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner.evidence_recorder import evidence_summary

ROOT = Path(__file__).resolve().parents[1]
STEP_DETAIL_DIR = ROOT / "reports" / "step-details"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def step_details_path(run_id: str) -> Path:
    return STEP_DETAIL_DIR / f"{run_id}.json"


def planned_step_titles(case: dict[str, Any]) -> list[str]:
    case_steps = [str(item).strip() for item in (case.get("steps") or []) if str(item).strip()]
    if case_steps:
        return case_steps
    asset = case.get("automation_asset") or {}
    operation_steps = [str(item).strip() for item in (asset.get("operation_steps") or []) if str(item).strip()]
    if operation_steps:
        return operation_steps
    title = str(case.get("title") or case.get("id") or "执行步骤").strip()
    return [title or "执行步骤"]


def initialize_step_details(run_id: str, case: dict[str, Any], *, mode: str = "worker") -> dict[str, Any]:
    started_at = utc_now_iso()
    steps = [
        {
            "step_index": index,
            "step_code": f"step_{index:02d}",
            "title": title,
            "status": "running" if index == 1 else "queued",
            "started_at": started_at if index == 1 else None,
            "finished_at": None,
            "duration_seconds": None,
            "summary": "",
            "error_message": "",
            "screenshot_url": "",
            "ai_analysis": "",
            "final_url": "",
            "command_output": [],
            "selectors": [],
            "inputs": [],
            "console_logs": [],
            "network_logs": [],
            "dom_snapshot_url": "",
            "events": [],
        }
        for index, title in enumerate(planned_step_titles(case), start=1)
    ]
    payload = {
        "run_id": run_id,
        "case_id": str(case.get("id") or ""),
        "case_name": f"{case.get('id', '')} {case.get('title', '')}".strip(),
        "mode": mode,
        "status": "running",
        "operator": "admin",
        "started_at": started_at,
        "finished_at": None,
        "duration_seconds": None,
        "final_url": "",
        "summary": {
            "title": str(case.get("title") or case.get("id") or ""),
            "conclusion": "",
            "failure_reason": "",
            "ai_analysis": "",
        },
        "steps": steps,
        "artifacts": {
            "report_markdown_url": "",
            "observed_asset_path": "",
            "observed_asset_merge_url": f"/api/runs/{run_id}/merge-observed-asset",
            "trace_download_url": f"/api/runs/{run_id}/evidence/trace",
            "candidate_flow_url": "",
        },
    }
    write_step_details(run_id, payload)
    return payload


def record_step_screenshot(run_id: str, screenshot_path: str, final_url: str = "") -> None:
    payload = load_step_details(run_id)
    match = re.fullmatch(r"step-(\d+)\.png", Path(screenshot_path).name, flags=re.IGNORECASE)
    if not payload or not match:
        return
    index = int(match.group(1))
    steps = payload.get("steps") or []
    if index < 1 or index > len(steps):
        return

    now = utc_now_iso()
    step = steps[index - 1]
    step["status"] = "completed"
    step["started_at"] = step.get("started_at") or payload.get("started_at") or now
    step["finished_at"] = now
    step["duration_seconds"] = _duration_seconds(step["started_at"], now)
    step["summary"] = step.get("summary") or step.get("title") or ""
    step["screenshot_url"] = _screenshot_url(screenshot_path)
    step["final_url"] = final_url
    payload["final_url"] = final_url
    if index < len(steps) and steps[index].get("status") == "queued":
        steps[index]["status"] = "running"
        steps[index]["started_at"] = now
    write_step_details(run_id, payload)


def finalize_step_details(
    run_id: str,
    case: dict[str, Any],
    result: dict[str, Any],
    *,
    started_at: str | None = None,
    finished_at: str | None = None,
    mode: str = "worker",
) -> dict[str, Any]:
    payload = initialize_step_details(run_id, case, mode=mode)
    payload["started_at"] = started_at or payload["started_at"]
    payload["finished_at"] = finished_at or utc_now_iso()
    payload["status"] = "completed" if result.get("status") == "passed" else "failed"
    payload["final_url"] = str(result.get("final_url") or "")
    payload["duration_seconds"] = _duration_seconds(payload["started_at"], payload["finished_at"])
    payload["summary"] = {
        "title": str(case.get("title") or case.get("id") or ""),
        "conclusion": "执行成功" if result.get("status") == "passed" else "执行失败",
        "failure_reason": str(result.get("error") or ""),
        "ai_analysis": str(result.get("error") or ""),
    }
    payload["artifacts"]["observed_asset_path"] = str(result.get("observed_asset_path") or "")
    payload["artifacts"]["report_markdown_url"] = f"/api/reports/{run_id}"

    screenshots = [str(item) for item in (result.get("screenshots") or [])]
    evidence = evidence_summary(run_id)
    step_screenshots = _step_screenshots(screenshots)
    step_count = len(payload["steps"])
    failing_index = min(len(step_screenshots) + 1, step_count) if result.get("status") != "passed" else 0
    for index, step in enumerate(payload["steps"], start=1):
        if failing_index == 0:
            step["status"] = "completed"
        elif index < failing_index:
            step["status"] = "completed"
        elif index == failing_index:
            step["status"] = "failed"
        else:
            step["status"] = "queued"
        if index == failing_index and failing_index > 0:
            step["summary"] = str(result.get("error") or result.get("failure_point") or step["title"])
            step["error_message"] = str(result.get("error") or "")
        else:
            step["summary"] = step["title"]
        step["started_at"] = payload["started_at"]
        step["finished_at"] = payload["finished_at"] if step["status"] in {"completed", "failed"} else None
        step["duration_seconds"] = payload["duration_seconds"]
        step["final_url"] = payload["final_url"]
        shot_path = step_screenshots.get(index, "")
        if index == failing_index and not shot_path:
            shot_path = next((item for item in reversed(screenshots) if Path(item).name == "03-final.png"), "")
        if index == step_count and not shot_path:
            shot_path = next((item for item in reversed(screenshots) if Path(item).name == "03-final.png"), "")
        step["screenshot_url"] = _screenshot_url(shot_path)
        step["command_output"] = [str(result.get("error") or "")] if step["status"] == "failed" and result.get("error") else []
        step["selectors"] = _selector_keys(case)
        step["inputs"] = _input_items(case)
        step["console_logs"] = evidence.get("console", {}).get("latest", [])
        step["network_logs"] = evidence.get("network", {}).get("latest", [])
        step["events"] = evidence.get("events", {}).get("latest", [])
        dom_files = evidence.get("dom", {}).get("files", [])
        step["dom_snapshot_url"] = dom_files[-1]["url"] if dom_files else ""
    write_step_details(run_id, payload)
    return payload


def load_step_details(run_id: str) -> dict[str, Any] | None:
    path = step_details_path(run_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_step_details(run_id: str, payload: dict[str, Any]) -> Path:
    path = step_details_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def _duration_seconds(started_at: str | None, finished_at: str | None) -> float | None:
    if not started_at or not finished_at:
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, round((finished - started).total_seconds(), 3))


def _selector_keys(case: dict[str, Any]) -> list[str]:
    selectors = (case.get("automation_asset") or {}).get("selectors") or {}
    if isinstance(selectors, dict):
        return [str(key) for key in selectors.keys()]
    if isinstance(selectors, list):
        return [str(item) for item in selectors]
    return []


def _input_items(case: dict[str, Any]) -> list[dict[str, str]]:
    values = (case.get("automation_asset") or {}).get("input_values") or {}
    if not isinstance(values, dict):
        return []
    return [{"name": str(key), "value": str(value)} for key, value in values.items()]


def _screenshot_url(path_text: str) -> str:
    if not path_text:
        return ""
    normalized = path_text.replace("\\", "/")
    parts = normalized.split("/")
    if len(parts) >= 4 and parts[0] == "screenshots" and parts[1] == "latest":
        return f"/api/screenshots/latest/{parts[2]}/{parts[-1]}"
    if len(parts) >= 4 and parts[0] == "screenshots" and parts[1] == "runs":
        run_id = parts[2]
        return f"/api/screenshots/runs/{run_id}/{parts[-1]}"
    return ""


def _step_screenshots(paths: list[str]) -> dict[int, str]:
    screenshots: dict[int, str] = {}
    for path in paths:
        match = re.fullmatch(r"step-(\d+)\.png", Path(path).name, flags=re.IGNORECASE)
        if match:
            screenshots[int(match.group(1))] = path
    return screenshots
