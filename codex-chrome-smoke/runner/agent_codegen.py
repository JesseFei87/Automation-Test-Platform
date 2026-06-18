from __future__ import annotations

from collections.abc import Callable


def _quote(value: object) -> str:
    return repr(str(value or ""))


def _goto(decision: dict, execution: dict) -> str | None:
    url = decision.get("url")
    return f"    await page.goto({_quote(url)}, wait_until='domcontentloaded')" if url else None


def _fill(decision: dict, execution: dict) -> str | None:
    selector = execution.get("selector")
    return (
        f"    await fill_first(page, [{_quote(selector)}], {_quote(decision.get('value'))})"
        if selector
        else None
    )


def _click(decision: dict, execution: dict) -> str | None:
    selector = execution.get("selector")
    return f"    await click_first(page, [{_quote(selector)}])" if selector else None


def _press(decision: dict, execution: dict) -> str | None:
    selector = execution.get("selector")
    key = decision.get("key") or execution.get("key") or "Enter"
    return f"    await page.locator({_quote(selector)}).first.press({_quote(key)})" if selector else None


def _wait(decision: dict, execution: dict) -> str | None:
    return "    await page.wait_for_timeout(1200)"


def _scroll(decision: dict, execution: dict) -> str | None:
    value = str(decision.get("value") or 650)
    return f"    await page.mouse.wheel(0, {int(value) if value.isdigit() else 650})"


def _assert_text(decision: dict, execution: dict) -> str | None:
    value = decision.get("value")
    return f"    await ensure_text_visible(page, {_quote(value)})" if value else None


_EMITTERS: dict[str, Callable[[dict, dict], str | None]] = {
    "goto": _goto,
    "fill": _fill,
    "click": _click,
    "press": _press,
    "wait": _wait,
    "scroll": _scroll,
    "assert_text": _assert_text,
}


def generate_candidate_flow(trace: dict) -> str:
    lines = [
        "from __future__ import annotations",
        "",
        "from runner.browser import click_first, ensure_text_visible, fill_first, goto_route",
        "",
        "",
        "async def run(page, system, case) -> None:",
        "    # Generated from successful Agent exploration. Review before registration.",
    ]
    generated = [
        line
        for item in trace.get("history") or []
        for decision in [item.get("decision") or {}]
        for emitter in [_EMITTERS.get(decision.get("action"))]
        for line in [emitter(decision, item.get("execution") or {}) if emitter else None]
        if line
    ]
    lines.extend(generated or ["    raise RuntimeError('Agent trace did not contain executable actions')"])
    return "\n".join(lines) + "\n"
