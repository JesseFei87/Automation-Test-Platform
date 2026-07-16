"""Retry strategy helpers for advisory self-healing hints.

P7 scope: convert healing issues into safe, bounded retry actions.  Strategies
are intentionally conservative: they do not create new selectors, do not bypass
current observation refs, and perform at most one retry per failed action.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from runner.element_self_healing import classify_error


RetryCallable = Callable[[], Awaitable[None]]

_RETRYABLE_ISSUES = {
    "target_not_visible",
    "covered_by_overlay",
    "timeout",
    "stale_element",
    "needs_hover",
}


def healing_issue_for_target(target: dict[str, Any] | None, error: str | None = None) -> str:
    if target:
        issue = str(target.get("healing_issue") or "")
        if not issue and isinstance(target.get("self_healing"), dict):
            issue = str(target["self_healing"].get("primary_issue") or "")
        if issue:
            return issue
    return classify_error(error)


def should_retry(issue: str, action: str) -> bool:
    if issue not in _RETRYABLE_ISSUES:
        return False
    if action not in {"click", "fill", "hover", "press"}:
        return False
    return True


async def apply_retry_preparation(page: Any, issue: str, locator: Any | None = None, *, action: str = "") -> list[str]:
    """Apply safe pre-retry actions and return a list of performed step names."""
    steps: list[str] = []
    if issue == "target_not_visible":
        if locator is not None and hasattr(locator, "scroll_into_view_if_needed"):
            await locator.scroll_into_view_if_needed(timeout=5000)
            steps.append("scroll_into_view")
        elif hasattr(page, "mouse") and hasattr(page.mouse, "wheel"):
            await page.mouse.wheel(0, 650)
            steps.append("scroll_page")
        if hasattr(page, "wait_for_timeout"):
            await page.wait_for_timeout(200)
            steps.append("wait_after_scroll")
        return steps

    if issue == "covered_by_overlay":
        keyboard = getattr(page, "keyboard", None)
        if keyboard is not None and hasattr(keyboard, "press"):
            await keyboard.press("Escape")
            steps.append("dismiss_overlay_escape")
        if hasattr(page, "wait_for_timeout"):
            await page.wait_for_timeout(200)
            steps.append("wait_after_overlay_dismiss")
        return steps

    if issue == "timeout":
        if hasattr(page, "wait_for_timeout"):
            await page.wait_for_timeout(800)
            steps.append("wait_for_settle")
        return steps

    if issue == "stale_element":
        if hasattr(page, "wait_for_timeout"):
            await page.wait_for_timeout(300)
            steps.append("wait_for_dom_refresh")
        return steps

    if issue == "needs_hover":
        if locator is not None and hasattr(locator, "hover") and action != "hover":
            await locator.hover(timeout=5000)
            steps.append("hover_before_retry")
        if hasattr(page, "wait_for_timeout"):
            await page.wait_for_timeout(200)
            steps.append("wait_after_hover")
        return steps

    return steps


async def retry_once_with_healing(
    *,
    page: Any,
    action: str,
    target: dict[str, Any] | None,
    locator: Any | None,
    error: Exception,
    operation: RetryCallable,
) -> tuple[bool, list[str]]:
    """Prepare and retry once when healing metadata or error category allows it."""
    issue = healing_issue_for_target(target, str(error))
    if not should_retry(issue, action):
        return False, []
    steps = await apply_retry_preparation(page, issue, locator, action=action)
    if not steps:
        return False, []
    await operation()
    return True, steps
