"""Safe second-pass locator selection for Recorder.

This module deliberately has no Playwright or model-client dependency.  Callers
provide DOM-derived candidates and may optionally supply an AI scoring function.
Only selectors already proven by the browser observer are returned.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping


SUPPORTED_STRATEGIES = frozenset({"css", "xpath"})

# Vue scope ids, generated tooltip ids, structural indexes and embedded image
# data are all implementation details rather than durable product contracts.
_FRAGILE_PATTERNS = (
    re.compile(r":nth-(?:child|of-type)\(", re.IGNORECASE),
    re.compile(r"\[\s*data-v-[^\]]+\]", re.IGNORECASE),
    re.compile(r"data-v-[0-9a-f]{4,}", re.IGNORECASE),
    re.compile(r"(?:el-)?tooltip[-_]\d+", re.IGNORECASE),
    re.compile(r"aria-describedby[^\]]*tooltip", re.IGNORECASE),
    re.compile(r"data:image|base64", re.IGNORECASE),
    re.compile(r"\[\s*src\s*[~|^$*]?=", re.IGNORECASE),
    re.compile(r"\bposition\s*\(|\blast\s*\(", re.IGNORECASE),
    re.compile(r"\[\s*\d+\s*\]"),
)


@dataclass(frozen=True)
class LocatorCandidate:
    """One CSS or XPath candidate, with browser-observed validation facts."""

    strategy: str
    value: str
    unique: bool = False
    visible: bool = False
    enabled: bool = False
    covers_click_point: bool = False
    trial_clickable: bool = False

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "LocatorCandidate":
        return cls(
            strategy=str(raw.get("strategy", "")).lower().strip(),
            value=str(raw.get("value", "")).strip(),
            unique=raw.get("unique") is True,
            visible=raw.get("visible") is True,
            enabled=raw.get("enabled") is True,
            covers_click_point=raw.get("covers_click_point") is True,
            trial_clickable=raw.get("trial_clickable") is True,
        )

    def as_recorder_candidate(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "value": self.value,
            "unique": True,
            "recovered_by": "ai",
        }


@dataclass(frozen=True)
class RecoveryDecision:
    candidate: LocatorCandidate | None
    reason: str | None = None


CandidateScorer = Callable[[tuple[LocatorCandidate, ...]], Iterable[LocatorCandidate]]


def fragile_reason(candidate: LocatorCandidate) -> str | None:
    """Return the specific policy failure without attempting a browser action."""
    if candidate.strategy not in SUPPORTED_STRATEGIES:
        return "AI recovery only supports CSS or XPath locators"
    if not candidate.value or len(candidate.value) > 1024 or "\n" in candidate.value:
        return "AI locator is empty or malformed"
    if any(pattern.search(candidate.value) for pattern in _FRAGILE_PATTERNS):
        return "AI locator uses fragile generated or structural attributes"
    return None


def validation_reason(candidate: LocatorCandidate) -> str | None:
    """Require current-page proof, never merely an AI assertion."""
    checks = (
        (candidate.unique, "AI locator is not unique"),
        (candidate.visible, "AI locator is not visible"),
        (candidate.enabled, "AI locator is not enabled"),
        (candidate.covers_click_point, "AI locator does not cover the recorded click point"),
        (candidate.trial_clickable, "AI locator is not trial-clickable"),
    )
    return next((message for passed, message in checks if not passed), None)


def choose_recovered_locator(
    candidates: Iterable[LocatorCandidate | Mapping[str, object]],
    *,
    score: CandidateScorer | None = None,
) -> RecoveryDecision:
    """Return the first compliant candidate after optional AI ordering.

    `score` may only reorder/filter the browser-observed candidates. It cannot
    manufacture validation facts, which prevents an AI response from bypassing
    uniqueness, click-point, or trial-click checks.
    """
    normalized = tuple(
        item if isinstance(item, LocatorCandidate) else LocatorCandidate.from_mapping(item)
        for item in candidates
    )
    ordered = tuple(score(normalized)) if score else normalized
    if not ordered:
        return RecoveryDecision(None, "AI recovery produced no locator candidate")
    reasons: list[str] = []
    for candidate in ordered:
        reason = fragile_reason(candidate) or validation_reason(candidate)
        if reason is None:
            return RecoveryDecision(candidate)
        reasons.append(reason)
    return RecoveryDecision(None, reasons[0])
