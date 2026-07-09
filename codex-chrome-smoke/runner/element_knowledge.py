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
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_LIBRARY = _ROOT / "reports" / "element-library" / "library.json"

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


@lru_cache(maxsize=1)
def _load_library() -> dict[str, Any] | None:
    if not _LIBRARY.exists():
        return None
    try:
        return json.loads(_LIBRARY.read_text(encoding="utf-8"))
    except Exception:
        return None


def _tokenize(text: str) -> set[str]:
    text = (text or "").lower()
    return {tok for tok in re.split(r"[\s,;:_/.\-()\[\]【】、，；。]+", text) if tok}


def rank_for_intent(intent: str, route: str = "", *, top_k: int = 6) -> list[dict[str, Any]]:
    """Return top_k elements whose NL synonyms match `intent` (and route)."""
    lib = _load_library()
    if not lib:
        return []
    intent_tokens = _tokenize(intent)
    route_norm = (route or "").strip().lower()
    scored: list[tuple[float, dict[str, Any]]] = []
    for e in lib.get("elements") or []:
        score = 0.0
        text_haystack = " ".join([
            e.get("name", ""),
            e.get("human_en", ""),
            " ".join(e.get("human_zh") or []),
            " ".join(e.get("context_keys") or []),
            " ".join(e.get("selectors") or []),
        ]).lower()
        # token overlap on human_en + human_zh
        text_tokens = _tokenize(text_haystack)
        overlap = intent_tokens & text_tokens
        score += 4.0 * len(overlap)
        # substring hit boost
        if intent.lower() and intent.lower() in text_haystack:
            score += 8.0
        # coverage bonus (reused elements > single-case)
        score += 0.4 * float(e.get("coverage", 0))
        # route-specific boost
        if route_norm and route_norm in " ".join(e.get("selectors") or []).lower():
            score += 1.5
        # context_keys boost (e.g. intent contains "弹窗" & element is dialog)
        for ck in e.get("context_keys") or []:
            if ck.lower() in intent.lower():
                score += 1.0
        if score > 0:
            scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:top_k]]


def format_candidate_elements(intent: str, route: str = "", *, top_k: int = 6) -> str:
    """Markdown snippet intended for injection into agent_explore.build_agent_prompt.

    Returns '' when nothing matches (safe to always concatenate).
    """
    rows = rank_for_intent(intent, route, top_k=top_k)
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
        lines.append(f"- `{e['name']}` ({e.get('human_en','')}; ZH: {zh}; ctx: {ctx}) → {sel_preview} (reuse: {e.get('coverage',0)})")
    return "\n".join(lines)
