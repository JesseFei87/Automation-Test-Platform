"""PT ↔ yaml diff plan.

For TC-ICM-001..011, parse the matching prompt-template markdown and the
case yaml, then list:
  - yaml operation_steps that are NOT covered by PT Required Steps
  - PT Required Steps that are NOT in yaml operation_steps
  - PT "expected signal" phrases (lines containing 'Decide', 'Wait', 'Confirm',
    'If', 'whether', 'visible', 'opens', 'returns') NOT present in yaml
    assertions
  - status of evidence_points count vs the "Keep N screenshots" claim

Output:
  reports/patch-plan.md   (human diff overview)
  reports/patch-plan.json (machine-readable suggestions)

This script is read-only — no yaml files are modified.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PT_DIR = ROOT / "prompt-templates"
CASE_DIR = ROOT / "test-cases" / "icm"
OUT = ROOT / "reports"

ID_NUM_RE = re.compile(r"PT-ICM-(\d+)")
SIGNAL_RE = re.compile(
    r"\b(Decide|Wait(?:ing)?|Confirm|whether|visible|opens|returns|rendered|finished|refresh|loaded|appears?|contain|shows?|signal)\b",
    flags=re.IGNORECASE,
)
KEEP_N_RE = re.compile(r"Keep\s+(\d+)\s+screenshots?", flags=re.IGNORECASE)
NUM_PREFIX_RE = re.compile(r"^\s*(\d+)\.\s+(.+)$")


def _case_path_for(num: str) -> Path:
    matches = sorted(CASE_DIR.glob(f"TC-ICM-{num}-*.yaml"))
    if not matches:
        matches = sorted(CASE_DIR.glob(f"tc-icm-{num}-generated.yaml"))
    return matches[0] if matches else None


def _pt_path_for(num: str) -> Path | None:
    matches = sorted(PT_DIR.glob(f"PT-ICM-{num}-*.md"))
    return matches[0] if matches else None


def _load_md(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_md_sections(md: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = None
    for line in md.splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            current = m.group(1).strip()
            out.setdefault(current, [])
            continue
        if current is None:
            continue
        if line.strip().startswith(("- ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            out[current].append(line.strip())
    return out


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _signal_lines(steps: list[str]) -> list[str]:
    out: list[str] = []
    for line in steps or []:
        if SIGNAL_RE.search(line):
            out.append(line.strip())
    return out


def _norm_step(text: str) -> str:
    return NUM_PREFIX_RE.sub(r"\2", text.strip()).strip(" .")


def _ensure_evidence_screenshots(yaml_data: dict) -> dict:
    asset = yaml_data.setdefault("automation_asset", {})
    ep = asset.get("evidence_points") or []
    keep_n_match = None
    md = asset.get("_md_text", "")
    m = KEEP_N_RE.search(md)
    if m:
        keep_n_match = int(m.group(1))
    if not keep_n_match:
        return {}
    picture_lines = [e for e in ep if "png" in str(e).lower() or "screenshot" in str(e).lower()]
    return {
        "pt_keep_n": keep_n_match,
        "yaml_picture_lines": len(picture_lines),
        "yaml_evidence_points_total": len(ep),
    }


def analyse_pair(num: str) -> dict:
    pt_path = _pt_path_for(num)
    case_path = _case_path_for(num)
    if not pt_path or not case_path or not case_path.exists():
        return {"num": num, "skipped": "missing file"}
    case = _load_yaml(case_path)
    md = _load_md(pt_path)
    sections = _extract_md_sections(md)
    pt_steps = sections.get("Required Steps", []) or sections.get("Required steps", [])
    pt_inputs = sections.get("Required Inputs", []) or sections.get("Inputs", [])
    pt_norm = [_norm_step(s) for s in pt_steps]

    asset = case.get("automation_asset") or {}
    asset["_md_text"] = md
    yaml_ops = [_norm_step(s) for s in (asset.get("operation_steps") or [])]
    yaml_assertions = [s.strip() for s in (asset.get("assertions") or [])]

    pt_only_ops = [s for s in pt_norm if s and not any(_is_contained(s, y) for y in yaml_ops)]
    yaml_only_ops = [s for s in yaml_ops if s and not any(_is_contained(_norm_step(s), p) for p in pt_norm)]
    mutual_ops = [s for s in pt_norm if s and any(_is_contained(s, y) for y in yaml_ops)]

    pt_signals = _signal_lines(pt_steps)
    missing_signals = [s for s in pt_signals
                       if not any(_is_contained(s, a) or _is_contained(a, s) for a in yaml_assertions)]

    screenshot = _ensure_evidence_screenshots(case)
    return {
        "num": num,
        "case_id": case.get("id"),
        "case_path": str(case_path.relative_to(ROOT)),
        "pt_path": str(pt_path.relative_to(ROOT)),
        "pt_input_count": len(pt_inputs),
        "pt_ops_total": len(pt_norm),
        "yaml_ops_total": len(yaml_ops),
        "yaml_ops_matched_with_pt": len(mutual_ops),
        "yaml_ops_only": yaml_only_ops,
        "pt_ops_only": pt_only_ops,
        "pt_signals_total": len(pt_signals),
        "missing_pt_signals": missing_signals,
        "screenshot": screenshot,
    }


def _is_contained(a: str, b: str) -> bool:
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    return a in b or b in a


def main() -> int:
    nums = sorted({m.group(1) for m in
                   [ID_NUM_RE.search(p.name) for p in PT_DIR.glob("PT-ICM-*.md")]
                   if m})
    out_md: list[str] = []
    out_md.append("# Patch Plan: prompt-templates ↔ yaml (TC-ICM-001..011)")
    out_md.append("")
    out_md.append("> Read-only diff. After you approve each case's patch entries below,")
    out_md.append("> run `python scripts/apply_patch_plan.py` to write them into the yaml files.")
    out_md.append("")
    out_md.append("## 数字总览")
    out_md.append("")
    out_md.append("| case | pt 操作 | yaml 操作 | 互有 | 缺 PT 步 | 缺信号 |")
    out_md.append("|---|---|---|---|---|---|")
    rows = []
    json_dump = []
    for n in nums:
        r = analyse_pair(n)
        if r.get("skipped"):
            continue
        rows.append(r)
        json_dump.append(r)
        out_md.append(
            f"| {r['case_id']} | {r['pt_ops_total']} | {r['yaml_ops_total']} | "
            f"{r['yaml_ops_matched_with_pt']} | {len(r['pt_ops_only'])} | "
            f"{len(r['missing_pt_signals'])} |"
        )
    out_md.append("")

    for r in rows:
        out_md.append(f"## {r['case_id']}")
        out_md.append("")
        out_md.append(f"- yaml: `{r['case_path']}`")
        out_md.append(f"- pt  : `{r['pt_path']}`")
        out_md.append(f"- 操作匹配度: {r['yaml_ops_matched_with_pt']}/{r['pt_ops_total']}")
        if r["screenshot"]:
            keep = r["screenshot"].get("pt_keep_n")
            yaml_pic = r["screenshot"].get("yaml_picture_lines", 0)
            if keep:
                out_md.append(f"- 截图要求: PT 说 Keep **{keep}** 张；yaml 现有图注 **{yaml_pic}** 条")
        out_md.append("")
        if r["pt_ops_only"]:
            out_md.append("**PT 里有但 yaml 没写的操作步骤（建议 append 到 operation_steps）：**")
            for s in r["pt_ops_only"]:
                out_md.append(f"- {s}")
            out_md.append("")
        if r["yaml_ops_only"]:
            out_md.append("**yaml 里有但 PT 没写的操作步骤（保留即可，yaml 更细）：**")
            for s in r["yaml_ops_only"]:
                out_md.append(f"- {s}")
            out_md.append("")
        if r["missing_pt_signals"]:
            out_md.append("**PT 里的 expected signal 但 yaml 没列在 assertions（建议 append 到 assertions）：**")
            for s in r["missing_pt_signals"]:
                out_md.append(f"- {s}")
            out_md.append("")
        out_md.append("")
    out_md.append("## 汇总：建议每条 case 的 patches 数")
    counters = Counter()
    for r in rows:
        counters["pt_ops_only"] += len(r["pt_ops_only"])
        counters["yaml_ops_extra_kept"] += len(r["yaml_ops_only"])
        counters["missing_signals"] += len(r["missing_pt_signals"])
    out_md.append("")
    out_md.append("| 类型 | 数量 |")
    out_md.append("|---|---|")
    for k, v in counters.most_common():
        out_md.append(f"| {k} | {v} |")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "patch-plan.md").write_text("\n".join(out_md), encoding="utf-8")
    (OUT / "patch-plan.json").write_text(json.dumps(json_dump, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print("== patch plan generated ==")
    print(f"  rows              : {len(rows)}")
    print(f"  pt_ops_only total : {counters['pt_ops_only']}")
    print(f"  missing_signals   : {counters['missing_signals']}")
    print(f"  -> {OUT.relative_to(ROOT)}/patch-plan.md")
    print(f"  -> {OUT.relative_to(ROOT)}/patch-plan.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
