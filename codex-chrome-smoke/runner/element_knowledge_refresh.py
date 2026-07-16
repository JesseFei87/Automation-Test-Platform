"""One-shot element knowledge refresh pipeline.

P8 scope: compose the previous stages into one deterministic refresh flow:
scan/build library -> merge feedback stats -> merge self-healing hints -> write
refreshed library and a small summary.  The scan step is optional so CI can run
without launching a browser.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from runner.element_feedback import load_feedback, merge_feedback_into_library
from runner.element_knowledge_report import write_element_knowledge_reports
from runner.element_scanner import DEFAULT_LIBRARY_PATH, build_library, deduplicate_library_elements, default_scan_targets, scan_targets, write_library
from runner.element_self_healing import build_healing_suggestions, merge_healing_into_library

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = ROOT / "reports" / "element-library" / "refresh-summary.json"
ProgressCallback = Callable[[dict[str, Any]], None]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _previous_page_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        library = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    identities_by_page: dict[str, set[tuple[tuple[str, ...], tuple[str, ...]]]] = {}
    for element in library.get("elements") or []:
        page_id = str(element.get("page_id") or "").strip()
        if not page_id or str(element.get("state") or "default") != "default":
            continue
        selectors = tuple(sorted(str(value) for value in element.get("selectors") or []))
        actions = tuple(sorted(str(value) for value in element.get("actions") or []))
        identities_by_page.setdefault(page_id, set()).add((selectors, actions))
    return {page_id: len(identities) for page_id, identities in identities_by_page.items()}


def _targets_with_quality_gate(targets: list[dict[str, Any]], previous_counts: dict[str, int]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for target in targets:
        copied = dict(target)
        page_id = str(copied.get("page_id") or "")
        configured_minimum = max(0, int(copied.get("minimum_interactive_count") or 0))
        previous_count = previous_counts.get(page_id, 0)
        derived_minimum = (previous_count + 1) // 2 if previous_count >= 12 else 0
        copied["minimum_interactive_count"] = max(configured_minimum, derived_minimum)
        prepared.append(copied)
    return prepared


def merge_scanned_pages(existing: dict[str, Any], scanned: dict[str, Any]) -> dict[str, Any]:
    """Replace only pages observed in this scan while retaining other library pages."""
    scanned_page_ids = {str(page.get("page_id") or "").strip() for page in scanned.get("pages") or []}
    scanned_page_ids.discard("")
    retained_pages = [page for page in existing.get("pages") or [] if str(page.get("page_id") or "").strip() not in scanned_page_ids]
    retained_elements = [element for element in existing.get("elements") or [] if str(element.get("page_id") or "").strip() not in scanned_page_ids]
    return {
        **scanned,
        "pages": retained_pages + list(scanned.get("pages") or []),
        "elements": retained_elements + list(scanned.get("elements") or []),
    }


def _load_library_for_page_merge(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"pages": [], "elements": []}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"existing element library cannot be read: {path}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"existing element library is not an object: {path}")
    return loaded


def refresh_library_from_scan_results(
    scan_results: list[dict[str, Any]],
    *,
    feedback_path: Path | None = None,
    output_path: Path | None = None,
    summary_path: Path | None = None,
    min_healing_failures: int = 1,
) -> dict[str, Any]:
    """Build library from scan results, enrich it, write output, and return summary."""
    library = build_library(scan_results)
    return refresh_existing_library(
        library,
        feedback_path=feedback_path,
        output_path=output_path,
        summary_path=summary_path,
        min_healing_failures=min_healing_failures,
        source="scan_results",
    )


def refresh_existing_library(
    library: dict[str, Any],
    *,
    feedback_path: Path | None = None,
    output_path: Path | None = None,
    summary_path: Path | None = None,
    min_healing_failures: int = 1,
    source: str = "existing_library",
) -> dict[str, Any]:
    deduplicated = deduplicate_library_elements(library)
    feedback = load_feedback(feedback_path)
    with_feedback = merge_feedback_into_library(deduplicated, feedback)
    healing = build_healing_suggestions(feedback.get("records") or [], min_failures=min_healing_failures)
    refreshed = merge_healing_into_library(with_feedback, healing)
    refreshed["refreshed_at"] = _now_iso()
    refreshed["refresh_source"] = source
    output = write_library(refreshed, output_path or DEFAULT_LIBRARY_PATH)
    summary = build_refresh_summary(
        refreshed,
        feedback=feedback,
        healing=healing,
        output_path=output,
        source=source,
    )
    summary_output = write_refresh_summary(summary, summary_path)
    report_paths = write_element_knowledge_reports(
        library_path=output,
        summary_path=summary_output,
        markdown_path=summary_output.parent / "refresh-report.md",
        html_path=summary_output.parent / "refresh-report.html",
    )
    summary.update(report_paths)
    write_refresh_summary(summary, summary_output)
    return summary


def refresh_library_file(
    *,
    library_path: Path | None = None,
    feedback_path: Path | None = None,
    output_path: Path | None = None,
    summary_path: Path | None = None,
    min_healing_failures: int = 1,
) -> dict[str, Any]:
    source_path = library_path or DEFAULT_LIBRARY_PATH
    if not source_path.exists():
        raise FileNotFoundError(f"element library not found: {source_path}")
    library = json.loads(source_path.read_text(encoding="utf-8"))
    return refresh_existing_library(
        library,
        feedback_path=feedback_path,
        output_path=output_path or source_path,
        summary_path=summary_path,
        min_healing_failures=min_healing_failures,
        source=str(source_path),
    )


async def refresh_element_knowledge(
    *,
    page: Any | None = None,
    base_url: str = "",
    include_states: bool = False,
    state_scan_max_states: int = 8,
    state_scan_max_per_kind: int = 2,
    scan: bool = True,
    targets: list[dict[str, str]] | None = None,
    library_path: Path | None = None,
    feedback_path: Path | None = None,
    output_path: Path | None = None,
    summary_path: Path | None = None,
    min_healing_failures: int = 1,
    preserve_unscanned_pages: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Refresh element knowledge either by scanning or enriching an existing library."""
    if progress_callback:
        progress_callback({"stage": "refresh_started", "scan": scan, "include_states": include_states})
    if scan:
        if page is None:
            raise ValueError("page is required when scan=True")
        output = output_path or library_path or DEFAULT_LIBRARY_PATH
        scan_targets_input = _targets_with_quality_gate(
            targets or default_scan_targets(base_url),
            _previous_page_counts(output),
        )
        library = await scan_targets(
            page,
            scan_targets_input,
            include_states=include_states,
            state_scan_max_states=state_scan_max_states,
            state_scan_max_per_kind=state_scan_max_per_kind,
            progress_callback=progress_callback,
        )
        if preserve_unscanned_pages:
            library = merge_scanned_pages(_load_library_for_page_merge(output), library)
        if progress_callback:
            progress_callback({"stage": "merging_feedback_and_healing", "element_count": len(library.get("elements") or [])})
        summary = refresh_existing_library(
            library,
            feedback_path=feedback_path,
            output_path=output,
            summary_path=summary_path,
            min_healing_failures=min_healing_failures,
            source="playwright_scan",
        )
        if progress_callback:
            progress_callback({"stage": "refresh_completed", **summary})
        return summary
    if progress_callback:
        progress_callback({"stage": "loading_existing_library"})
    summary = refresh_library_file(
        library_path=library_path,
        feedback_path=feedback_path,
        output_path=output_path,
        summary_path=summary_path,
        min_healing_failures=min_healing_failures,
    )
    if progress_callback:
        progress_callback({"stage": "refresh_completed", **summary})
    return summary


def build_refresh_summary(
    library: dict[str, Any],
    *,
    feedback: dict[str, Any],
    healing: dict[str, dict[str, Any]],
    output_path: Path,
    source: str,
) -> dict[str, Any]:
    elements = library.get("elements") or []
    pages = library.get("pages") or []
    elements_with_feedback = [item for item in elements if item.get("execution_count") is not None]
    elements_with_healing = [item for item in elements if item.get("healing_issue")]
    return {
        "version": "1.0",
        "refreshed_at": library.get("refreshed_at") or _now_iso(),
        "source": source,
        "output_path": str(output_path),
        "page_count": len(pages),
        "element_count": len(elements),
        "feedback_record_count": len(feedback.get("records") or []),
        "feedback_stat_count": len(feedback.get("stats") or {}),
        "healing_suggestion_count": len(healing),
        "elements_with_feedback": len(elements_with_feedback),
        "elements_with_healing": len(elements_with_healing),
    }


def write_refresh_summary(summary: dict[str, Any], path: Path | None = None) -> Path:
    output = path or DEFAULT_SUMMARY_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return output
