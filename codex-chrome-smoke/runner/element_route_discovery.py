"""Bounded route discovery for element-library refreshes.

Routes enter the queue only when they are present in the current browser
observation.  The optional Agent is limited to revealing navigation controls;
it cannot fill, submit, delete, or navigate to an invented URL.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from runner.agent_explore import decide_next_action, execute_agent_decision, observe_page, run_agent_loop

_DANGEROUS_TERMS = (
    "delete", "remove", "logout", "restart", "shutdown", "pay", "submit",
    chr(0x5220) + chr(0x9664), chr(0x79FB) + chr(0x9664), chr(0x9000) + chr(0x51FA),
    chr(0x91CD) + chr(0x542F), chr(0x5173) + chr(0x95ED), chr(0x652F) + chr(0x4ED8), chr(0x63D0) + chr(0x4EA4),
)
_AGENT_STEPS_PER_PAGE = 3


def _emit(callback: Callable[[dict[str, Any]], None] | None, stage: str, **data: Any) -> None:
    if callback:
        callback({"stage": stage, **data})


def _route_target(url: str, base_url: str, name: str = "") -> dict[str, str] | None:
    parsed = urlparse(url)
    base = urlparse(base_url)
    route = f"#{parsed.fragment}" if parsed.fragment else parsed.path
    normalized = route.lstrip("#/").strip("/")
    if not normalized or "login" in normalized.lower() or "logout" in normalized.lower():
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if base.netloc and parsed.netloc != base.netloc:
        return None
    page_id = normalized.replace("/", "_").replace("-", "_").replace("?", "_").replace("=", "_")
    return {"page_id": page_id, "name": name.strip() or page_id.replace("_", " ").title(), "route": route, "url": url}


def _href_from_selector(selector: str) -> str:
    prefix = 'a[href="'
    if not selector.startswith(prefix):
        return ""
    return selector[len(prefix):].split('"', 1)[0]


def _observed_route_url(value: str, observation_url: str, base_url: str) -> str:
    route = value.strip()
    if not route or route.startswith(("javascript:", "mailto:", "tel:")):
        return ""
    if route.startswith("#/"):
        return urljoin(observation_url or base_url, route)
    if route.startswith("/#/"):
        return urljoin(base_url, route)
    if route.startswith(("http://", "https://", "/")):
        return urljoin(observation_url or base_url, route)
    return ""


def _safe_navigation_target(observation: dict[str, Any], ref: str) -> bool:
    target = next((item for item in observation.get("interactives") or [] if item.get("ref") == ref), {})
    text = " ".join(str(target.get(key) or "") for key in ("text", "ariaLabel", "selector", "href")).lower()
    if any(term.lower() in text for term in _DANGEROUS_TERMS):
        return False
    href = str(target.get("href") or _href_from_selector(str(target.get("selector") or ""))).strip()
    return bool(href) or str(target.get("tag") or "") == "a" or str(target.get("role") or "") in {"link", "menuitem"} or "el-menu" in str(target.get("selector") or "")


def _navigation_candidates(observation: dict[str, Any], base_url: str) -> list[dict[str, str]]:
    return [assessment["target"] for assessment in _assess_navigation_candidates(observation, base_url) if assessment.get("target")]


def _assess_navigation_candidates(observation: dict[str, Any], base_url: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    sources = observation.get("navigationLinks") or observation.get("interactives") or []
    for item in sources:
        href = str(item.get("href") or _href_from_selector(str(item.get("selector") or ""))).strip()
        candidate_url = _observed_route_url(href, str(observation.get("url") or ""), base_url)
        assessment: dict[str, Any] = {"href": href, "text": str(item.get("text") or item.get("ariaLabel") or "").strip()}
        if not candidate_url:
            assessment["reason"] = "unsupported_route_value"
            candidates.append(assessment)
            continue
        text = " ".join(str(item.get(key) or "") for key in ("text", "ariaLabel", "href")).lower()
        if any(term.lower() in text for term in _DANGEROUS_TERMS):
            assessment["reason"] = "dangerous_navigation_label"
            candidates.append(assessment)
            continue
        target = _route_target(candidate_url, base_url, str(item.get("text") or item.get("ariaLabel") or ""))
        if target:
            assessment["target"] = target
        else:
            assessment["reason"] = "out_of_scope_or_login_route"
        candidates.append(assessment)
    return candidates


def _record_agent_history(
    history: list[dict[str, Any]],
    *,
    route_url: str,
    progress_callback: Callable[[dict[str, Any]], None] | None,
) -> int:
    action_count = 0
    for entry in history:
        decision = entry.get("decision") or {}
        execution = entry.get("execution") or {}
        action = str(decision.get("action") or "")
        if action not in {"finish", "fail"}:
            action_count += 1
        _emit(
            progress_callback,
            "route_agent_decision",
            route_url=route_url,
            step=entry.get("step"),
            action=action,
            ref=decision.get("ref") or "",
            reason=decision.get("reason") or "",
            result=execution.get("result") or execution.get("error") or "",
        )
    return action_count


async def discover_routes(
    page: Any,
    *,
    base_url: str,
    max_actions: int = 24,
    max_pages: int = 20,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, str]]:
    """Breadth-first discover same-origin routes from observed navigation links."""
    initial_url = str(getattr(page, "url", "") or base_url)
    queue: deque[str] = deque([initial_url])
    queued = {initial_url}
    visited: set[str] = set()
    discovered: dict[str, dict[str, str]] = {}
    action_count = 0
    agent_failures = 0
    agent_budget_exhaustions = 0
    emitted_candidates: set[tuple[str, str, str]] = set()

    def add_observation(observation: dict[str, Any]) -> None:
        target = _route_target(str(observation.get("url") or ""), base_url)
        if target and target["url"] not in discovered and len(discovered) < max_pages:
            discovered[target["url"]] = target
            _emit(progress_callback, "route_discovered", page_id=target["page_id"], url=target["url"], discovered_page_count=len(discovered))
        for assessment in _assess_navigation_candidates(observation, base_url):
            candidate = assessment.get("target")
            candidate_url = str((candidate or {}).get("url") or "")
            candidate_key = (str(observation.get("url") or ""), str(assessment.get("href") or ""), candidate_url)
            if candidate_key not in emitted_candidates:
                emitted_candidates.add(candidate_key)
                _emit(
                    progress_callback,
                    "route_candidate_observed",
                    observed_url=str(observation.get("url") or ""),
                    href=str(assessment.get("href") or ""),
                    text=str(assessment.get("text") or ""),
                    candidate_url=candidate_url,
                    decision="eligible" if candidate else "rejected",
                    reason=str(assessment.get("reason") or ""),
                )
            if not candidate:
                continue
            if candidate["url"] in queued or candidate["url"] in visited or len(queued) + len(visited) >= max_pages:
                reason = "already_queued" if candidate["url"] in queued else "already_visited" if candidate["url"] in visited else "page_limit_reached"
                _emit(progress_callback, "route_queue_skipped", page_id=candidate["page_id"], url=candidate["url"], reason=reason)
                continue
            queue.append(candidate["url"])
            queued.add(candidate["url"])
            _emit(progress_callback, "route_queue_enqueued", page_id=candidate["page_id"], url=candidate["url"], queue_size=len(queue))

    while queue and len(visited) < max_pages:
        route_url = queue.popleft()
        queued.discard(route_url)
        if route_url in visited:
            continue
        visited.add(route_url)
        _emit(progress_callback, "route_queue_dequeued", url=route_url, visited_route_count=len(visited), queue_size=len(queue))
        if str(getattr(page, "url", "")) != route_url:
            await page.goto(route_url, wait_until="domcontentloaded", timeout=8000)

        observation = await observe_page(page)
        add_observation(observation)

        remaining_actions = max_actions - action_count
        if remaining_actions > 0:
            async def execute(decision, current_observation: dict[str, Any]) -> dict[str, Any]:
                if decision.action in {"finish", "wait", "scroll"}:
                    execution = await execute_agent_decision(page, decision, current_observation)
                    add_observation(await observe_page(page))
                    return execution
                if decision.action not in {"click", "hover"} or not _safe_navigation_target(current_observation, decision.ref):
                    return {"result": "error", "error": "route discovery only permits observed safe navigation actions"}
                execution = await execute_agent_decision(page, decision, current_observation)
                add_observation(await observe_page(page))
                return execution

            goal = (
                "Reveal additional visible application navigation for route discovery. "
                "Only hover or click current navigation links, menu items, or submenu triggers. "
                "Never fill forms, submit, delete, logout, change data, or use a URL. "
                "Finish after revealing available navigation."
            )
            result = await run_agent_loop(
                goal,
                lambda: observe_page(page),
                decide_next_action,
                execute,
                {urlparse(base_url).hostname or ""},
                max_steps=min(_AGENT_STEPS_PER_PAGE, remaining_actions),
            )
            action_count += _record_agent_history(result.get("history") or [], route_url=route_url, progress_callback=progress_callback)
            error = str(result.get("error") or "")
            if result.get("ok"):
                _emit(progress_callback, "route_agent_finished", route_url=route_url, summary=result.get("summary") or "")
            elif error.startswith("Agent reached max steps"):
                agent_budget_exhaustions += 1
                _emit(progress_callback, "route_agent_budget_exhausted", route_url=route_url, action_budget=max_actions, message=error)
            else:
                agent_failures += 1
                _emit(progress_callback, "route_agent_failed", route_url=route_url, error=error or "unknown agent failure")
            add_observation(await observe_page(page))

    _emit(
        progress_callback,
        "route_discovery_completed",
        discovered_page_count=len(discovered),
        visited_route_count=len(visited),
        route_action_count=action_count,
        agent_failure_count=agent_failures,
        agent_budget_exhaustion_count=agent_budget_exhaustions,
        queued_route_count=len(queue),
    )
    return list(discovered.values())
