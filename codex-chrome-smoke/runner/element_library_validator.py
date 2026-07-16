"""Read-only live validation for the persisted element library."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from runner.agent_explore import OBSERVE_PAGE_SCRIPT
from runner.element_scanner import is_login_url
from runner.element_ref_matcher import match_element_to_interactive

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALIDATION_PATH = ROOT / "reports" / "element-library" / "validation-report.json"
ProgressCallback = Callable[[dict[str, Any]], None]

_SELECTOR_COUNTS_SCRIPT = """(selectors) => Object.fromEntries(selectors.map((selector) => {
  try { return [selector, document.querySelectorAll(selector).length]; }
  catch (_) { return [selector, null]; }
}))"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def validate_element_library(page: Any, library: dict[str, Any], *, page_readiness: dict[str, dict[str, Any]] | None = None, output_path: Path | None = None, progress_callback: ProgressCallback | None = None) -> dict[str, Any]:
    pages = {str(item.get("page_id") or ""): item for item in library.get("pages") or []}
    elements_by_page: dict[str, list[dict[str, Any]]] = {}
    for element in library.get("elements") or []:
        elements_by_page.setdefault(str(element.get("page_id") or ""), []).append(element)
    records: list[dict[str, Any]] = []
    page_total = len(elements_by_page)
    for page_index, (page_id, elements) in enumerate(elements_by_page.items(), start=1):
        page_info = pages.get(page_id) or {}
        url = str(page_info.get("url") or next((item.get("last_seen_url") for item in elements if item.get("last_seen_url")), ""))
        if progress_callback:
            progress_callback({"stage": "validating_page", "current_page": page_id, "page_index": page_index, "page_total": page_total})
        if not url:
            records.extend({"element_id": item.get("element_id"), "page_id": page_id, "status": "invalid", "reason": "missing_page_url", "matched_refs": []} for item in elements)
            continue
        readiness = (page_readiness or {}).get(page_id) or {}
        ready_selector = str(readiness.get("ready_selector") or "")
        page_ready: bool | None = None
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=8000)
            if ready_selector:
                await page.locator(ready_selector).first.wait_for(state="visible", timeout=8000)
                page_ready = True
            observation = await page.evaluate(OBSERVE_PAGE_SCRIPT)
        except Exception as exc:
            records.extend({"element_id": item.get("element_id"), "page_id": page_id, "selectors": item.get("selectors") or [], "states": item.get("states") or [], "status": "needs_review", "reason": f"page_unavailable: {exc}", "matched_refs": [], "observed_url": "", "page_ready": False} for item in elements)
            continue
        if is_login_url(str(observation.get("url") or "")) and not is_login_url(url):
            records.extend({"element_id": item.get("element_id"), "page_id": page_id, "selectors": item.get("selectors") or [], "states": item.get("states") or [], "status": "needs_review", "reason": "redirected_to_login", "matched_refs": [], "observed_url": str(observation.get("url") or ""), "page_ready": page_ready} for item in elements)
            continue
        if page_id == "login" and not is_login_url(str(observation.get("url") or "")):
            records.extend({"element_id": item.get("element_id"), "page_id": page_id, "selectors": item.get("selectors") or [], "states": item.get("states") or [], "status": "needs_review", "reason": "requires_logged_out_session", "matched_refs": [], "observed_url": str(observation.get("url") or ""), "page_ready": page_ready} for item in elements)
            continue
        selectors = sorted({str(selector) for item in elements for selector in item.get("selectors") or [] if str(selector).strip()})
        counts = await page.evaluate(_SELECTOR_COUNTS_SCRIPT, selectors)
        refs_by_selector: dict[str, list[str]] = {}
        for interactive in observation.get("interactives") or []:
            selector = str(interactive.get("selector") or "")
            if selector:
                refs_by_selector.setdefault(selector, []).append(str(interactive.get("ref") or ""))
        for item in elements:
            item_selectors = [str(selector) for selector in item.get("selectors") or [] if str(selector).strip()]
            matched_refs = [ref for selector in item_selectors for ref in refs_by_selector.get(selector, []) if ref]
            for interactive in observation.get("interactives") or []:
                ref = str(interactive.get("ref") or "")
                if ref and match_element_to_interactive(item, interactive) >= 20.0 and ref not in matched_refs:
                    matched_refs.append(ref)
            present = bool(matched_refs) or any(counts.get(selector) not in (0, None) for selector in item_selectors)
            status = "valid" if matched_refs else "needs_review" if present else "invalid"
            reason = "mapped_to_current_ref" if matched_refs else "selector_present_but_not_interactive" if present else "selector_not_found"
            records.append({"element_id": item.get("element_id"), "page_id": page_id, "selectors": item_selectors, "states": item.get("states") or [], "status": status, "reason": reason, "matched_refs": matched_refs, "observed_url": str(observation.get("url") or ""), "page_ready": page_ready})
        if progress_callback:
            progress_callback({"stage": "page_validated", "current_page": page_id, "page_index": page_index, "page_total": page_total, "element_count": len(records)})
    summary = {status: sum(item["status"] == status for item in records) for status in ("valid", "invalid", "needs_review")}
    report = {"generated_at": _now_iso(), "source": "cdp_read_only", "page_count": page_total, "element_count": len(records), "summary": summary, "records": records}
    destination = output_path or DEFAULT_VALIDATION_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**report, "output_path": str(destination)}
