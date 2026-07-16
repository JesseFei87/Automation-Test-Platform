"""Self-healing suggestion helpers based on element feedback.

P6 scope: classify recurring execution failures and surface deterministic
repair suggestions.  This module does not mutate selectors or execute recovery
actions; it only produces advisory metadata for later phases and prompts.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from runner.element_feedback import build_feedback_stats, load_feedback

_ERROR_RULES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "unknown_ref",
        ("unknown ref", "selected unknown ref", "ref not found", "missing ref"),
        "Refresh observation and re-bind the element to a current observation.interactives ref before acting.",
    ),
    (
        "target_not_visible",
        ("not visible", "hidden", "visible=false", "element is not visible"),
        "Scroll the element into view or rescan the current state before retrying.",
    ),
    (
        "covered_by_overlay",
        ("intercepts pointer", "pointer events", "covered", "overlay", "blocked by", "subtree intercepts"),
        "Dismiss stale overlays or hover/open the owning menu before retrying.",
    ),
    (
        "stale_element",
        ("stale", "detached", "not attached", "execution context was destroyed"),
        "Refresh the observation after navigation or DOM update, then retry with a fresh ref.",
    ),
    (
        "timeout",
        ("timeout", "timed out"),
        "Wait for the page to settle and rescan before retrying.",
    ),
    (
        "selector_unstable",
        ("strict mode violation", "resolved to", "multiple elements", "ambiguous"),
        "Prefer role/name, placeholder, data-testid, or a more stable selector candidate.",
    ),
    (
        "needs_hover",
        ("hover", "menu item", "dropdown", "not expanded"),
        "Hover or open the parent menu before clicking this element.",
    ),
)


def classify_error(error: str | None) -> str:
    text = str(error or "").lower()
    if not text:
        return "none"
    for category, terms, _suggestion in _ERROR_RULES:
        if any(term in text for term in terms):
            return category
    return "unknown_failure"


def suggestion_for_category(category: str) -> str:
    for item_category, _terms, suggestion in _ERROR_RULES:
        if item_category == category:
            return suggestion
    if category == "unknown_failure":
        return "Inspect the latest error and rescan the page state before retrying."
    return "No self-healing action is needed."


def build_healing_suggestions(records: list[dict[str, Any]], *, min_failures: int = 1) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = str(record.get("key") or record.get("element_id") or "")
        if not key:
            key = "fallback:" + "|".join(
                [
                    str(record.get("page_id") or "unknown_page"),
                    str(record.get("state") or "default"),
                    str(record.get("action") or "action"),
                    str(record.get("selector") or record.get("url") or "unknown_target"),
                ]
            )
        grouped[key].append(record)

    suggestions: dict[str, dict[str, Any]] = {}
    stats = build_feedback_stats(records)
    for key, items in grouped.items():
        failed_records = [item for item in items if not item.get("success")]
        if len(failed_records) < min_failures:
            continue
        categories = [classify_error(item.get("error")) for item in failed_records]
        categories = [category for category in categories if category != "none"]
        if not categories:
            continue
        counter = Counter(categories)
        primary = counter.most_common(1)[0][0]
        sample_error = next((str(item.get("error") or "") for item in reversed(failed_records) if item.get("error")), "")
        stat = stats.get(key, {})
        suggestions[key] = {
            "primary_issue": primary,
            "issue_counts": dict(counter),
            "suggestion": suggestion_for_category(primary),
            "sample_error": sample_error,
            "failure_count": len(failed_records),
            "success_rate": stat.get("success_rate", 0.0),
            "last_success_selector": stat.get("last_success_selector", ""),
            "last_error": stat.get("last_error", sample_error),
        }
    return suggestions


def merge_healing_into_library(library: dict[str, Any], healing: dict[str, dict[str, Any]]) -> dict[str, Any]:
    merged = {**library}
    elements: list[dict[str, Any]] = []
    for element in library.get("elements") or []:
        copied = dict(element)
        element_id = str(copied.get("element_id") or "")
        suggestion = healing.get(element_id)
        if suggestion:
            copied["self_healing"] = suggestion
            copied["healing_issue"] = suggestion.get("primary_issue", "")
            copied["healing_suggestion"] = suggestion.get("suggestion", "")
        elements.append(copied)
    merged["elements"] = elements
    return merged


def build_healing_from_feedback_file(path: Path | None = None, *, min_failures: int = 1) -> dict[str, dict[str, Any]]:
    feedback = load_feedback(path)
    return build_healing_suggestions(feedback.get("records") or [], min_failures=min_failures)


def merge_healing_files(
    *,
    library_path: Path,
    feedback_path: Path | None = None,
    output_path: Path | None = None,
    min_failures: int = 1,
) -> Path:
    library = json.loads(library_path.read_text(encoding="utf-8"))
    healing = build_healing_from_feedback_file(feedback_path, min_failures=min_failures)
    merged = merge_healing_into_library(library, healing)
    target = output_path or library_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def format_healing_hint(element: dict[str, Any]) -> str:
    issue = str(element.get("healing_issue") or "")
    suggestion = str(element.get("healing_suggestion") or "")
    if not issue and isinstance(element.get("self_healing"), dict):
        issue = str(element["self_healing"].get("primary_issue") or "")
        suggestion = str(element["self_healing"].get("suggestion") or "")
    if not issue:
        return ""
    return f"healing: {issue} - {suggestion}"
