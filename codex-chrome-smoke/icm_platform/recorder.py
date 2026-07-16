from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import yaml


SUPPORTED_ACTIONS = frozenset({"click", "fill", "select", "check", "press", "navigate", "popup", "download"})
RISKY_ACTIONS = frozenset({"download"})
SENSITIVE_NAMES = re.compile(r"password|passwd|secret|token|api[_-]?key|credential", re.IGNORECASE)
UNSTABLE_SELECTOR = re.compile(r":nth-(?:child|of-type)\(", re.IGNORECASE)
SELECTOR_PRIORITY = ("testid", "role", "label", "placeholder", "text", "css")


class RecorderError(ValueError):
    """Raised when an incoming recording event cannot safely be retained."""


@dataclass(frozen=True)
class Selector:
    strategy: str
    value: str
    publishable: bool
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"strategy": self.strategy, "value": self.value, "publishable": self.publishable}
        if self.reason:
            data["reason"] = self.reason
        return data


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists recorder_sessions (
          id text primary key,
          start_url text not null,
          allowed_origins_json text not null,
          status text not null,
          failure_reason text,
          created_at text not null,
          stopped_at text,
          candidate_yaml text,
          candidate_python text
        );
        create table if not exists recorder_events (
          id integer primary key autoincrement,
          session_id text not null,
          sequence integer not null,
          action_json text not null,
          created_at text not null,
          unique(session_id, sequence),
          foreign key(session_id) references recorder_sessions(id)
        );
        create index if not exists idx_recorder_events_session on recorder_events(session_id, sequence);
        """
    )
    columns = {row["name"] for row in conn.execute("pragma table_info(recorder_sessions)")}
    if "failure_reason" not in columns:
        conn.execute("alter table recorder_sessions add column failure_reason text")


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise RecorderError("recording URL must be an absolute http(s) URL without credentials")
    return f"{parsed.scheme}://{parsed.netloc}"


def create_session(conn: sqlite3.Connection, *, start_url: str, allowed_origins: list[str]) -> dict[str, Any]:
    ensure_schema(conn)
    start_origin = _origin(start_url)
    normalized_origins = sorted({_origin(origin) for origin in allowed_origins})
    if start_origin not in normalized_origins:
        raise RecorderError("start URL origin must be explicitly allowlisted")
    session_id = f"rec-{uuid.uuid4().hex}"
    created_at = utc_now()
    conn.execute(
        "insert into recorder_sessions(id, start_url, allowed_origins_json, status, created_at) values (?, ?, ?, 'recording', ?)",
        (session_id, start_url, json.dumps(normalized_origins), created_at),
    )
    return {"id": session_id, "start_url": start_url, "allowed_origins": normalized_origins, "status": "recording", "created_at": created_at}


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    ensure_schema(conn)
    row = conn.execute("select * from recorder_sessions where id = ?", (session_id,)).fetchone()
    if not row:
        raise RecorderError("recording session not found")
    data = dict(row)
    data["allowed_origins"] = json.loads(data.pop("allowed_origins_json"))
    return data


def choose_selector(candidates: list[dict[str, Any]]) -> Selector:
    normalized = [item for item in candidates if item.get("strategy") in SELECTOR_PRIORITY and str(item.get("value", "")).strip()]
    if not normalized:
        return Selector("unknown", "", False, "no supported locator was captured")
    rank = {name: index for index, name in enumerate(SELECTOR_PRIORITY)}
    selected = min(normalized, key=lambda item: rank[str(item["strategy"])])
    value = str(selected["value"]).strip()
    if selected.get("unique") is False:
        return Selector(str(selected["strategy"]), value, False, "locator is not unique")
    if UNSTABLE_SELECTOR.search(value):
        return Selector(str(selected["strategy"]), value, False, "locator uses nth-child style structure")
    return Selector(str(selected["strategy"]), value, True)


def _is_sensitive(action: dict[str, Any]) -> bool:
    if action.get("sensitive"):
        return True
    return bool(SENSITIVE_NAMES.search(" ".join(str(action.get(key, "")) for key in ("name", "label", "selector_name", "target"))))


def _normalize_action(session: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    kind = str(action.get("type", ""))
    if kind not in SUPPORTED_ACTIONS:
        raise RecorderError(f"unsupported recording action: {kind}")
    target_url = action.get("url")
    if target_url and _origin(str(target_url)) not in set(session["allowed_origins"]):
        raise RecorderError("navigation origin is not allowlisted")
    if kind in RISKY_ACTIONS and not action.get("confirmed"):
        raise RecorderError(f"{kind} requires explicit confirmation")
    selector = (
        Selector("url", str(target_url), True)
        if kind == "navigate"
        else choose_selector(list(action.get("locator_candidates") or []))
    )
    result: dict[str, Any] = {"type": kind, "selector": selector.as_dict(), "publishable": selector.publishable}
    if target_url:
        result["url"] = str(target_url)
    if "value" in action:
        result["value"] = "${SECRET}" if _is_sensitive(action) else action["value"]
    if _is_sensitive(action):
        result["redacted"] = True
    if not selector.publishable:
        result["review_required"] = True
    return result


def append_action(conn: sqlite3.Connection, session_id: str, action: dict[str, Any]) -> dict[str, Any]:
    session = get_session(conn, session_id)
    if session["status"] != "recording":
        raise RecorderError("recording session is not active")
    normalized = _normalize_action(session, action)
    row = conn.execute("select coalesce(max(sequence), 0) + 1 as next_sequence from recorder_events where session_id = ?", (session_id,)).fetchone()
    sequence = int(row["next_sequence"])
    conn.execute(
        "insert into recorder_events(session_id, sequence, action_json, created_at) values (?, ?, ?, ?)",
        (session_id, sequence, json.dumps(normalized, ensure_ascii=False), utc_now()),
    )
    return {"sequence": sequence, "action": normalized}


def list_events(conn: sqlite3.Connection, session_id: str, *, after: int = 0) -> list[dict[str, Any]]:
    get_session(conn, session_id)
    rows = conn.execute("select sequence, action_json, created_at from recorder_events where session_id = ? and sequence > ? order by sequence", (session_id, after)).fetchall()
    return [{"sequence": row["sequence"], "action": json.loads(row["action_json"]), "created_at": row["created_at"]} for row in rows]


def _playwright_line(action: dict[str, Any]) -> str:
    selector = action["selector"]
    locator = {"testid": f"page.get_by_test_id({selector['value']!r})", "role": f"page.get_by_role({selector['value']!r})", "label": f"page.get_by_label({selector['value']!r})", "placeholder": f"page.get_by_placeholder({selector['value']!r})", "text": f"page.get_by_text({selector['value']!r})"}.get(selector["strategy"], f"page.locator({selector['value']!r})")
    if action["type"] == "navigate":
        return f"    await page.goto({action.get('url', '')!r})"
    if action["type"] == "fill":
        return f"    await {locator}.fill({action.get('value', '')!r})"
    if action["type"] == "select":
        return f"    await {locator}.select_option({action.get('value', '')!r})"
    if action["type"] == "check":
        return f"    await {locator}.check()"
    if action["type"] == "press":
        return f"    await {locator}.press({action.get('value', 'Enter')!r})"
    return f"    await {locator}.click()"


def stop_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    session = get_session(conn, session_id)
    if session["status"] == "stopped":
        return session
    events = list_events(conn, session_id)
    actions = [event["action"] for event in events]
    publishable = bool(actions) and all(action["publishable"] for action in actions)
    dsl = {"version": 1, "source": "recorder", "status": "candidate", "start_url": session["start_url"], "requires_review": True, "publishable": publishable, "steps": actions, "expected_results": []}
    python_lines = ["from playwright.async_api import Page", "", "", "async def run(page: Page) -> None:"]
    python_lines.extend(_playwright_line(action) for action in actions)
    if not actions:
        python_lines.append("    pass")
    candidate_yaml = yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False)
    candidate_python = "\n".join(python_lines) + "\n"
    stopped_at = utc_now()
    conn.execute("update recorder_sessions set status = 'stopped', stopped_at = ?, candidate_yaml = ?, candidate_python = ? where id = ?", (stopped_at, candidate_yaml, candidate_python, session_id))
    return {**get_session(conn, session_id), "events": events, "dsl": dsl, "candidate_yaml": candidate_yaml, "candidate_python": candidate_python}


def fail_session(conn: sqlite3.Connection, session_id: str, reason: str) -> dict[str, Any]:
    session = get_session(conn, session_id)
    if session["status"] != "recording":
        return session
    conn.execute(
        "update recorder_sessions set status = 'failed', stopped_at = ?, failure_reason = ? where id = ?",
        (utc_now(), reason, session_id),
    )
    return get_session(conn, session_id)
