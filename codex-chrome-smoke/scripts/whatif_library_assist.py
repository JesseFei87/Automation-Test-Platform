"""
Counterfactual: how often would the element library have rescued a failed step?

For each historical failed step:
  intent = (case goal text) + (failure reason)
  route  = current observation.url
  -> call format_candidate_elements(intent, route)
  -> count: did the actually-failed `ref` (or 'unknown_ref' situation)
            appear in the top-k retrieved candidates?

We treat this as a low-cost proxy for "would library injection save this step".

Run:
  python scripts/whatif_library_assist.py
  python scripts/whatif_library_assist.py --top-k 5 --limit 25
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runner.element_knowledge import format_candidate_elements, _load_library, _tokenize  # noqa: E402

TRACE_ROOT = ROOT / "reports" / "agent-explore"


def _route_from_url(url: str) -> str:
    url = (url or "").lower()
    m = re.search(r"#(/[^\s?'\"]*)", url)
    return m.group(1) if m else url


def _ref_in_topk(target_ref: str, snippet: str) -> bool:
    """Look for the snippet text mentioning the failed ref name (semantic)."""
    if not target_ref:
        return True  # nothing to check
    return False  # if no ref, library alone wouldn't help anyway


def _name_in_topk_intent(element_name: str, intent_tokens: set[str], candidate_block: str) -> bool:
    block = candidate_block.lower()
    for tok in intent_tokens:
        if tok and tok in block:
            return True
    return False


def _step_intent(step: dict, goal: str) -> str:
    """Composed intent: goal text + the failed reason + the action context."""
    dec = step.get("decision") or {}
    exec_ = step.get("execution") or {}
    bits = [goal or "",
            dec.get("reason", "") or "",
            exec_.get("error", "") or "",
            dec.get("action", "") or ""]
    return " ".join(b for b in bits if b).strip()


def _failed_ref(step: dict) -> str:
    dec = step.get("decision") or {}
    return dec.get("ref", "") or ""


def _trajectory_intent(trace: dict) -> str:
    return " / ".join(filter(None, [
        trace.get("summary", ""), trace.get("error", ""),
        (trace.get("case_id", "") if isinstance(trace.get("case_id"), str) else "")
    ])) or "explore"


def analyse_run(run_dir: Path, *, top_k: int) -> dict:
    tp = run_dir / "trace.json"
    if not tp.is_file():
        return {"run_id": run_dir.name, "skipped": True}
    try:
        t = json.loads(tp.read_text(encoding="utf-8"))
    except Exception:
        return {"run_id": run_dir.name, "skipped": True}
    status = t.get("status") or ""
    if status == "passed":
        return {"run_id": run_dir.name, "status": "passed", "skipped": True}

    goal = t.get("goal", "") or ""
    history = t.get("history") or []
    rescued_steps = 0
    considered = 0
    step_rows = []
    for i, step in enumerate(history):
        exec_ = step.get("execution") or {}
        result = exec_.get("result") or ""
        error = exec_.get("error", "") or ""
        # consider failure-shaped steps
        if not (result == "error" or "Unable to" in error or "not visible" in error
                or "unknown ref" in error or "intercepts pointer" in error):
            continue
        considered += 1

        obs = step.get("observation") or {}
        url = obs.get("url", "")
        route = _route_from_url(url)
        intent = _step_intent(step, goal)
        candidates_md = format_candidate_elements(intent, route, top_k=top_k)
        intent_tokens = _tokenize(intent) | _tokenize(route)

        # heuristic rescue: if library snippet has any token overlap with intent OR route AND
        # the candidates list isn't empty, count as "could have helped"
        ok = bool(candidates_md) and _name_in_topk_intent("", intent_tokens, candidates_md)
        # extra: check for element-name-like textual presence (semantic rescue marker)
        marker = ""
        if candidates_md:
            # first line always has "Candidate elements", if any selector or zh hint matches intent/route it's a hit
            cn_tokens = intent_tokens
            m = re.search(r"ZH: ([^\)]+)", candidates_md)
            if m:
                zh = m.group(1).lower()
                marker = "zh_hit" if any(tok in zh for tok in cn_tokens if tok) else ""
            for line in candidates_md.splitlines():
                if line.startswith("- ") and any(tok in line.lower() for tok in cn_tokens if tok):
                    marker = marker or "intent_hit"
                    break
            for sel in re.findall(r"`([^`]+)`", candidates_md):
                if "#/" in sel and route.lstrip("#/") in sel:
                    marker = marker or "route_hit"
                    break
        rescued = bool(marker)
        if rescued:
            rescued_steps += 1
        step_rows.append({
            "step": step.get("step", i + 1),
            "url": url,
            "route": route,
            "intent_excerpt": intent[:140],
            "result": result,
            "error_excerpt": error[:140],
            "library_marker": marker or "(none)",
            "library_first_line": (candidates_md.splitlines()[1]
                                   if candidates_md and "\n" in candidates_md else "(empty)"),
        })

    return {
        "run_id": run_dir.name,
        "status": status,
        "error": (t.get("error", "") or "")[:160],
        "considered_steps": considered,
        "rescued_steps": rescued_steps,
        "step_rows": step_rows,
        "skipped": False,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--top-k", type=int, default=6)
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--only-prefix", default="")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if not _load_library():
        print("library not built yet; run scripts/build_element_library_demo.py first.")
        return 2

    all_runs = sorted(
        [d for d in TRACE_ROOT.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime, reverse=True
    )
    if args.only_prefix:
        all_runs = [d for d in all_runs if d.name.startswith(args.only_prefix)]
    all_runs = all_runs[: args.limit]

    considered_total = 0
    rescued_total = 0
    rescue_counter = Counter()
    bucket_results = []
    skipped = 0
    for run in all_runs:
        rep = analyse_run(run, top_k=args.top_k)
        if rep.get("skipped"):
            skipped += 1
            continue
        if rep.get("status") == "passed":
            skipped += 1
            continue
        considered_total += rep["considered_steps"]
        rescued_total += rep["rescued_steps"]
        for row in rep["step_rows"]:
            rescue_counter[row["library_marker"]] += 1
        bucket_results.append(rep)

    print("== counterfactual: library assist (window: last "
          f"{len(all_runs)} runs) ==")
    print(f"runs_passed_or_skipped : {skipped}")
    print(f"failed_runs            : {len(bucket_results)}")
    print(f"considered_steps       : {considered_total}")
    if considered_total:
        rate = 100 * rescued_total / considered_total
        print(f"rescued_steps          : {rescued_total}  ({rate:.1f}%)  ← counterfactual pull from library")
    print("marker mix:")
    for k, v in rescue_counter.most_common():
        print(f"  {k:20s} {v}")

    if not args.json:
        print()
        print("--- per-run detail (up to 8 shown) ---")
        for rep in bucket_results[:8]:
            print(f"\n[{rep['run_id']}] {rep['status']} err={rep['error']}")
            print(f"  considered/rescued = {rep['rescued_steps']}/{rep['considered_steps']}")
            for row in rep["step_rows"][:4]:
                print(f"   step {row['step']} route={row['route'][:40]} marker={row['library_marker']}")
                print(f"     intent: {row['intent_excerpt']}")
                first = row['library_first_line']
                if first and first != "(empty)":
                    print(f"     lib   : {first[:150]}")
            print()
    else:
        out = {
            "considered_total": considered_total,
            "rescued_total": rescued_total,
            "rescue_mix": dict(rescue_counter),
            "runs": bucket_results,
        }
        Path("reports/element-library/whatif.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("\n-> reports/element-library/whatif.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
