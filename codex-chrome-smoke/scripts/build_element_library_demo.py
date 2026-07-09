"""
Element Library Demo — Stage B (passive accumulation)

What it does (no browser needed):
  1. Walk test-cases/icm/*.yaml, pull out `automation_asset.selectors`.
  2. For each semantic name (e.g. logout_button) gather every selector
     candidate used across cases, plus the route/context and real input
     values that fed those selectors.
  3. Build a normalized element library keyed by snake_case semantic name.
  4. Auto-attach NL synonyms by splitting the snake_case into Chinese hints
     + English hints so the agent can route NL phrases to the right
     element.
  5. Emit two products:
       - reports/element-library/library.json   (machine-readable)
       - reports/element-library/library.md     (human-readable report)

This is a *demo*: it does NOT modify runner/agent_explore.py. The next
stage would wire `format_element_knowledge_for_prompt(...)` into
`build_agent_prompt` -- an integration stub is in
`runner/element_knowledge.py` to make that future diff obvious.

Run:
  python scripts/build_element_library_demo.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "test-cases" / "icm"
OUT_DIR = ROOT / "reports" / "element-library"

# synonyms pulled from snake_case names; minimal but useful for the demo
_CN_HINTS = {
    "input": "输入框", "button": "按钮", "confirm": "确认", "cancel": "取消",
    "submit": "提交", "search": "搜索", "add": "新增", "delete": "删除",
    "edit": "编辑", "create": "创建", "user": "用户", "device": "设备",
    "server": "服务器", "password": "密码", "username": "账号", "login": "登录",
    "logout": "退出", "menu": "菜单", "avatar": "头像", "dialog": "弹窗",
    "url": "页面", "switch": "开关", "select": "下拉选择", "list": "列表",
    "control": "控制", "wall": "墙", "name": "名称", "ip": "IP",
    "port": "端口", "type": "类型", "status": "状态", "tab": "标签页",
}


def _humanize(name: str) -> tuple[str, list[str]]:
    """Split snake_case → (English phrase, Chinese hints)."""
    parts = re.split(r"[_\-]+", name.strip())
    parts = [p for p in parts if p]
    if not parts:
        return name, []
    english = " ".join(parts)
    zh = []
    for p in parts:
        hint = _CN_HINTS.get(p.lower())
        if hint and hint not in zh:
            zh.append(hint)
    if zh:
        zh.insert(0, parts[0])
    return english, zh


def _infer_context_keys(name: str) -> list[str]:
    """Heuristic context anchors extracted from the name only."""
    ctx = []
    if "dialog" in name or "modal" in name or "popup" in name:
        ctx.append("dialog")
    if "url" in name:
        ctx.append("route")
    if "list" in name:
        ctx.append("list_page")
    return ctx


def _load_cases() -> list[dict[str, Any]]:
    cases = []
    for path in sorted(CASE_DIR.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  skip {path.name}: {exc}", file=sys.stderr)
            continue
        if isinstance(raw, dict):
            raw["_path"] = str(path.relative_to(ROOT))
            cases.append(raw)
    return cases


def build_library(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_element: dict[str, dict[str, Any]] = {}
    by_route: dict[str, set[str]] = defaultdict(set)
    by_case: dict[str, dict[str, Any]] = {}

    for case in cases:
        case_id = str(case.get("id") or case["_path"])
        asset = case.get("automation_asset") or {}
        if not isinstance(asset, dict):
            continue
        selectors = asset.get("selectors") or {}
        input_values = asset.get("input_values") or {}
        assertions = asset.get("assertions") or []
        if not isinstance(selectors, dict) or not selectors:
            by_case[case_id] = {"case_id": case_id, "title": case.get("title", ""),
                                "category": case.get("category", ""),
                                "selectors_count": 0}
            continue

        per_case = {"case_id": case_id, "title": case.get("title", ""),
                    "category": case.get("category", ""),
                    "selectors": {}}
        for sem_name, candidates in selectors.items():
            cands = candidates if isinstance(candidates, list) else [candidates]
            cands = [str(c).strip() for c in cands if str(c).strip()]
            english, zh = _humanize(sem_name)
            ctx = _infer_context_keys(sem_name)

            entry = by_element.setdefault(sem_name, {
                "name": sem_name,
                "human_en": english,
                "human_zh": zh,
                "selectors": [],
                "selectors_by_case": {},
                "context_keys": ctx,
                "used_in_cases": [],
                "input_values_used": [],
                "assertions_supported": [],
            })
            entry["selectors_by_case"][case_id] = cands
            for s in cands:
                if s not in entry["selectors"]:
                    entry["selectors"].append(s)
            if case_id not in entry["used_in_cases"]:
                entry["used_in_cases"].append(case_id)
            for vname, vval in (input_values or {}).items():
                key = f"{sem_name}.{vname}"
                if key in entry["input_values_used"]:
                    continue
                entry["input_values_used"].append(key)
                # attach route hints if element name has "url"
            if "url" in sem_name:
                for s in cands:
                    if s.startswith("#/"):
                        by_route[s].add(sem_name)
            for a in assertions:
                if sem_name in a.lower() or _any_token(a, [english, *zh]):
                    if a not in entry["assertions_supported"]:
                        entry["assertions_supported"].append(a)

            per_case["selectors"][sem_name] = cands
        per_case["selectors_count"] = len(selectors)
        by_case[case_id] = per_case

    # routes consolidated
    routes = {k: sorted(v) for k, v in by_route.items()}
    # final library payload
    elements = []
    for name, data in by_element.items():
        elements.append({
            "name": name,
            "human_en": data["human_en"],
            "human_zh": data["human_zh"],
            "context_keys": data["context_keys"],
            "selectors": data["selectors"],
            "selectors_by_case": data["selectors_by_case"],
            "used_in_cases": data["used_in_cases"],
            "coverage": len(data["used_in_cases"]),
            "input_values_used": data["input_values_used"],
            "assertions_supported": data["assertions_supported"],
        })
    elements.sort(key=lambda x: (-x["coverage"], x["name"]))
    return {
        "summary": {
            "total_cases_scanned": len(cases),
            "cases_with_automation_asset": sum(
                1 for c in by_case.values() if c.get("selectors_count", 0) > 0
            ),
            "unique_elements": len(elements),
            "routes_extracted": len(routes),
        },
        "elements": elements,
        "by_route": routes,
        "by_case": by_case,
    }


def _any_token(text: str, tokens: list[str]) -> bool:
    t = text.lower()
    return any(tok and tok.lower() in t for tok in tokens if tok)


def write_json(lib: dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / "library.json"
    p.write_text(json.dumps(lib, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def write_markdown(lib: dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / "library.md"
    s = lib["summary"]
    lines: list[str] = []
    lines.append("# ICM 元素库 Demo · Stage B (passive accumulation)\n")
    lines.append("## 总览\n")
    lines.append(f"- 扫描 case: **{s['total_cases_scanned']}**")
    lines.append(f"- 含 automation_asset 的 case: **{s['cases_with_automation_asset']}**")
    lines.append(f"- 归一化后元素数: **{s['unique_elements']}**")
    lines.append(f"- 提取到的 route 数: **{s['routes_extracted']}**\n")
    lines.append("## 复用度 TOP 元素（被 ≥ 2 个 case 共享）\n")
    top = [e for e in lib["elements"] if e["coverage"] >= 2]
    if top:
        lines.append("| 语义名 | EN | ZH 提示 | 复用次数 | 选择器数 | 出现于 |")
        lines.append("|---|---|---|---|---|---|")
        for e in top:
            used = ", ".join(e["used_in_cases"][:5])
            if len(e["used_in_cases"]) > 5:
                used += f" …(+{len(e['used_in_cases'])-5})"
            lines.append(f"| `{e['name']}` | {e['human_en']} | {' / '.join(e['human_zh']) or '-'} "
                         f"| {e['coverage']} | {len(e['selectors'])} | {used} |")
    else:
        lines.append("（暂无）")
    lines.append("\n## 全量元素\n")
    for e in lib["elements"]:
        ctx = " · ".join(e["context_keys"]) or "-"
        lines.append(f"### `{e['name']}`  *(reuse: {e['coverage']})*")
        lines.append(f"- **EN**: {e['human_en']}")
        if e["human_zh"]:
            lines.append(f"- **ZH 提示**: {' / '.join(e['human_zh'])}")
        lines.append(f"- **Context**: {ctx}")
        lines.append(f"- **Selectors ({len(e['selectors'])}):**")
        for s in e["selectors"][:8]:
            lines.append(f"  - `{s}`")
        if len(e["selectors"]) > 8:
            lines.append(f"  - …(+{len(e['selectors'])-8})")
        lines.append(f"- **Used in**: {', '.join(e['used_in_cases'])}")
        if e["input_values_used"]:
            lines.append(f"- **Input values paired**: {', '.join(e['input_values_used'][:5])}")
        lines.append("")
    lines.append("## by_case 索引\n")
    lines.append("| case_id | title | category | selectors |")
    lines.append("|---|---|---|---|")
    for cid, info in sorted(lib["by_case"].items()):
        lines.append(f"| {cid} | {info.get('title','')} | {info.get('category','')} | "
                     f"{info.get('selectors_count', 0)} |")
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def main() -> int:
    cases = _load_cases()
    lib = build_library(cases)
    pj = write_json(lib)
    pm = write_markdown(lib)
    print("== element library demo ==")
    s = lib["summary"]
    print(f"cases scanned       : {s['total_cases_scanned']}")
    print(f"with automation_asset: {s['cases_with_automation_asset']}")
    print(f"unique elements     : {s['unique_elements']}")
    print(f"routes extracted    : {s['routes_extracted']}")
    print()
    print("top reused elements:")
    for e in [x for x in lib["elements"] if x["coverage"] >= 2][:10]:
        print(f"  {e['name']:35s}  reuse={e['coverage']:<2}  zh={'/'.join(e['human_zh']) or '-'}")
    print()
    print(f"json  -> {pj.relative_to(ROOT)}")
    print(f"md    -> {pm.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
