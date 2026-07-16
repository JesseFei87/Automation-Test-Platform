"""Element knowledge provider — Stage B integration surface (read-only).

This module demonstrates *where* and *how* the element library would be
consumed by the agent loop, without touching any existing runner code.
The next stage would call `format_candidate_elements(...)` from
`runner/agent_explore.build_agent_prompt` and append the returned text to
each step's prompt.

When the library is absent (early adoption / fresh project), the provider
returns an empty string -- safe-by-default.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_LIBRARY = _ROOT / "reports" / "element-library" / "library.json"
_VALIDATION_REPORT = _ROOT / "reports" / "element-library" / "validation-report.json"
_LIBRARY_ENV = "ICM_ELEMENT_LIBRARY_PATH"
_LEGACY_LIBRARY_ENV = "ELEMENT_LIBRARY_PATH"
_VALIDATION_REPORT_ENV = "ICM_ELEMENT_VALIDATION_REPORT_PATH"

# synonyms pulled from snake_case + small Chinese hint dictionary
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

_BUSINESS_SYNONYMS = {
    "用户": ["账号", "账户", "人员", "user"],
    "账号": ["用户", "账户", "登录账号", "user", "username"],
    "新增": ["创建", "添加", "新建", "add", "create"],
    "创建": ["新增", "添加", "新建", "add", "create"],
    "添加": ["新增", "创建", "新建", "add", "create"],
    "输入": ["填写", "录入", "填入", "fill", "input"],
    "填写": ["输入", "录入", "填入", "fill", "input"],
    "登录": ["登陆", "login"],
    "查询": ["搜索", "筛选", "search", "filter"],
    "搜索": ["查询", "筛选", "search", "filter"],
    "保存": ["提交", "确认", "完成", "save", "submit", "confirm"],
    "提交": ["保存", "确认", "完成", "save", "submit", "confirm"],
    "编辑": ["修改", "更新", "edit", "update"],
    "修改": ["编辑", "更新", "edit", "update"],
    "删除": ["移除", "delete", "remove"],
    "设备": ["终端", "机器", "device"],
    "服务器": ["服务端", "主机", "server", "host"],
    "需求": ["需求条目", "requirement"],
    "测试用例": ["用例", "case", "testcase", "test case"],
    "执行": ["运行", "测试运行", "execution", "run"],
    "报告": ["测试报告", "执行报告", "report"],
    "项目": ["工程", "project"],
}

_NOISY_ELEMENT_RE = re.compile(r"^(agent_candidate|fill_\d+|click_\d+)$")


def _library_path() -> Path:
    configured = os.environ.get(_LEGACY_LIBRARY_ENV) or os.environ.get(_LIBRARY_ENV)
    return Path(configured).expanduser() if configured else _LIBRARY


def _validation_report_path() -> Path | None:
    configured = os.environ.get(_VALIDATION_REPORT_ENV)
    if configured:
        return Path(configured).expanduser()
    library_overridden = bool(os.environ.get(_LEGACY_LIBRARY_ENV) or os.environ.get(_LIBRARY_ENV))
    return None if library_overridden else _VALIDATION_REPORT


@lru_cache(maxsize=8)
def _load_library_from_path(path_text: str) -> dict[str, Any] | None:
    path = Path(path_text)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_library() -> dict[str, Any] | None:
    return _load_library_from_path(str(_library_path()))


@lru_cache(maxsize=8)
def _load_validation_from_path(path_text: str) -> dict[str, Any] | None:
    path = Path(path_text)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_validation() -> dict[str, Any] | None:
    path = _validation_report_path()
    return _load_validation_from_path(str(path)) if path else None


def clear_library_cache() -> None:
    _load_library_from_path.cache_clear()
    _load_validation_from_path.cache_clear()


def _tokenize(text: str) -> set[str]:
    text = (text or "").lower()
    return {tok for tok in re.split(r"[\s,;:_/.\-()\[\]【】、，；。]+", text) if tok}


def _expanded_tokens(text: str) -> set[str]:
    lowered = (text or "").lower()
    tokens = _tokenize(lowered)
    for source, synonyms in _BUSINESS_SYNONYMS.items():
        source_lower = source.lower()
        synonym_lowers = [item.lower() for item in synonyms]
        if source_lower in lowered or any(item in lowered for item in synonym_lowers):
            tokens.add(source_lower)
            tokens.update(synonym_lowers)
    for english, chinese in _CN_HINTS.items():
        if english in lowered or chinese.lower() in lowered:
            tokens.add(english)
            tokens.add(chinese.lower())
    return tokens


def _element_haystack(element: dict[str, Any]) -> str:
    state_labels = [
        str(label)
        for coverage in (element.get("state_coverage") or {}).values()
        if isinstance(coverage, dict)
        for label in coverage.get("labels") or []
    ]
    return " ".join(
        [
            str(element.get("element_id", "")),
            str(element.get("name", "")),
            str(element.get("human_en", "")),
            " ".join(str(item) for item in element.get("human_zh") or []),
            str(element.get("business_desc", "")),
            " ".join(str(item) for item in element.get("context_keys") or []),
            " ".join(str(item) for item in element.get("selectors") or []),
            " ".join(str(item.get("value") or "") for item in element.get("locator_variants") or [] if isinstance(item, dict)),
            " ".join(state_labels),
            str(element.get("page_id", "")),
            str(element.get("state", "")),
        ]
    ).lower()


def _validation_key(record: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    return (
        str(record.get("page_id") or ""),
        str(record.get("element_id") or ""),
        tuple(str(item) for item in record.get("selectors") or []),
    )


def _validation_status_index() -> dict[tuple[str, str, tuple[str, ...]], str]:
    report = _load_validation()
    if not report:
        return {}
    return {
        _validation_key(record): str(record.get("status") or "")
        for record in report.get("records") or []
    }


def _status_for_element(element: dict[str, Any], status_index: dict[tuple[str, str, tuple[str, ...]], str]) -> str:
    if not status_index:
        return ""
    key = (
        str(element.get("page_id") or ""),
        str(element.get("element_id") or ""),
        tuple(str(item) for item in element.get("selectors") or []),
    )
    return status_index.get(key, "")


def rank_for_intent(intent: str, route: str = "", *, top_k: int = 6, include_needs_review: bool = False) -> list[dict[str, Any]]:
    """Return top_k elements whose NL synonyms match `intent` (and route)."""
    lib = _load_library()
    if not lib:
        return []
    status_index = _validation_status_index()
    intent_tokens = _expanded_tokens(intent)
    route_norm = (route or "").strip().lower()
    scored: list[tuple[float, dict[str, Any]]] = []
    for e in lib.get("elements") or []:
        validation_status = _status_for_element(e, status_index)
        if validation_status == "invalid":
            continue
        if validation_status == "needs_review" and not include_needs_review:
            continue
        if status_index and not validation_status:
            continue
        score = 0.0
        text_haystack = _element_haystack(e)
        text_tokens = _expanded_tokens(text_haystack)
        overlap = intent_tokens & text_tokens
        semantic_score = 4.0 * len(overlap)
        if intent.lower() and intent.lower() in text_haystack:
            semantic_score += 8.0
        score += semantic_score
        selector_text = " ".join(str(item) for item in e.get("selectors") or []).lower()
        context_text = " ".join(str(item) for item in e.get("context_keys") or []).lower()
        route_score = 0.0
        if route_norm and (route_norm in selector_text or route_norm in context_text or route_norm in text_haystack):
            route_score += 6.0
        for ck in e.get("context_keys") or []:
            ck_text = str(ck).lower()
            if ck_text in intent.lower() or ck_text in route_norm:
                score += 2.0
        score += route_score
        if semantic_score > 0 or route_score > 0:
            score += min(float(e.get("coverage", 0)), 10.0) * 0.15
        if _NOISY_ELEMENT_RE.match(str(e.get("name", ""))):
            score -= 12.0
        if validation_status == "valid":
            score += 8.0
        elif validation_status == "needs_review":
            score -= 8.0
        if score > 0:
            candidate = dict(e)
            if validation_status:
                candidate["validation_status"] = validation_status
            scored.append((score, candidate))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:top_k]]


def format_candidate_elements(intent: str, route: str = "", *, top_k: int = 6, include_needs_review: bool = False) -> str:
    """Markdown snippet intended for injection into agent_explore.build_agent_prompt.

    Returns '' when nothing matches (safe to always concatenate).
    """
    rows = rank_for_intent(intent, route, top_k=top_k, include_needs_review=include_needs_review)
    if not rows:
        return ""
    lines = ["Candidate elements (from shared library, ranked by intent match):"]
    for e in rows:
        zh = " / ".join(e.get("human_zh") or []) or "-"
        ctx = " · ".join(e.get("context_keys") or []) or "-"
        sels = e.get("selectors") or []
        sel_preview = ", ".join(f"`{s}`" for s in sels[:5])
        if len(sels) > 5:
            sel_preview += f" …(+{len(sels)-5})"
        feedback_bits = []
        if e.get("execution_count") is not None:
            feedback_bits.append(f"runs: {e.get('execution_count')}")
        if e.get("success_rate") is not None:
            feedback_bits.append(f"success: {e.get('success_rate')}")
        if e.get("last_error"):
            feedback_bits.append(f"last_error: {e.get('last_error')}")
        if e.get("validation_status"):
            feedback_bits.append(f"validation: {e.get('validation_status')}")
        feedback = f"; feedback: {', '.join(feedback_bits)}" if feedback_bits else ""
        lines.append(f"- `{e['name']}` ({e.get('human_en','')}; ZH: {zh}; ctx: {ctx}) → {sel_preview} (reuse: {e.get('coverage',0)}{feedback})")
    return "\n".join(lines)
