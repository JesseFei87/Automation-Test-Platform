from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml


_CASE_NUMBER_RE = re.compile(r"(\d+)$")
_ROUTE_RE = re.compile(r"#/[A-Za-z0-9_./?=&%-]+")


def load_passed_formal_case_ids(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            select distinct case_id
            from run_tasks
            where status = 'passed'
              and mode = 'run-case'
              and case_id is not null
              and case_id <> ''
            """
        ).fetchall()
    return {str(row[0]).strip() for row in rows if str(row[0] or "").strip()}


def build_trusted_catalog(case_dir: Path, flow_dir: Path, passed_case_ids: set[str]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for case_path in sorted(case_dir.glob("*.yaml")):
        case = yaml.safe_load(case_path.read_text(encoding="utf-8")) or {}
        case_id = str(case.get("id") or "").strip()
        flow_path = _formal_flow_path(flow_dir, case_id)
        asset = case.get("automation_asset") if isinstance(case.get("automation_asset"), dict) else {}
        if case_id not in passed_case_ids or flow_path is None or not asset:
            continue
        catalog.append(
            {
                "case_id": case_id,
                "system": str(case.get("system") or "").strip(),
                "title": str(case.get("title") or "").strip(),
                "routes": sorted(_extract_routes(asset)),
                "operation_steps": _string_list(asset.get("operation_steps")),
                "selectors": asset.get("selectors") if isinstance(asset.get("selectors"), dict) else {},
                "assertions": _string_list(asset.get("assertions")),
                "flow_path": str(flow_path),
                "trust": "formal_passed",
            }
        )
    return catalog


def retrieve_stage_knowledge(
    catalog: Iterable[dict[str, Any]], *, system: str, target_route: str
) -> list[dict[str, Any]]:
    route = _normalize_route(target_route)
    if not route:
        return []
    return [
        item
        for item in catalog
        if str(item.get("system") or "") == system
        and route in {_normalize_route(value) for value in item.get("routes") or []}
    ]


def attach_trusted_knowledge_to_plan(
    plan: dict[str, Any], catalog: Iterable[dict[str, Any]], *, system: str
) -> dict[str, Any]:
    catalog_items = list(catalog)
    stages = [
        {
            **stage,
            "trusted_knowledge": retrieve_stage_knowledge(
                catalog_items,
                system=system,
                target_route=str(stage.get("target_route") or ""),
            ),
        }
        for stage in plan.get("stages") or []
    ]
    return {**plan, "stages": stages}


def load_trusted_plan(
    case: dict[str, Any],
    plan: dict[str, Any],
    *,
    db_path: Path,
    case_dir: Path,
    flow_dir: Path,
) -> dict[str, Any]:
    passed_case_ids = load_passed_formal_case_ids(db_path)
    catalog = build_trusted_catalog(case_dir, flow_dir, passed_case_ids)
    return attach_trusted_knowledge_to_plan(
        plan,
        catalog,
        system=str(case.get("system") or ""),
    )


def format_stage_knowledge(items: Iterable[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        lines.append(f"- Trusted source: {item.get('case_id')} ({item.get('flow_path')})")
        lines.extend(f"  operation: {step}" for step in item.get("operation_steps") or [])
        for name, candidates in (item.get("selectors") or {}).items():
            values = _string_list(candidates if isinstance(candidates, list) else [candidates])
            if values:
                lines.append(f"  selector {name}: {' | '.join(values)}")
        lines.extend(f"  assertion: {assertion}" for assertion in item.get("assertions") or [])
    return "\n".join(lines)


def write_pending_agent_asset(root: Path, run_id: str, case: dict[str, Any], trace: dict[str, Any]) -> Path:
    if not trace.get("ok") or str(trace.get("status") or "") != "passed":
        raise ValueError("only passed Agent traces can enter pending review")
    pending_dir = root / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    path = pending_dir / f"{run_id}.json"
    payload = {
        "run_id": run_id,
        "case_id": str(case.get("id") or ""),
        "review_status": "pending",
        "enabled": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "final_url": str(trace.get("final_url") or ""),
        "history": trace.get("history") or [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _formal_flow_path(flow_dir: Path, case_id: str) -> Path | None:
    match = _CASE_NUMBER_RE.search(case_id)
    if not match:
        return None
    path = flow_dir / f"icm_case_{int(match.group(1)):03d}.py"
    return path if path.is_file() else None


def _extract_routes(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_extract_routes(item) for item in value.values()), set())
    if isinstance(value, (list, tuple, set)):
        return set().union(*(_extract_routes(item) for item in value), set())
    return {_normalize_route(route) for route in _ROUTE_RE.findall(str(value or "")) if _normalize_route(route)}


def _normalize_route(value: str) -> str:
    text = str(value or "").strip()
    marker = text.find("#/")
    if marker >= 0:
        text = text[marker:]
    return text.rstrip("/")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
