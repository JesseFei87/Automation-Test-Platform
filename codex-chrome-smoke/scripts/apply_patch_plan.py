"""Apply patch-plan signals to TC-ICM-001..011 yaml files.

Behavior:
  1. Back up each target yaml to test-cases/icm/.bak-pre-pt-apply/
  2. For every case row in reports/patch-plan.json, append
     `missing_pt_signals` items to automation_asset.assertions
     (preserving order, de-duping against existing entries).
  3. Re-write yaml with PyYAML safe_dump, sort_keys=False,
     allow_unicode=True to keep field order and Chinese text intact.
  4. Emit reports/apply-report.md with per-case before/after diff
     of the assertions list.
  5. Keep TC-ICM-012 / tc-icm-013..026 untouched.

Rollback:
  python scripts/apply_patch_plan.py --rollback
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "reports" / "patch-plan.json"
CASE_DIR = ROOT / "test-cases" / "icm"
BAK_DIR = CASE_DIR / ".bak-pre-pt-apply"
REPORT = ROOT / "reports" / "apply-report.md"


def _strip_order(s: str) -> str:
    return NUM_RE.sub("", s or "").strip().rstrip(".").strip().lower()


NUM_RE = __import__("re").compile(r"^\s*\d+\.\s+")


def _load_plan() -> list[dict]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _write_yaml(path: Path, data: dict) -> None:
    """Write yaml with preserved top-level key order, allow_unicode=True."""
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            data, f,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=1000,
        )


def _backup_target(paths: list[Path]) -> None:
    BAK_DIR.mkdir(parents=True, exist_ok=True)
    for p in paths:
        dst = BAK_DIR / p.name
        if not dst.exists():
            shutil.copy2(p, dst)


def _restore_from_backup() -> int:
    if not BAK_DIR.exists():
        print(f"no backup dir: {BAK_DIR}")
        return 1
    restored = 0
    for bak in BAK_DIR.glob("*.yaml"):
        target = CASE_DIR / bak.name
        shutil.copy2(bak, target)
        restored += 1
    print(f"restored {restored} yaml files from {BAK_DIR.relative_to(ROOT)}")
    return 0


def _append_unique_assertions(yaml_data: dict, missing: list[str]) -> tuple[list[str], list[str]]:
    asset = yaml_data.get("automation_asset") or {}
    existing = [str(s).strip() for s in (asset.get("assertions") or []) if str(s).strip()]
    existing_keys = {_strip_order(s) for s in existing}
    added: list[str] = []
    for sig in missing:
        s = (sig or "").strip()
        # strip the leading "N. " left over from PT
        s = NUM_RE.sub("", s)
        if not s:
            continue
        if _strip_order(s) in existing_keys:
            continue
        existing.append(s)
        existing_keys.add(_strip_order(s))
        added.append(s)
    if added:
        asset["assertions"] = existing
        yaml_data["automation_asset"] = asset
    return existing, added


def _diff_assertions(before: list[str], after_added: list[str]) -> str:
    lines = []
    for s in after_added:
        lines.append(f"  +  {s}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", action="store_true",
                        help="Restore from .bak-pre-pt-apply/ instead of patching.")
    args = parser.parse_args()

    if args.rollback:
        return _restore_from_backup()

    plan = _load_plan()
    target_paths = [Path(ROOT / r["case_path"]) for r in plan]
    _backup_target(target_paths)

    report_lines = []
    report_lines.append("# Apply Report — PT signals → yaml assertions")
    report_lines.append("")
    report_lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
    report_lines.append(f"- Backup dir: `{BAK_DIR.relative_to(ROOT)}`")
    report_lines.append(f"- Plan source: `{PLAN_PATH.relative_to(ROOT)}`")
    report_lines.append("")
    report_lines.append("## Per-case changes")
    report_lines.append("")
    total_added = 0
    cases_touched = 0
    for row in plan:
        cp = Path(ROOT / row["case_path"])
        before = _read_yaml(cp)
        before_asserts = list((before.get("automation_asset") or {}).get("assertions") or [])
        after, added = _append_unique_assertions(before, list(row.get("missing_pt_signals") or []))
        if added:
            _write_yaml(cp, before)
            cases_touched += 1
            total_added += len(added)
            report_lines.append(f"### {row['case_id']} (`{cp.relative_to(ROOT)}`)  +{len(added)} assertion(s)")
            report_lines.append("")
            report_lines.append("**before:**")
            for s in before_asserts:
                report_lines.append(f"  - {s}")
            report_lines.append("")
            report_lines.append("**after (added only):**")
            for s in added:
                report_lines.append(f"  + {s}")
            report_lines.append("")
        else:
            report_lines.append(f"### {row['case_id']}  — no change (all signals already present)")
            report_lines.append("")

    report_lines.insert(5, f"- Cases touched: **{cases_touched}/{len(plan)}**")
    report_lines.insert(6, f"- Total assertions added: **{total_added}**")
    report_lines.insert(7, "")

    REPORT.write_text("\n".join(report_lines), encoding="utf-8")

    print("== apply done ==")
    print(f"  cases touched      : {cases_touched}/{len(plan)}")
    print(f"  assertions added   : {total_added}")
    print(f"  backup             : {BAK_DIR.relative_to(ROOT)}")
    print(f"  report             : {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
