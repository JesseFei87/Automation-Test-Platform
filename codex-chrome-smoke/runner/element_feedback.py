"""Element execution feedback store.

P3 scope: persist execution feedback for element-library candidates and merge
summary statistics back into ``library.json`` records.  The functions here are
pure or file-path injectable so callers can opt in without adding side effects
to the Agent loop during tests.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEEDBACK_PATH = ROOT / "reports" / "element-library" / "feedback.json"
_FEEDBACK_PATH_ENV = "ELEMENT_FEEDBACK_PATH"
_FEEDBACK_ENABLED_ENV = "ELEMENT_FEEDBACK_ENABLED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def feedback_key(
    *,
    element_id: str = "",
    page_id: str = "",
    state: str = "",
    action: str = "",
    selector: str = "",
    url: str = "",
) -> str:
    """Return a stable page, selector, and action key independent of element ids."""
    normalized_selector = " ".join(str(selector or "").split())
    target = normalized_selector or str(url or "").strip() or str(element_id or "").strip() or "unknown_target"
    parts = [str(page_id or "unknown_page").strip(), str(action or "action").strip(), target]
    return "stable:" + "|".join(part.lower() for part in parts)


def empty_feedback() -> dict[str, Any]:
    return {"version": "1.0", "updated_at": "", "records": [], "stats": {}}


def feedback_enabled() -> bool:
    return os.environ.get(_FEEDBACK_ENABLED_ENV, "1").lower() not in {"0", "false", "no", "off"}


def resolve_feedback_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    configured = os.environ.get(_FEEDBACK_PATH_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_FEEDBACK_PATH


def load_feedback(path: Path | None = None) -> dict[str, Any]:
    feedback_path = resolve_feedback_path(path)
    if not feedback_path.exists():
        return empty_feedback()
    try:
        payload = json.loads(feedback_path.read_text(encoding="utf-8"))
    except Exception:
        return empty_feedback()
    if not isinstance(payload, dict):
        return empty_feedback()
    payload.setdefault("version", "1.0")
    payload.setdefault("updated_at", "")
    payload.setdefault("records", [])
    payload.setdefault("stats", {})
    if not isinstance(payload["records"], list):
        payload["records"] = []
    if not isinstance(payload["stats"], dict):
        payload["stats"] = {}
    return payload


def write_feedback(feedback: dict[str, Any], path: Path | None = None) -> Path:
    feedback_path = resolve_feedback_path(path)
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    feedback_path.write_text(json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8")
    return feedback_path


def normalize_feedback_record(
    *,
    element_id: str = "",
    page_id: str = "",
    state: str = "default",
    action: str,
    selector: str = "",
    success: bool,
    duration_ms: int | float = 0,
    url: str = "",
    error: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    key = feedback_key(
        element_id=element_id,
        page_id=page_id,
        state=state,
        action=action,
        selector=selector,
        url=url,
    )
    return {
        "key": key,
        "stable_key": key,
        "element_id": element_id,
        "page_id": page_id,
        "state": state or "default",
        "action": action,
        "selector": selector,
        "success": bool(success),
        "duration_ms": int(duration_ms or 0),
        "url": url,
        "error": error or None,
        "created_at": created_at or _now_iso(),
    }


def build_feedback_stats(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for record in records:
        key = feedback_key(
            element_id=str(record.get("element_id") or ""),
            page_id=str(record.get("page_id") or ""),
            action=str(record.get("action") or ""),
            selector=str(record.get("selector") or ""),
            url=str(record.get("url") or ""),
        )
        item = stats.setdefault(
            key,
            {
                "total": 0,
                "success": 0,
                "failed": 0,
                "success_rate": 0.0,
                "last_success_selector": "",
                "last_error": "",
                "last_action": "",
                "last_url": "",
                "last_seen_at": "",
            },
        )
        item["total"] += 1
        item["last_action"] = str(record.get("action") or "")
        item["last_url"] = str(record.get("url") or "")
        item["last_seen_at"] = str(record.get("created_at") or "")
        if record.get("success"):
            item["success"] += 1
            if record.get("selector"):
                item["last_success_selector"] = str(record.get("selector") or "")
        else:
            item["failed"] += 1
            if record.get("error"):
                item["last_error"] = str(record.get("error") or "")
        item["success_rate"] = round(item["success"] / item["total"], 4) if item["total"] else 0.0
    return stats


def record_element_feedback(
    *,
    element_id: str = "",
    page_id: str = "",
    state: str = "default",
    action: str,
    selector: str = "",
    success: bool,
    duration_ms: int | float = 0,
    url: str = "",
    error: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    feedback = load_feedback(path)
    record = normalize_feedback_record(
        element_id=element_id,
        page_id=page_id,
        state=state,
        action=action,
        selector=selector,
        success=success,
        duration_ms=duration_ms,
        url=url,
        error=error,
    )
    feedback["records"].append(record)
    feedback["stats"] = build_feedback_stats(feedback["records"])
    feedback["updated_at"] = _now_iso()
    write_feedback(feedback, path)
    return feedback


def _combine_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(int(item.get("total") or 0) for item in items)
    success = sum(int(item.get("success") or 0) for item in items)
    failed = sum(int(item.get("failed") or 0) for item in items)
    latest = max(items, key=lambda item: str(item.get("last_seen_at") or ""))
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "success_rate": round(success / total, 4) if total else 0.0,
        "last_success_selector": next((str(item.get("last_success_selector") or "") for item in reversed(items) if item.get("last_success_selector")), ""),
        "last_error": next((str(item.get("last_error") or "") for item in reversed(items) if item.get("last_error")), ""),
        "last_action": str(latest.get("last_action") or ""),
        "last_seen_at": str(latest.get("last_seen_at") or ""),
    }


def merge_feedback_into_library(library: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of library with feedback stats copied onto matching elements."""
    stats = feedback.get("stats") or build_feedback_stats(feedback.get("records") or [])
    legacy_record_stats: dict[str, list[dict[str, Any]]] = {}
    for record in feedback.get("records") or []:
        element_id = str(record.get("element_id") or "").strip()
        if not element_id:
            continue
        key = feedback_key(
            element_id=element_id,
            page_id=str(record.get("page_id") or ""),
            action=str(record.get("action") or ""),
            selector=str(record.get("selector") or ""),
            url=str(record.get("url") or ""),
        )
        if key in stats:
            legacy_record_stats.setdefault(element_id, []).append(stats[key])
    merged = {**library}
    merged_elements: list[dict[str, Any]] = []
    for element in library.get("elements") or []:
        copied = dict(element)
        element_id = str(copied.get("element_id") or "")
        selectors = [str(selector or "") for selector in copied.get("selectors") or []] or [""]
        actions = [str(action or "") for action in copied.get("actions") or []] or [""]
        matching_stats = [
            stats[key]
            for selector in selectors
            for action in actions
            if (key := feedback_key(page_id=str(copied.get("page_id") or ""), action=action, selector=selector)) in stats
        ]
        stat = _combine_stats(matching_stats) if matching_stats else stats.get(element_id)
        if not stat and legacy_record_stats.get(element_id):
            stat = _combine_stats(legacy_record_stats[element_id])
        if stat:
            copied["execution_count"] = stat.get("total", 0)
            copied["success_count"] = stat.get("success", 0)
            copied["failed_count"] = stat.get("failed", 0)
            copied["success_rate"] = stat.get("success_rate", 0.0)
            copied["last_success_selector"] = stat.get("last_success_selector", "")
            copied["last_error"] = stat.get("last_error", "")
            copied["last_action"] = stat.get("last_action", "")
            copied["last_seen_at"] = stat.get("last_seen_at", "")
        merged_elements.append(copied)
    merged["elements"] = merged_elements
    return merged


def merge_feedback_files(
    *,
    library_path: Path,
    feedback_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    library = json.loads(library_path.read_text(encoding="utf-8"))
    feedback = load_feedback(feedback_path)
    merged = merge_feedback_into_library(library, feedback)
    target = output_path or library_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
