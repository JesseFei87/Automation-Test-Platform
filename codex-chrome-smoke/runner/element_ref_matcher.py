"""Bind shared element-library candidates to current observation refs.

P4 scope: keep element-library knowledge advisory-only, but enrich it with
recommended current-page refs when a library element clearly matches one of
``observation.interactives``.  The Agent still must execute via the current ref;
no historical selector is executed directly.
"""
from __future__ import annotations

import re
from typing import Any

from runner.element_knowledge import rank_for_intent
from runner.element_self_healing import format_healing_hint


def _tokens(text: str) -> set[str]:
    lowered = (text or "").lower()
    return {item for item in re.split(r"[\s,;:_/.\-()\[\]【】、，；。'\"]+", lowered) if item}


def _as_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _candidate_text(element: dict[str, Any]) -> str:
    state_labels = [
        label
        for coverage in (element.get("state_coverage") or {}).values()
        if isinstance(coverage, dict)
        for label in coverage.get("labels") or []
    ]
    return " ".join(
        [
            _as_text(element.get("element_id")),
            _as_text(element.get("name")),
            _as_text(element.get("human_en")),
            _as_text(element.get("human_zh")),
            _as_text(element.get("business_desc")),
            _as_text(element.get("text")),
            _as_text(element.get("placeholder")),
            _as_text(element.get("ariaLabel")),
            _as_text(element.get("context_keys")),
            _as_text(element.get("selectors")),
            _as_text([variant.get("value") for variant in element.get("locator_variants") or []]),
            _as_text(state_labels),
        ]
    ).lower()


def _interactive_text(item: dict[str, Any]) -> str:
    return " ".join(
        [
            _as_text(item.get("ref")),
            _as_text(item.get("tag")),
            _as_text(item.get("role")),
            _as_text(item.get("type")),
            _as_text(item.get("text")),
            _as_text(item.get("ariaLabel")),
            _as_text(item.get("placeholder")),
            _as_text(item.get("name")),
            _as_text(item.get("testId")),
            _as_text(item.get("selector")),
        ]
    ).lower()


_STABILITY_SCORE = {"high": 32.0, "medium": 20.0, "low": 6.0, "legacy": 30.0}


def _locator_variants(element: dict[str, Any]) -> list[dict[str, Any]]:
    variants = [item for item in element.get("locator_variants") or [] if isinstance(item, dict)]
    if variants:
        return variants
    return [
        {"kind": "css", "value": str(selector or ""), "stability": "legacy"}
        for selector in element.get("selectors") or []
        if str(selector or "").strip()
    ]


def _variant_matches(variant: dict[str, Any], interactive: dict[str, Any]) -> bool:
    kind = str(variant.get("kind") or "").lower()
    value = str(variant.get("value") or "").strip().lower()
    if not value:
        return False
    if kind == "testid":
        return value == str(interactive.get("testId") or "").strip().lower()
    if kind == "role_name":
        role = str(variant.get("role") or "").strip().lower()
        current_name = str(interactive.get("ariaLabel") or interactive.get("text") or "").strip().lower()
        return bool(role and role == str(interactive.get("role") or "").strip().lower() and value == current_name)
    fields = {
        "aria_label": "ariaLabel",
        "name": "name",
        "placeholder": "placeholder",
        "text": "text",
    }
    if kind in fields:
        return value == str(interactive.get(fields[kind]) or "").strip().lower()
    if kind == "css":
        selector = str(interactive.get("selector") or "").strip().lower()
        return bool(selector and (selector == value or selector in value or value in selector))
    return False


