"""Element library scanner and normalizer.

P1 scope: provide a small, testable scanner that can turn Playwright page
observations into ``reports/element-library/library.json``.  This module keeps
browser-dependent code thin and puts most behavior in pure functions so the
library format can be verified without launching a browser.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from runner.agent_explore import OBSERVE_PAGE_SCRIPT

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_PATH = ROOT / "reports" / "element-library" / "library.json"
ProgressCallback = Callable[[dict[str, Any]], None]
SCAN_NAVIGATION_TIMEOUT_MS = 8000
SCAN_SETTLE_TIMEOUT_MS = 500
SCAN_LOW_COVERAGE_RETRY_TIMEOUT_MS = 1000
STATE_ACTION_TIMEOUT_MS = 1500

_CONTENT_INTERACTIVE_COUNT_SCRIPT = """(selector) => {
  const root = document.querySelector(selector);
  if (!root) return 0;
  const visible = (element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  return [...root.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"], [role="menuitem"]')]
    .filter(visible)
    .length;
}"""

_UNSCANNABLE_REGIONS_SCRIPT = """() => {
  const visible = (element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
  };
  const selectorFor = (element) => {
    if (element.id) return `#${element.id}`;
    const siblings = Array.from(document.querySelectorAll(element.tagName.toLowerCase()));
    const index = siblings.indexOf(element) + 1;
    return `${element.tagName.toLowerCase()}:nth-of-type(${index})`;
  };
  const regions = [];
  for (const frame of Array.from(document.querySelectorAll('iframe')).filter(visible)) {
    let reason = 'iframe_not_scanned_by_top_document_collector';
    try {
      if (!frame.contentDocument) reason = 'cross_origin_or_unavailable_iframe';
    } catch (_) {
      reason = 'cross_origin_or_unavailable_iframe';
    }
    regions.push({
      kind: 'iframe',
      reason,
      selector: selectorFor(frame),
      label: frame.getAttribute('title') || frame.getAttribute('name') || '',
      src: frame.getAttribute('src') || '',
    });
  }
  for (const canvas of Array.from(document.querySelectorAll('canvas')).filter(visible)) {
    regions.push({
      kind: 'canvas',
      reason: 'canvas_visual_surface_not_dom_scanned',
      selector: selectorFor(canvas),
      label: canvas.getAttribute('aria-label') || canvas.getAttribute('title') || canvas.className || '',
      src: '',
    });
  }
  return regions;
}"""

_REQUIRED_ELEMENT_FIELDS = {
    "element_id",
    "page_id",
    "state",
    "name",
    "human_zh",
    "human_en",
    "tag",
    "role",
    "type",
    "text",
    "placeholder",
    "selectors",
    "locator_variants",
    "actions",
    "risk_level",
    "confidence",
    "last_seen_url",
}

_HIGH_RISK_TERMS = (
    "删除",
    "移除",
    "清空",
    "重置",
    "停用",
    "注销",
    "解绑",
    "发布",
    "发送",
    "付款",
    "支付",
    "确认删除",
    "delete",
    "remove",
    "clear",
    "reset",
    "disable",
    "logout",
    "unbind",
    "publish",
    "send",
    "pay",
    "payment",
)

_STATE_TRIGGER_RULES = (
    ("dialog:create", ("新增", "添加", "创建", "新建", "add", "create", "new"), "click"),
    ("dropdown:more", ("更多", "more", "操作", "actions", "dropdown"), "hover"),
    ("panel:filter", ("筛选", "高级筛选", "过滤", "filter"), "click"),
    ("panel:search", ("展开搜索", "搜索条件", "查询条件"), "click"),
    ("panel:expand", ("展开", "expand"), "click"),
)

_CONTROLLED_DIALOG_RULES = (
    ("dialog:edit", ("修改", "编辑", "edit", "modify"), False),
    ("dialog:delete", ("删除", "delete", "remove"), True),
)

_MORE_DESTINATION_TERMS = ("重置密码", "分配角色", "配置服务器和设备", "reset password", "assign role", "configure server")
_MUTATING_REQUEST_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_TAB_TERMS = ("tab", "标签页", "选项卡")

_CN_ACTION_HINTS = {
    "login": "登录",
    "logout": "退出",
    "save": "保存",
    "submit": "提交",
    "confirm": "确认",
    "cancel": "取消",
    "search": "搜索",
    "query": "查询",
    "add": "新增",
    "create": "创建",
    "edit": "编辑",
    "delete": "删除",
    "remove": "移除",
    "run": "执行",
    "execute": "执行",
    "report": "报告",
    "setting": "设置",
    "settings": "设置",
    "project": "项目",
    "requirement": "需求",
    "testcase": "测试用例",
    "case": "用例",
    "user": "用户",
    "username": "账号",
    "password": "密码",
    "device": "设备",
    "server": "服务器",
}

_TARGETS = [
    ("login", "登录页", "#/login"),
    ("home", "首页", "#/index"),
    ("project_management", "项目管理", "#/projects"),
    ("requirement_management", "需求管理", "#/requirements"),
    ("testcase_management", "测试用例", "#/test-cases"),
    ("execution_center", "执行中心", "#/execution"),
    ("report_detail", "报告详情", "#/reports"),
    ("system_settings", "系统设置", "#/settings"),
]

_LOGIN_ROUTE_RE = re.compile(r"(?:^|[/#?&])login(?:$|[/?#&=])", re.IGNORECASE)


def is_login_url(url: str) -> bool:
    """Return whether an observed browser URL is actually the login page.

    Protected routes often redirect anonymous users to ``#/login?redirect=...``.
    The scanner must classify those observations as the login page, not as the
    originally requested protected page.
    """
    value = str(url or "").strip()
    if not value:
        return False
    return bool(_LOGIN_ROUTE_RE.search(value.replace("%2F", "/")))


def resolve_observed_page(page: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Return page metadata corrected by the actual observed browser URL."""
    observed_url = str(observation.get("url") or page.get("url") or "")
    if is_login_url(observed_url):
        requested_page_id = str(page.get("page_id") or "")
        return {
            **page,
            "page_id": "login",
            "name": "登录页",
            "route": "#/login",
            "url": observed_url,
            "actual_url": observed_url,
            "requested_page_id": requested_page_id,
            "requested_url": str(page.get("url") or page.get("route") or ""),
            "blocked_by_login": requested_page_id != "login",
        }
    return {**page, "url": observed_url, "actual_url": observed_url, "blocked_by_login": False}


def default_scan_targets(base_url: str = "") -> list[dict[str, str]]:
    """Return the small P1 core-page scan target list.

    ``base_url`` is optional so tests can assert deterministic route metadata.
    When supplied, it is joined with the hash route for a Playwright ``goto``.
    """
    targets: list[dict[str, str]] = []
    base = (base_url or "").rstrip("/")
    for page_id, name, route in _TARGETS:
        url = urljoin(f"{base}/", route) if base else route
        targets.append({"page_id": page_id, "name": name, "route": route, "url": url})
    return targets


def normalize_page_id(name_or_route: str) -> str:
    """Normalize a page name or route into a stable snake_case page id."""
    value = (name_or_route or "").strip().lower()
    value = value.replace("#", " ").replace("/", " ").replace("-", "_")
    value = re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "page"


def _compact_text(*values: Any) -> str:
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if text:
            return text
    return ""


def _slug(value: str, *, fallback: str = "element") -> str:
    text = (value or "").strip().lower()
    for english, chinese in _CN_ACTION_HINTS.items():
        text = text.replace(chinese.lower(), f" {english} ")
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def _collapse_repeated_slug(value: str) -> str:
    parts = [part for part in str(value or "").split("_") if part]
    if parts and len(set(parts)) == 1:
        return parts[0]
    return value


def _clean_visible_text(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"[|｜]+", text) if part.strip()]
    tokens: list[str] = []
    source_tokens = parts if len(parts) > 1 else [text]
    for source_token in source_tokens:
        tokens.extend(part.strip() for part in source_token.split() if part.strip())
    deduped: list[str] = []
    for token in tokens:
        if token and token not in deduped:
            deduped.append(token)
    if len(deduped) == 1:
        return deduped[0]
    return text


def _clean_raw_display_text(raw: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(raw)
    for key in ("text", "ariaLabel", "placeholder", "name"):
        if cleaned.get(key):
            cleaned[key] = _clean_visible_text(cleaned.get(key))
    return cleaned


def _element_kind(raw: dict[str, Any]) -> str:
    tag = str(raw.get("tag") or "").lower()
    role = str(raw.get("role") or "").lower()
    raw_type = str(raw.get("type") or "").lower()
    if tag in {"input", "textarea"}:
        return "input"
    if raw.get("contenteditable") == "true":
        return "input"
    if tag == "select":
        return "select"
    if tag == "a" or role == "link":
        return "link"
    if tag == "button" or role == "button":
        return "button"
    if role == "menuitem":
        return "menu_item"
    if raw_type:
        return raw_type
    return tag or "element"


def infer_actions(raw: dict[str, Any]) -> list[str]:
    """Infer only actions currently supported by the Agent executor."""
    tag = str(raw.get("tag") or "").lower()
    role = str(raw.get("role") or "").lower()
    raw_type = str(raw.get("type") or "").lower()
    if tag in {"input", "textarea"} or raw.get("contenteditable") == "true":
        if raw_type in {"button", "submit", "reset", "checkbox", "radio"}:
            return ["click"]
        return ["fill", "press"]
    if tag == "select":
        return ["press"]
    if tag in {"button", "a"} or role in {"button", "link", "menuitem"}:
        return ["click", "hover"]
    return ["click"]


def infer_risk_level(raw: dict[str, Any]) -> str:
    haystack = " ".join(
        str(raw.get(key) or "")
        for key in ("text", "ariaLabel", "placeholder", "selector", "title", "name")
    ).lower()
    return "high" if any(term.lower() in haystack for term in _HIGH_RISK_TERMS) else "low"


def infer_state_trigger(raw: dict[str, Any]) -> dict[str, str] | None:
    """Infer whether an element can safely reveal a lightweight page state."""
    if raw.get("disabled"):
        return None
    actions = infer_actions(raw)
    haystack = " ".join(
        str(raw.get(key) or "")
        for key in ("text", "ariaLabel", "placeholder", "selector", "role", "title", "name")
    ).lower()
    role = str(raw.get("role") or "").lower()
    if "confirm" in haystack or "确认删除" in haystack:
        return None
    for state, terms, block_mutations in _CONTROLLED_DIALOG_RULES:
        if "click" in actions and any(term.lower() in haystack for term in terms):
            return {
                "state": state,
                "action": "click",
                "requires_dialog": "true",
                "block_mutations": str(block_mutations).lower(),
            }
    if infer_risk_level(raw) == "high":
        return None
    if role == "tab" or any(term in haystack for term in _TAB_TERMS):
        if "click" in actions:
            tab_name = _slug(_compact_text(raw.get("text"), raw.get("ariaLabel"), raw.get("name")), fallback="tab")
            return {"state": f"tab:{tab_name}", "action": "click"}
    for state, terms, action in _STATE_TRIGGER_RULES:
        if state == "dropdown:more" and (str(raw.get("tag") or "").lower() != "button" and role != "button"):
            continue
        if action in actions and any(term.lower() in haystack for term in terms):
            return {"state": state, "action": action}
    return None


def build_human_labels(raw: dict[str, Any], page_name: str = "") -> list[str]:
    visible = _compact_text(raw.get("text"), raw.get("ariaLabel"), raw.get("placeholder"), raw.get("name"))
    kind = _element_kind(raw)
    suffix = {
        "input": "输入框",
        "select": "下拉框",
        "button": "按钮",
        "link": "链接",
        "menu_item": "菜单项",
    }.get(kind, "元素")
    labels: list[str] = []
    if visible:
        labels.append(f"{visible}{suffix}" if suffix not in visible else visible)
        labels.append(visible)
    if page_name and visible:
        labels.append(f"{page_name}{visible}{suffix}")
    if not labels and page_name:
        labels.append(f"{page_name}{suffix}")
    deduped: list[str] = []
    for label in labels:
        if label and label not in deduped:
            deduped.append(label)
    return deduped or [suffix]


def _human_en(raw: dict[str, Any], name: str) -> str:
    visible = _compact_text(raw.get("text"), raw.get("ariaLabel"), raw.get("placeholder"), raw.get("name"))
    kind = _element_kind(raw).replace("_", " ")
    if visible and visible.isascii():
        return f"{visible.lower()} {kind}".strip()
    return name.replace("_", " ")


def _context_keys(page: dict[str, Any], raw: dict[str, Any]) -> list[str]:
    keys = [page.get("page_id"), page.get("name"), page.get("state") or "default", raw.get("role"), raw.get("tag")]
    result: list[str] = []
    for key in keys:
        text = str(key or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _css_attribute_selector(tag: str, attribute: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    prefix = f"{tag}" if tag else ""
    return f'{prefix}[{attribute}="{escaped}"]'


def build_locator_variants(raw: dict[str, Any], selectors: list[str]) -> list[dict[str, str]]:
    """Record observed locator signals with an explicit stability grade."""
    tag = str(raw.get("tag") or "").strip().lower()
    variants: list[dict[str, str]] = []

    def add(kind: str, value: str, stability: str, *, selector: str = "", role: str = "") -> None:
        value = str(value or "").strip()
        if not value:
            return
        variant = {"kind": kind, "value": value, "stability": stability}
        if selector:
            variant["selector"] = selector
        if role:
            variant["role"] = role
        if variant not in variants:
            variants.append(variant)

    test_id = str(raw.get("testId") or "").strip()
    test_id_attribute = str(raw.get("testIdAttribute") or "data-testid").strip()
    if test_id:
        add("testid", test_id, "high", selector=_css_attribute_selector(tag, test_id_attribute, test_id))
    role = str(raw.get("role") or "").strip()
    accessible_name = _compact_text(raw.get("ariaLabel"), raw.get("text"))
    if role and accessible_name:
        add("role_name", accessible_name, "high", role=role)
    aria_label = str(raw.get("ariaLabel") or "").strip()
    if aria_label:
        add("aria_label", aria_label, "high", selector=_css_attribute_selector(tag, "aria-label", aria_label))
    name = str(raw.get("name") or "").strip()
    if name:
        add("name", name, "high", selector=_css_attribute_selector(tag, "name", name))
    placeholder = str(raw.get("placeholder") or "").strip()
    if placeholder:
        add("placeholder", placeholder, "medium", selector=_css_attribute_selector(tag, "placeholder", placeholder))
    text = str(raw.get("text") or "").strip()
    if text:
        add("text", text, "medium")
    for selector in selectors:
        normalized = str(selector or "").strip()
        if normalized:
            add("css", normalized, "low")
    return variants


def normalize_element(raw: dict[str, Any], page: dict[str, Any], *, index: int) -> dict[str, Any]:
    raw = _clean_raw_display_text(raw)
    page_id = str(page.get("page_id") or normalize_page_id(str(page.get("name") or page.get("route") or "page")))
    page_name = str(page.get("name") or page_id)
    state = str(page.get("state") or "default")
    visible = _compact_text(raw.get("text"), raw.get("ariaLabel"), raw.get("placeholder"), raw.get("name"))
    kind = _element_kind(raw)
    base_name = _collapse_repeated_slug(_slug(visible, fallback=f"element_{index + 1:03d}"))
    if kind not in base_name:
        base_name = f"{base_name}_{kind}"
    selector = str(raw.get("selector") or "").strip()
    selectors = []
    if base_name == "login_button":
        selectors.append('button:has-text("登录")')
    if selector and selector not in selectors:
        selectors.append(selector)
    name = base_name
    element = {
        "element_id": f"{page_id}.{name}",
        "page_id": page_id,
        "state": state,
        "name": name,
        "human_zh": build_human_labels(raw, page_name),
        "human_en": _human_en(raw, name),
        "tag": str(raw.get("tag") or ""),
        "role": str(raw.get("role") or ""),
        "type": str(raw.get("type") or ""),
        "text": str(raw.get("text") or ""),
        "placeholder": str(raw.get("placeholder") or ""),
        "selectors": selectors,
        "locator_variants": build_locator_variants(raw, selectors),
        "actions": infer_actions(raw),
        "risk_level": infer_risk_level(raw),
        "confidence": 0.82 if selector and visible else 0.65 if selector else 0.45,
        "last_seen_url": str(raw.get("last_seen_url") or page.get("url") or ""),
        "context_keys": _context_keys(page, raw),
        "ariaLabel": str(raw.get("ariaLabel") or ""),
        "coverage": 1,
        "states": [state],
        "state_coverage": {
            state: {
                "source_refs": [str(raw.get("ref") or "")],
                "last_seen_urls": [str(raw.get("last_seen_url") or page.get("url") or "")],
                "labels": _state_labels(raw),
            }
        },
        "source_ref": str(raw.get("ref") or ""),
        "generated_by": "element_scanner_p1",
    }
    missing = _REQUIRED_ELEMENT_FIELDS - set(element)
    if missing:
        raise ValueError(f"normalized element is missing required fields: {sorted(missing)}")
    return element


def _element_identity(element: dict[str, Any]) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    return (
        str(element.get("page_id") or ""),
        tuple(sorted(str(value) for value in element.get("selectors") or [])),
        tuple(sorted(str(value) for value in element.get("actions") or [])),
    )


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _state_labels(raw: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for value in (raw.get("text"), raw.get("ariaLabel"), raw.get("name"), raw.get("placeholder")):
        text = str(value or "").strip()
        if text:
            _append_unique(labels, text)
    return labels


def _merge_element_coverage(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing["coverage"] = int(existing.get("coverage") or 0) + int(incoming.get("coverage") or 1)
    existing_states = existing.setdefault("states", [str(existing.get("state") or "default")])
    state_coverage = existing.setdefault("state_coverage", {})
    for state in incoming.get("states") or [str(incoming.get("state") or "default")]:
        normalized_state = str(state or "default")
        _append_unique(existing_states, normalized_state)
        destination = state_coverage.setdefault(normalized_state, {"source_refs": [], "last_seen_urls": []})
        source = (incoming.get("state_coverage") or {}).get(normalized_state) or {}
        for source_ref in source.get("source_refs") or [incoming.get("source_ref")]:
            _append_unique(destination.setdefault("source_refs", []), str(source_ref or ""))
        for url in source.get("last_seen_urls") or [incoming.get("last_seen_url")]:
            _append_unique(destination.setdefault("last_seen_urls", []), str(url or ""))
        for label in source.get("labels") or _state_labels(incoming):
            _append_unique(destination.setdefault("labels", []), str(label or ""))
    for value in incoming.get("context_keys") or []:
        _append_unique(existing.setdefault("context_keys", []), str(value or ""))
    existing["confidence"] = max(float(existing.get("confidence") or 0), float(incoming.get("confidence") or 0))
    if incoming.get("risk_level") == "high":
        existing["risk_level"] = "high"
    for variant in incoming.get("locator_variants") or []:
        if variant not in existing.setdefault("locator_variants", []):
            existing["locator_variants"].append(variant)
    if "default" in existing_states:
        existing["state"] = "default"


def _row_semantic_identity(element: dict[str, Any]) -> tuple[str, str, tuple[str, ...], str, str, str] | None:
    selectors = [str(selector) for selector in element.get("selectors") or []]
    if not any("tbody" in selector and "tr:nth-of-type" in selector for selector in selectors):
        return None
    return (
        str(element.get("page_id") or ""),
        str(element.get("name") or ""),
        tuple(sorted(str(action) for action in element.get("actions") or [])),
        str(element.get("tag") or ""),
        str(element.get("role") or ""),
        str(element.get("type") or ""),
    )


def _deduplicate_repeated_row_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated table-row controls while retaining each observed selector."""
    deduplicated: list[dict[str, Any]] = []
    elements_by_semantic_identity: dict[tuple[str, str, tuple[str, ...], str, str, str], dict[str, Any]] = {}
    for element in elements:
        identity = _row_semantic_identity(element)
        existing = elements_by_semantic_identity.get(identity) if identity else None
        if existing is None:
            deduplicated.append(element)
            if identity:
                elements_by_semantic_identity[identity] = element
            continue
        _merge_element_coverage(existing, element)
        for selector in element.get("selectors") or []:
            _append_unique(existing.setdefault("selectors", []), str(selector or ""))
        for variant in element.get("locator_variants") or []:
            if variant not in existing.setdefault("locator_variants", []):
                existing["locator_variants"].append(variant)
    return deduplicated


def deduplicate_library_elements(library: dict[str, Any]) -> dict[str, Any]:
    """Return the library with repeated table-row controls consolidated."""
    return {**library, "elements": _deduplicate_repeated_row_elements(list(library.get("elements") or []))}


def build_library(scan_results: list[dict[str, Any]]) -> dict[str, Any]:
    pages_by_id: dict[str, dict[str, Any]] = {}
    elements: list[dict[str, Any]] = []
    elements_by_identity: dict[tuple[str, tuple[str, ...], tuple[str, ...]], dict[str, Any]] = {}
    for result in scan_results:
        requested_page = dict(result.get("page") or {})
        observation = result.get("observation") or {}
        page = resolve_observed_page(requested_page, observation)
        page_id = str(page.get("page_id") or normalize_page_id(str(page.get("name") or observation.get("url") or "page")))
        page["page_id"] = page_id
        page.setdefault("name", page_id)
        page.setdefault("state", "default")
        page_url = str(page.get("url") or observation.get("url") or "")
        page["url"] = page_url
        page_record = {
            "page_id": page_id,
            "name": str(page.get("name") or page_id),
            "url": page_url,
            "url_pattern": str(page.get("route") or page_url),
            "title": str(observation.get("title") or page.get("title") or ""),
            "states": [str(page.get("state") or "default")],
        }
        regions = [dict(item) for item in observation.get("unscannable_regions") or [] if isinstance(item, dict)]
        if regions:
            page_record["unscannable_regions"] = regions
        if page.get("blocked_by_login"):
            page_record["blocked_by_login"] = True
            page_record["requested_page_ids"] = [str(page.get("requested_page_id") or "")]
            page_record["requested_urls"] = [str(page.get("requested_url") or "")]
        if page_id in pages_by_id:
            existing_page = pages_by_id[page_id]
            states = existing_page.setdefault("states", [])
            for state in page_record["states"]:
                if state not in states:
                    states.append(state)
            if page_record.get("blocked_by_login"):
                existing_page["blocked_by_login"] = True
                for key in ("requested_page_ids", "requested_urls"):
                    values = existing_page.setdefault(key, [])
                    for value in page_record.get(key, []):
                        if value and value not in values:
                            values.append(value)
            for region in page_record.get("unscannable_regions") or []:
                if region not in existing_page.setdefault("unscannable_regions", []):
                    existing_page["unscannable_regions"].append(region)
        else:
            pages_by_id[page_id] = page_record
        for index, raw in enumerate(observation.get("interactives") or []):
            normalized = normalize_element({**raw, "last_seen_url": page_url}, page, index=index)
            identity = _element_identity(normalized)
            existing = elements_by_identity.get(identity)
            if existing is None:
                elements_by_identity[identity] = normalized
                elements.append(normalized)
            else:
                _merge_element_coverage(existing, normalized)
    return deduplicate_library_elements(
        {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system": "ICM",
        "pages": list(pages_by_id.values()),
        "elements": elements,
        }
    )


def write_library(library: dict[str, Any], path: Path | None = None) -> Path:
    output = path or DEFAULT_LIBRARY_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _interactive_count(observation: dict[str, Any]) -> int:
    return len(observation.get("interactives") or [])


async def _settled_observation(page: Any) -> dict[str, Any]:
    first = await page.evaluate(OBSERVE_PAGE_SCRIPT)
    if not hasattr(page, "wait_for_timeout"):
        return first
    await page.wait_for_timeout(SCAN_SETTLE_TIMEOUT_MS)
    second = await page.evaluate(OBSERVE_PAGE_SCRIPT)
    return second if _interactive_count(second) >= _interactive_count(first) else first


async def _wait_for_page_ready(page: Any, selector: str) -> None:
    if not selector:
        return
    locator = page.locator(selector)
    await locator.first.wait_for(state="visible", timeout=SCAN_NAVIGATION_TIMEOUT_MS)


async def _content_interactive_count(page: Any, selector: str) -> int:
    if not selector:
        return 0
    return max(0, int(await page.evaluate(_CONTENT_INTERACTIVE_COUNT_SCRIPT, selector) or 0))


async def scan_page(page: Any, target: dict[str, Any]) -> dict[str, Any]:
    """Scan one target after two observations, rejecting persisted low coverage."""
    url = target.get("url") or target.get("route") or ""
    if url:
        await page.goto(url, wait_until="domcontentloaded", timeout=SCAN_NAVIGATION_TIMEOUT_MS)
    await _wait_for_page_ready(page, str(target.get("ready_selector") or ""))
    observation = await _settled_observation(page)
    minimum = max(0, int(target.get("minimum_interactive_count") or 0))
    if _interactive_count(observation) < minimum and hasattr(page, "wait_for_timeout"):
        await page.wait_for_timeout(SCAN_LOW_COVERAGE_RETRY_TIMEOUT_MS)
        retry_observation = await _settled_observation(page)
        if _interactive_count(retry_observation) >= _interactive_count(observation):
            observation = retry_observation
    if _interactive_count(observation) < minimum:
        raise RuntimeError(
            f"low coverage: {target.get('page_id') or 'page'} observed {_interactive_count(observation)} interactive elements; minimum is {minimum}"
        )
    content_selector = str(target.get("content_selector") or "")
    content_minimum = max(0, int(target.get("minimum_content_interactive_count") or 0))
    content_count = await _content_interactive_count(page, content_selector)
    if content_count < content_minimum:
        raise RuntimeError(
            f"low content coverage: {target.get('page_id') or 'page'} observed {content_count} interactive elements in {content_selector}; minimum is {content_minimum}"
        )
    observation = await _append_configured_surface_hints(page, target, observation)
    observation["unscannable_regions"] = await _unscannable_regions(page)
    return {"page": {**target, "state": target.get("state") or "default"}, "observation": observation}


async def _unscannable_regions(page: Any) -> list[dict[str, str]]:
    try:
        regions = await page.evaluate(_UNSCANNABLE_REGIONS_SCRIPT)
    except Exception:
        return []
    return [dict(item) for item in regions or [] if isinstance(item, dict)]


def _configured_surface_hints(target: dict[str, Any]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for raw in target.get("surface_hints") or []:
        if not isinstance(raw, dict):
            continue
        selector = str(raw.get("selector") or "").strip()
        label = str(raw.get("label") or "").strip()
        if not selector or not label:
            continue
        hints.append(
            {
                "selector": selector,
                "label": label,
                "tag": str(raw.get("tag") or "div"),
                "role": str(raw.get("role") or "button"),
                "max_matches": max(1, min(12, int(raw.get("max_matches") or 1))),
            }
        )
    return hints


async def _append_configured_surface_hints(page: Any, target: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    hints = _configured_surface_hints(target)
    if not hints or not hasattr(page, "locator"):
        return observation
    enriched = {**observation, "interactives": list(observation.get("interactives") or [])}
    for hint_index, hint in enumerate(hints, start=1):
        locator = page.locator(hint["selector"])
        try:
            count = min(int(await locator.count()), int(hint["max_matches"]))
        except Exception:
            continue
        for match_index in range(count):
            candidate = locator.nth(match_index)
            try:
                if not await candidate.is_visible():
                    continue
            except Exception:
                continue
            text = hint["label"]
            try:
                observed_text = " ".join(str(await candidate.inner_text()).split())
                if observed_text and observed_text != hint["label"]:
                    text = f"{hint['label']} {observed_text}"
            except Exception:
                pass
            selector = hint["selector"] if count == 1 else f"{hint['selector']} >> nth={match_index}"
            if any(str(item.get("selector") or "") == selector for item in enriched["interactives"]):
                continue
            enriched["interactives"].append(
                {
                    "ref": f"configured-surface-{hint_index}-{match_index + 1}",
                    "tag": hint["tag"],
                    "role": hint["role"],
                    "text": text,
                    "ariaLabel": hint["label"],
                    "selector": selector,
                    "disabled": False,
                }
            )
    return enriched


async def _restore_default_state(page: Any) -> None:
    keyboard = getattr(page, "keyboard", None)
    if keyboard is not None and hasattr(keyboard, "press"):
        await keyboard.press("Escape")
    if hasattr(page, "wait_for_timeout"):
        await page.wait_for_timeout(120)


async def _click_with_mutations_blocked(page: Any, locator: Any, *, timeout: int = STATE_ACTION_TIMEOUT_MS) -> bool:
    context = getattr(page, "context", None)
    if context is None or not hasattr(context, "route") or not hasattr(context, "unroute"):
        return False

    async def block_mutation(route: Any) -> None:
        request = route.request
        if str(request.method or "").upper() in _MUTATING_REQUEST_METHODS:
            await route.abort()
        else:
            await route.continue_()

    await context.route("**/*", block_mutation)
    try:
        await locator.click(timeout=timeout)
        return True
    finally:
        await context.unroute("**/*", block_mutation)


async def _activate_trigger(page: Any, trigger: dict[str, str], raw: dict[str, Any]) -> bool:
    selector = str(raw.get("selector") or "").strip()
    if not selector or not hasattr(page, "locator"):
        return False
    locator = page.locator(selector)
    action = trigger.get("action") or "click"
    try:
        if action == "hover" and hasattr(locator, "hover"):
            await locator.hover(timeout=STATE_ACTION_TIMEOUT_MS)
        elif action == "click" and hasattr(locator, "click"):
            if trigger.get("block_mutations") == "true":
                if not await _click_with_mutations_blocked(page, locator):
                    return False
            else:
                await locator.click(timeout=STATE_ACTION_TIMEOUT_MS)
        else:
            return False
        if hasattr(page, "wait_for_timeout"):
            await page.wait_for_timeout(300)
        return True
    except Exception:
        return False


def _has_dialog(observation: dict[str, Any]) -> bool:
    return bool(observation.get("dialogs"))


async def _close_controlled_dialog(page: Any) -> None:
    observation = await page.evaluate(OBSERVE_PAGE_SCRIPT)
    if not _has_dialog(observation):
        return
    for selector in (".el-dialog__headerbtn:visible", ".el-message-box__headerbtn:visible", ".el-message-box__close:visible"):
        if not hasattr(page, "locator"):
            break
        locator = page.locator(selector)
        try:
            await locator.click(timeout=2000)
        except Exception:
            continue
        if await _wait_for_controlled_dialog_to_close(page):
            return
    await _restore_default_state(page)
    if await _wait_for_controlled_dialog_to_close(page):
        return
    raise RuntimeError("controlled dialog could not be closed")


async def _wait_for_controlled_dialog_to_close(page: Any) -> bool:
    if hasattr(page, "wait_for_function"):
        try:
            await page.wait_for_function(
                """() => {
                    const visible = (el) => {
                      const style = window.getComputedStyle(el);
                      const rect = el.getBoundingClientRect();
                      return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && rect.width > 0 && rect.height > 0;
                    };
                    return !Array.from(document.querySelectorAll('[role=dialog],.el-dialog,.el-message-box')).some(visible);
                }""",
                timeout=2000,
            )
            return True
        except Exception:
            return False
    observation = await page.evaluate(OBSERVE_PAGE_SCRIPT)
    return not _has_dialog(observation)


def _more_destination_label(raw: dict[str, Any]) -> str:
    text = _compact_text(raw.get("text"), raw.get("ariaLabel"), raw.get("name")).lower()
    for term in _MORE_DESTINATION_TERMS:
        if term.lower() in text:
            return _slug(text, fallback="more_destination")
    return ""


async def _scan_more_destination(page: Any, target: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    label = _more_destination_label(raw)
    if not label:
        return None
    before_url = str(getattr(page, "url", "") or "")
    context = getattr(page, "context", None)
    before_pages = list(getattr(context, "pages", []) or [])
    if not await _activate_trigger(page, {"action": "click", "block_mutations": "true"}, raw):
        return None
    popup_pages = [candidate for candidate in list(getattr(context, "pages", []) or []) if candidate not in before_pages]
    destination_page = popup_pages[0] if popup_pages else page
    destination_observation = await _settled_observation(destination_page)
    if _has_dialog(destination_observation):
        await _close_controlled_dialog(destination_page)
        return {
            "page": {**target, "state": f"dialog:{label}", "state_trigger_ref": str(raw.get("ref") or "")},
            "observation": destination_observation,
        }
    result = {
        "page": {
            "page_id": f"{target.get('page_id') or 'page'}__{label}",
            "name": f"{target.get('name') or target.get('page_id') or 'page'} {label}",
            "route": str(destination_observation.get("url") or ""),
            "url": str(destination_observation.get("url") or ""),
            "state": "default",
        },
        "observation": destination_observation,
    }
    if destination_page is not page and hasattr(destination_page, "close"):
        await destination_page.close()
    if before_url and hasattr(page, "goto"):
        await page.goto(before_url, wait_until="domcontentloaded", timeout=SCAN_NAVIGATION_TIMEOUT_MS)
    return result


async def scan_page_with_states(
    page: Any,
    target: dict[str, Any],
    *,
    max_states: int = 8,
    max_per_state_kind: int = 2,
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    """Scan one page and bounded safe states such as dialogs, menus, filters, and tabs."""
    default_result = await scan_page(page, target)
    results = [default_result]
    observation = default_result.get("observation") or {}
    triggers: list[tuple[dict[str, str], dict[str, Any], int]] = []
    for index, trigger in enumerate(_configured_state_triggers(target), start=1):
        triggers.append(
            (
                trigger,
                {
                    "ref": f"configured-state-{index}",
                    "selector": trigger["selector"],
                    "text": trigger.get("label") or "",
                    "ariaLabel": trigger.get("label") or "",
                },
                -index,
            )
        )
    for index, raw in enumerate(observation.get("interactives") or []):
        trigger = infer_state_trigger(raw)
        if trigger:
            triggers.append((trigger, raw, index))
    state_counts: dict[str, int] = {}
    state_attempts: dict[str, int] = {}
    for trigger, raw, index in triggers:
        state_kind = trigger["state"]
        state_count = state_counts.get(state_kind, 0)
        attempt_count = state_attempts.get(state_kind, 0)
        max_attempts = max_per_state_kind + 1
        if state_count >= max_per_state_kind or attempt_count >= max_attempts or len(results) - 1 >= max_states:
            continue
        state_attempts[state_kind] = attempt_count + 1
        if progress_callback:
            progress_callback(
                {
                    "stage": "scanning_page_state",
                    "current_page": target.get("page_id"),
                    "state": state_kind,
                    "state_attempt": attempt_count + 1,
                    "state_attempt_limit": max_attempts,
                }
            )
        if not await _activate_trigger(page, trigger, raw):
            if progress_callback:
                progress_callback(
                    {
                        "stage": "page_state_skipped",
                        "current_page": target.get("page_id"),
                        "state": state_kind,
                        "reason": "trigger_not_actionable",
                    }
                )
            continue
        state_observation = await page.evaluate(OBSERVE_PAGE_SCRIPT)
        state_label = _slug(_compact_text(raw.get("text"), raw.get("ariaLabel"), raw.get("name")), fallback=f"trigger_{index + 1}")
        state = state_kind if state_count == 0 else f"{state_kind}:{state_label}"
        state_target = {**target, "state": state, "state_trigger_ref": str(raw.get("ref") or f"e{index + 1}")}
        if trigger.get("requires_dialog") == "true":
            if not _has_dialog(state_observation):
                await _restore_default_state(page)
                continue
            results.append({"page": state_target, "observation": state_observation})
            await _close_controlled_dialog(page)
        else:
            results.append({"page": state_target, "observation": state_observation})
            if state_kind == "dropdown:more":
                for menu_raw in state_observation.get("interactives") or []:
                    destination = await _scan_more_destination(page, target, menu_raw)
                    if destination is not None:
                        results.append(destination)
        state_counts[state_kind] = state_count + 1
        if progress_callback:
            progress_callback(
                {
                    "stage": "page_state_scanned",
                    "current_page": target.get("page_id"),
                    "state": state,
                    "observation_count": len(results),
                }
            )
        await _restore_default_state(page)
    return results


def _configured_state_triggers(target: dict[str, Any]) -> list[dict[str, str]]:
    """Return explicit, non-mutating page states declared by an environment profile."""
    triggers: list[dict[str, str]] = []
    for raw in target.get("state_triggers") or []:
        if not isinstance(raw, dict):
            continue
        state = str(raw.get("state") or "").strip()
        selector = str(raw.get("selector") or "").strip()
        action = str(raw.get("action") or "hover").strip().lower()
        if not state or not selector or action not in {"hover", "click"}:
            continue
        triggers.append(
            {
                "state": state,
                "selector": selector,
                "action": action,
                "label": str(raw.get("label") or "").strip(),
                "block_mutations": str(raw.get("block_mutations") or "false").lower(),
            }
        )
    return triggers


def summarize_scan_results(scan_results: list[dict[str, Any]]) -> dict[str, Any]:
    page_ids = {str((result.get("page") or {}).get("page_id") or "") for result in scan_results}
    element_count = 0
    high_risk_count = 0
    for result in scan_results:
        for raw in (result.get("observation") or {}).get("interactives") or []:
            element_count += 1
            if infer_risk_level(raw) == "high":
                high_risk_count += 1
    return {
        "scanned_page_count": len([page_id for page_id in page_ids if page_id]),
        "observation_count": len(scan_results),
        "element_count": element_count,
        "high_risk_count": high_risk_count,
    }


async def scan_targets(
    page: Any,
    targets: list[dict[str, str]],
    *,
    include_states: bool = False,
    state_scan_max_states: int = 8,
    state_scan_max_per_kind: int = 2,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    results = []
    total = len(targets)
    for index, target in enumerate(targets, start=1):
        if progress_callback:
            progress_callback({"stage": "scanning_page", "current_page": target.get("page_id"), "page_index": index, "page_total": total})
        before = len(results)
        try:
            if include_states:
                scanned = await scan_page_with_states(
                    page,
                    target,
                    max_states=state_scan_max_states,
                    max_per_state_kind=state_scan_max_per_kind,
                    progress_callback=progress_callback,
                )
            else:
                scanned = [await scan_page(page, target)]
            observed_page = resolve_observed_page(target, scanned[0].get("observation") or {})
            if observed_page.get("blocked_by_login"):
                raise RuntimeError(f"authenticated scan required: {target.get('page_id') or 'target'} redirected to login")
            results.extend(scanned)
        except Exception as exc:
            if progress_callback:
                progress_callback({"stage": "page_failed", "current_page": target.get("page_id"), "page_index": index, "page_total": total, "error": str(exc)})
            raise
        summary = summarize_scan_results(results)
        if progress_callback:
            progress_callback(
                {
                    "stage": "page_scanned",
                    "current_page": target.get("page_id"),
                    "page_index": index,
                    "page_total": total,
                    "observations_added": len(results) - before,
                    **summary,
                }
            )
    library = build_library(results)
    if progress_callback:
        progress_callback({"stage": "library_built", "page_total": total, "library_element_count": len(library.get("elements") or []), **summarize_scan_results(results)})
    return library


async def scan_and_write(
    page: Any,
    *,
    base_url: str = "",
    targets: list[dict[str, str]] | None = None,
    output_path: Path | None = None,
    include_states: bool = False,
    state_scan_max_states: int = 8,
    state_scan_max_per_kind: int = 2,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Scan targets with a Playwright page-like object and write library.json."""
    library = await scan_targets(
        page,
        targets or default_scan_targets(base_url),
        include_states=include_states,
        state_scan_max_states=state_scan_max_states,
        state_scan_max_per_kind=state_scan_max_per_kind,
        progress_callback=progress_callback,
    )
    return write_library(library, output_path)
