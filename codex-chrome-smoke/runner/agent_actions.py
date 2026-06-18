from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


SAFE_ACTIONS = {"goto", "fill", "click", "press", "wait", "scroll", "assert_text", "finish", "fail"}
REF_ACTIONS = {"fill", "click"}


@dataclass(slots=True)
class AgentDecision:
    action: str
    ref: str = ""
    url: str = ""
    value: str = ""
    key: str = ""
    reason: str = ""


def _text(value: object) -> str:
    return str(value or "").strip()


def normalize_decision(raw: dict) -> AgentDecision:
    action = _text(raw.get("action"))
    if action not in SAFE_ACTIONS:
        return AgentDecision(action="fail", reason=f"unsupported action: {action or 'empty'}")
    return AgentDecision(
        action=action,
        ref=_text(raw.get("ref")),
        url=_text(raw.get("url")),
        value=_text(raw.get("value")),
        key=_text(raw.get("key")),
        reason=_text(raw.get("reason")),
    )


def validate_decision(decision: AgentDecision, observed_refs: set[str], allowed_hosts: set[str]) -> list[str]:
    errors: list[str] = []
    if decision.action in REF_ACTIONS and decision.ref not in observed_refs:
        errors.append(f"unknown ref: {decision.ref or 'empty'}")
    if decision.action == "press" and decision.ref and decision.ref not in observed_refs:
        errors.append(f"unknown ref: {decision.ref or 'empty'}")
    if decision.action == "press" and not (decision.ref or decision.key):
        errors.append("press requires ref or key")
    if decision.action == "goto":
        parsed = urlparse(decision.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append("goto requires absolute http(s) url")
        elif parsed.hostname not in allowed_hosts:
            errors.append(f"host not allowed: {parsed.hostname}")
    return errors