def match_element_to_interactive(element: dict[str, Any], interactive: dict[str, Any]) -> float:
    """Return a deterministic match score between a library element and current ref."""
    score = 0.0
    for variant in _locator_variants(element):
        if _variant_matches(variant, interactive):
            score += _STABILITY_SCORE.get(str(variant.get("stability") or "").lower(), 6.0)

    for field in ("text", "placeholder", "ariaLabel"):
        left = str(element.get(field) or "").strip().lower()
        right = str(interactive.get(field) or "").strip().lower()
        if left and right and left == right:
            score += 10.0
        elif left and right and (left in right or right in left):
            score += 5.0

    if str(element.get("tag") or "").lower() and str(element.get("tag") or "").lower() == str(interactive.get("tag") or "").lower():
        score += 2.0
    if str(element.get("role") or "").lower() and str(element.get("role") or "").lower() == str(interactive.get("role") or "").lower():
        score += 2.0
    if str(element.get("type") or "").lower() and str(element.get("type") or "").lower() == str(interactive.get("type") or "").lower():
        score += 2.0

    element_tokens = _tokens(_candidate_text(element))
    interactive_tokens = _tokens(_interactive_text(interactive))
    score += min(len(element_tokens & interactive_tokens), 8) * 1.5
    return score


def bind_candidate_refs(candidates: list[dict[str, Any]], observation: dict[str, Any], *, min_score: float = 8.0) -> list[dict[str, Any]]:
    """Attach best current observation ref to each candidate when confidently matched."""
    interactives = observation.get("interactives") or []
    bound: list[dict[str, Any]] = []
    used_refs: set[str] = set()
    for candidate in candidates:
        best_item: dict[str, Any] | None = None
        best_score = 0.0
        for interactive in interactives:
            ref = str(interactive.get("ref") or "")
            score = match_element_to_interactive(candidate, interactive)
            if ref in used_refs and score < 30.0:
                score -= 5.0
            if score > best_score:
                best_score = score
                best_item = interactive
        copied = dict(candidate)
        if best_item and best_score >= min_score:
            ref = str(best_item.get("ref") or "")
            copied["matched_ref"] = ref
            copied["matched_ref_score"] = round(best_score, 2)
            copied["matched_ref_text"] = str(best_item.get("text") or best_item.get("placeholder") or best_item.get("ariaLabel") or "")
            copied["matched_ref_selector"] = str(best_item.get("selector") or "")
            if ref:
                used_refs.add(ref)
        bound.append(copied)
    return bound


def _supports_action(interactive: dict[str, Any], action: str) -> bool:
    if interactive.get("disabled"):
        return False
    if action != "fill":
        return True
    return str(interactive.get("tag") or "").lower() in {"input", "textarea"} or bool(interactive.get("contenteditable"))


def resolve_recovery_ref(
    intent: str,
    route: str,
    observation: dict[str, Any],
    action: str,
    *,
    top_k: int = 6,
    min_score: float = 16.0,
    ambiguity_gap: float = 3.0,
) -> dict[str, Any]:
    """Resolve one safe current ref for a failed pre-action locator attempt."""
    candidates = rank_for_intent(intent, route, top_k=top_k, include_needs_review=True)
    matches: dict[str, dict[str, Any]] = {}
    for candidate_index, element in enumerate(candidates):
        for interactive in observation.get("interactives") or []:
            ref = str(interactive.get("ref") or "")
            if not ref or not _supports_action(interactive, action):
                continue
            score = match_element_to_interactive(element, interactive)
            if score < min_score:
                continue
            current = matches.get(ref)
            if current and current["score"] >= score:
                continue
            matches[ref] = {
                "status": "resolved",
                "ref": ref,
                "score": round(score, 2),
                "element_id": str(element.get("element_id") or ""),
                "element_name": str(element.get("name") or ""),
                "matched_text": str(interactive.get("text") or interactive.get("placeholder") or interactive.get("ariaLabel") or ""),
                "candidate_rank": candidate_index + 1,
            }
    ranked = sorted(matches.values(), key=lambda item: (-item["score"], item["candidate_rank"], item["ref"]))
    if not ranked:
        return {"status": "no_confident_candidate"}
    if len(ranked) > 1 and ranked[0]["score"] - ranked[1]["score"] < ambiguity_gap:
        return {
            "status": "ambiguous",
            "score": ranked[0]["score"],
            "alternate_score": ranked[1]["score"],
        }
    return ranked[0]


