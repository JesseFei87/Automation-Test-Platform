"""Report rendering for element knowledge refresh results.

P9 scope: provide report-layer visibility for the element knowledge base without
requiring a frontend UI.  The renderer produces Markdown and HTML from the
refreshed library plus refresh-summary metadata.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_PATH = ROOT / "reports" / "element-library" / "library.json"
DEFAULT_SUMMARY_PATH = ROOT / "reports" / "element-library" / "refresh-summary.json"
DEFAULT_MARKDOWN_REPORT_PATH = ROOT / "reports" / "element-library" / "refresh-report.md"
DEFAULT_HTML_REPORT_PATH = ROOT / "reports" / "element-library" / "refresh-report.html"


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def failure_hotspots(library: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
    elements = [dict(item) for item in library.get("elements") or []]
    candidates = [
        item
        for item in elements
        if item.get("failed_count") is not None or item.get("healing_issue") or item.get("last_error")
    ]
    candidates.sort(
        key=lambda item: (
            int(item.get("failed_count") or 0),
            1 if item.get("healing_issue") else 0,
            float(item.get("execution_count") or 0),
        ),
        reverse=True,
    )
    return candidates[:limit]


def build_report_model(library: dict[str, Any], summary: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = summary or {}
    elements = library.get("elements") or []
    pages = library.get("pages") or []
    hotspots = failure_hotspots(library)
    unscannable_regions = [
        {"page_id": page.get("page_id") or "", "page_name": page.get("name") or "", **region}
        for page in pages
        for region in page.get("unscannable_regions") or []
        if isinstance(region, dict)
    ]
    return {
        "title": "Element Knowledge Refresh Report",
        "refreshed_at": summary.get("refreshed_at") or library.get("refreshed_at") or "",
        "source": summary.get("source") or library.get("refresh_source") or "",
        "output_path": summary.get("output_path") or "",
        "page_count": summary.get("page_count", len(pages)),
        "element_count": summary.get("element_count", len(elements)),
        "feedback_record_count": summary.get("feedback_record_count", 0),
        "feedback_stat_count": summary.get("feedback_stat_count", 0),
        "healing_suggestion_count": summary.get("healing_suggestion_count", len([item for item in elements if item.get("healing_issue")])),
        "elements_with_feedback": summary.get("elements_with_feedback", len([item for item in elements if item.get("execution_count") is not None])),
        "elements_with_healing": summary.get("elements_with_healing", len([item for item in elements if item.get("healing_issue")])),
        "hotspots": hotspots,
        "unscannable_regions": unscannable_regions,
    }


def render_markdown_report(model: dict[str, Any]) -> str:
    lines = [
        f"# {model['title']}",
        "",
        "## Summary",
        "",
        f"- refreshed_at: {model.get('refreshed_at') or 'unknown'}",
        f"- source: {model.get('source') or 'unknown'}",
        f"- output_path: {model.get('output_path') or 'unknown'}",
        f"- page_count: {model.get('page_count', 0)}",
        f"- element_count: {model.get('element_count', 0)}",
        f"- feedback_record_count: {model.get('feedback_record_count', 0)}",
        f"- feedback_stat_count: {model.get('feedback_stat_count', 0)}",
        f"- healing_suggestion_count: {model.get('healing_suggestion_count', 0)}",
        f"- elements_with_feedback: {model.get('elements_with_feedback', 0)}",
        f"- elements_with_healing: {model.get('elements_with_healing', 0)}",
        "",
        "## Failure Hotspots",
        "",
    ]
    hotspots = model.get("hotspots") or []
    if not hotspots:
        lines.append("No failure hotspots found.")
    else:
        lines.extend(
            [
                "| element_id | failed | success_rate | issue | suggestion | last_error |",
                "|---|---:|---:|---|---|---|",
            ]
        )
        for item in hotspots:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(item.get("element_id") or item.get("name") or ""),
                        str(item.get("failed_count") or 0),
                        str(item.get("success_rate") if item.get("success_rate") is not None else ""),
                        str(item.get("healing_issue") or ""),
                        str(item.get("healing_suggestion") or ""),
                        str(item.get("last_error") or ""),
                    ]
                ).replace("\n", " ")
                + " |"
            )
    lines.append("")
    lines.extend(["## Areas Not DOM Scanned", ""])
    regions = model.get("unscannable_regions") or []
    if not regions:
        lines.append("No iframe or canvas regions detected.")
    else:
        lines.extend(["| page | kind | reason | selector | label |", "|---|---|---|---|---|"])
        for region in regions:
            lines.append(
                "| "
                + " | ".join(
                    str(region.get(key) or "").replace("\n", " ")
                    for key in ("page_id", "kind", "reason", "selector", "label")
                )
                + " |"
            )
    lines.append("")
    return "\n".join(lines)


def _html_table_row(cells: list[Any], *, header: bool = False) -> str:
    tag = "th" if header else "td"
    return "<tr>" + "".join(f"<{tag}>{html.escape(str(cell))}</{tag}>" for cell in cells) + "</tr>"


def render_html_report(model: dict[str, Any]) -> str:
    summary_rows = [
        ("refreshed_at", model.get("refreshed_at") or "unknown"),
        ("source", model.get("source") or "unknown"),
        ("output_path", model.get("output_path") or "unknown"),
        ("page_count", model.get("page_count", 0)),
        ("element_count", model.get("element_count", 0)),
        ("feedback_record_count", model.get("feedback_record_count", 0)),
        ("feedback_stat_count", model.get("feedback_stat_count", 0)),
        ("healing_suggestion_count", model.get("healing_suggestion_count", 0)),
        ("elements_with_feedback", model.get("elements_with_feedback", 0)),
        ("elements_with_healing", model.get("elements_with_healing", 0)),
    ]
    summary_html = "\n".join(_html_table_row([key, value]) for key, value in summary_rows)
    hotspot_rows = [_html_table_row(["element_id", "failed", "success_rate", "issue", "suggestion", "last_error"], header=True)]
    for item in model.get("hotspots") or []:
        hotspot_rows.append(
            _html_table_row(
                [
                    item.get("element_id") or item.get("name") or "",
                    item.get("failed_count") or 0,
                    item.get("success_rate") if item.get("success_rate") is not None else "",
                    item.get("healing_issue") or "",
                    item.get("healing_suggestion") or "",
                    item.get("last_error") or "",
                ]
            )
        )
    if len(hotspot_rows) == 1:
        hotspot_rows.append(_html_table_row(["No failure hotspots found.", "", "", "", "", ""]))
    region_rows = [_html_table_row(["page", "kind", "reason", "selector", "label"], header=True)]
    for region in model.get("unscannable_regions") or []:
        region_rows.append(
            _html_table_row([region.get("page_id") or "", region.get("kind") or "", region.get("reason") or "", region.get("selector") or "", region.get("label") or ""])
        )
    if len(region_rows) == 1:
        region_rows.append(_html_table_row(["No iframe or canvas regions detected.", "", "", "", ""]))
    return f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <title>{html.escape(str(model['title']))}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }}
    h1, h2 {{ color: #111827; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 16px 0; }}
    .card {{ border: 1px solid #d1d5db; border-radius: 8px; padding: 12px; background: #fafafa; }}
    .metric {{ font-size: 24px; font-weight: 700; }}
    .label {{ color: #6b7280; font-size: 13px; }}
  </style>
</head>
<body>
  <h1>{html.escape(str(model['title']))}</h1>
  <div class=\"cards\">
    <div class=\"card\"><div class=\"metric\">{model.get('element_count', 0)}</div><div class=\"label\">Elements</div></div>
    <div class=\"card\"><div class=\"metric\">{model.get('feedback_record_count', 0)}</div><div class=\"label\">Feedback Records</div></div>
    <div class=\"card\"><div class=\"metric\">{model.get('healing_suggestion_count', 0)}</div><div class=\"label\">Healing Suggestions</div></div>
  </div>
  <h2>Summary</h2>
  <table>{summary_html}</table>
  <h2>Failure Hotspots</h2>
  <table>{''.join(hotspot_rows)}</table>
  <h2>Areas Not DOM Scanned</h2>
  <table>{''.join(region_rows)}</table>
</body>
</html>
"""


def write_element_knowledge_reports(
    *,
    library_path: Path | None = None,
    summary_path: Path | None = None,
    markdown_path: Path | None = None,
    html_path: Path | None = None,
) -> dict[str, str]:
    library = load_json_file(library_path or DEFAULT_LIBRARY_PATH)
    summary = load_json_file(summary_path or DEFAULT_SUMMARY_PATH)
    model = build_report_model(library, summary)
    md_output = markdown_path or DEFAULT_MARKDOWN_REPORT_PATH
    html_output = html_path or DEFAULT_HTML_REPORT_PATH
    md_output.parent.mkdir(parents=True, exist_ok=True)
    html_output.parent.mkdir(parents=True, exist_ok=True)
    md_output.write_text(render_markdown_report(model), encoding="utf-8")
    html_output.write_text(render_html_report(model), encoding="utf-8")
    return {"markdown_report_path": str(md_output), "html_report_path": str(html_output)}
