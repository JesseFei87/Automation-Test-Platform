from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def write_report(
    run_id: str,
    case: dict[str, Any],
    status: str,
    screenshots: list[str],
    failure_point: str = "",
    error: str = "",
    observed_asset_path: str = "",
) -> Path:
    out_dir = ROOT / "reports" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run_id}.md"
    asset = case.get("automation_asset", {})
    body = [
        f"# {run_id}",
        "",
        f"- case name: {case['id']} {case['title']}",
        f"- environment: icm-internal",
        f"- status: {status}",
        f"- error: {error or 'none'}",
        f"- failure point: {failure_point or 'none'}",
        f"- observed asset path: {observed_asset_path or 'none'}",
        f"- preconditions: {', '.join(case.get('preconditions', []))}",
        f"- key steps: {', '.join(case.get('steps', []))}",
        f"- operation steps: {', '.join(asset.get('operation_steps', []))}",
        f"- selectors: {', '.join(asset.get('selectors', {}).keys())}",
        f"- inputs: {', '.join(f'{k}={v}' for k, v in asset.get('input_values', {}).items())}",
        f"- assertions: {', '.join(asset.get('assertions', []))}",
        "- screenshot paths:",
    ]
    body.extend(f"  - {shot}" for shot in screenshots)
    path.write_text("\n".join(body), encoding="utf-8")
    return path