def format_agent_ref_guidance(intent: str, route: str, observation: dict[str, Any], *, top_k: int = 6) -> str:
    """Format only current-ref guidance for the Agent prompt."""
    candidates = rank_for_intent(intent, route, top_k=top_k)
    if not candidates:
        return ""
    rows = bind_candidate_refs(candidates, observation)
    lines = ["Candidate elements (from shared library, matched to current observation refs when possible):"]
    for element in rows:
        ref = str(element.get("matched_ref") or "")
        if not ref:
            continue
        label = str(element.get("matched_ref_text") or element.get("name") or "-")
        lines.append(
            f"- recommended current ref: `{ref}` (score: {element.get('matched_ref_score')}; "
            f"label: {label}; validation: {element.get('validation_status') or 'unknown'})"
        )
    if len(lines) == 1:
        return ""
    lines.append("Use recommended refs only if they appear in current observation.interactives; never use library selectors directly.")
    return "\n".join(lines)


def build_agent_ref_evidence(
    intent: str,
    route: str,
    observation: dict[str, Any],
    selected_ref: str = "",
    *,
    top_k: int = 6,
) -> dict[str, Any]:
    """Describe which library candidates matched current refs and whether one was used."""
    rows = bind_candidate_refs(rank_for_intent(intent, route, top_k=top_k, include_needs_review=True), observation)
    candidates = [
        {
            "element_id": str(element.get("element_id") or ""),
            "element_name": str(element.get("name") or ""),
            "recommended_ref": str(element.get("matched_ref") or ""),
            "label": str(element.get("matched_ref_text") or element.get("name") or ""),
            "score": element.get("matched_ref_score"),
            "validation_status": str(element.get("validation_status") or "unknown"),
        }
        for element in rows
        if element.get("matched_ref")
    ]
    adopted = next((item for item in candidates if item["recommended_ref"] == selected_ref), None)
    applicable = bool(selected_ref)
    return {
        "matched": bool(candidates),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "selected_ref": selected_ref,
        "adopted": adopted is not None,
        "adopted_element_id": adopted["element_id"] if adopted else "",
        "applicable": applicable,
        "adoption_reason": (
            "selected_ref_matches_candidate"
            if adopted
            else "selected_ref_differs_from_candidates"
            if applicable and candidates
            else "no_bound_candidate"
            if applicable
            else "action_has_no_target"
        ),
    }


def format_bound_candidate_elements(intent: str, route: str, observation: dict[str, Any], *, top_k: int = 6) -> str:
    """Return a prompt snippet with element candidates and recommended current refs."""
    candidates = rank_for_intent(intent, route, top_k=top_k)
    if not candidates:
        return ""
    rows = bind_candidate_refs(candidates, observation)
    lines = ["Candidate elements (from shared library, matched to current observation refs when possible):"]
    for element in rows:
        zh = " / ".join(element.get("human_zh") or []) or "-"
        ctx = " · ".join(element.get("context_keys") or []) or "-"
        selectors = element.get("selectors") or []
        selector_preview = ", ".join(f"`{item}`" for item in selectors[:3])
        if len(selectors) > 3:
            selector_preview += f" …(+{len(selectors)-3})"
        ref_text = ""
        if element.get("matched_ref"):
            ref_text = f"; recommended current ref: `{element.get('matched_ref')}` (score: {element.get('matched_ref_score')})"
        feedback_bits = []
        if element.get("execution_count") is not None:
            feedback_bits.append(f"runs: {element.get('execution_count')}")
        if element.get("success_rate") is not None:
            feedback_bits.append(f"success: {element.get('success_rate')}")
        if element.get("last_error"):
            feedback_bits.append(f"last_error: {element.get('last_error')}")
        if element.get("validation_status"):
            feedback_bits.append(f"validation: {element.get('validation_status')}")
        feedback = f"; feedback: {', '.join(feedback_bits)}" if feedback_bits else ""
        healing_hint = format_healing_hint(element)
        healing = f"; {healing_hint}" if healing_hint else ""
        lines.append(
            f"- `{element.get('name','')}` ({element.get('human_en','')}; ZH: {zh}; ctx: {ctx}) "
            f"→ {selector_preview} (reuse: {element.get('coverage', 0)}{feedback}{healing}{ref_text})"
        )
    lines.append("Use recommended refs only if they appear in current observation.interactives; never use library selectors directly.")
    return "\n".join(lines)
