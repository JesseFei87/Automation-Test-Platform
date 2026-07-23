import asyncio

from runner import element_retry_strategy


def test_healing_issue_for_target_prefers_target_metadata():
    assert element_retry_strategy.healing_issue_for_target({"healing_issue": "target_not_visible"}, "timeout") == "target_not_visible"
    assert element_retry_strategy.healing_issue_for_target(
        {"self_healing": {"primary_issue": "covered_by_overlay"}}, "timeout"
    ) == "covered_by_overlay"


def test_healing_issue_for_target_falls_back_to_error_classification():
    assert element_retry_strategy.healing_issue_for_target({}, "Agent target is not visible") == "target_not_visible"


def test_should_retry_only_safe_supported_actions():
    assert element_retry_strategy.should_retry("target_not_visible", "click") is True
    assert element_retry_strategy.should_retry("unknown_ref", "click") is False
    assert element_retry_strategy.should_retry("target_not_visible", "goto") is False


def test_apply_retry_preparation_scrolls_locator_for_not_visible():
    class Locator:
        def __init__(self):
            self.scrolled = False

        async def scroll_into_view_if_needed(self, timeout):
            self.scrolled = timeout == 5000

    class Page:
        def __init__(self):
            self.waits = []

        async def wait_for_timeout(self, ms):
            self.waits.append(ms)

    page = Page()
    locator = Locator()

    steps = asyncio.run(element_retry_strategy.apply_retry_preparation(page, "target_not_visible", locator))

    assert steps == ["scroll_into_view", "wait_after_scroll"]
    assert locator.scrolled is True
    assert page.waits == [200]


def test_apply_retry_preparation_dismisses_overlay():
    class Keyboard:
        def __init__(self):
            self.pressed = []

        async def press(self, key):
            self.pressed.append(key)

    class Page:
        def __init__(self):
            self.keyboard = Keyboard()
            self.waits = []

        async def wait_for_timeout(self, ms):
            self.waits.append(ms)

    page = Page()

    steps = asyncio.run(element_retry_strategy.apply_retry_preparation(page, "covered_by_overlay"))

    assert steps == ["dismiss_overlay_escape", "wait_after_overlay_dismiss"]
    assert page.keyboard.pressed == ["Escape"]
    assert page.waits == [200]


def test_retry_once_with_healing_runs_operation_after_preparation():
    class Locator:
        def __init__(self):
            self.scrolled = False

        async def scroll_into_view_if_needed(self, timeout):
            self.scrolled = True

    class Page:
        async def wait_for_timeout(self, ms):
            pass

    calls = []

    async def operation():
        calls.append("retried")

    retried, steps = asyncio.run(
        element_retry_strategy.retry_once_with_healing(
            page=Page(),
            action="click",
            target={"healing_issue": "target_not_visible"},
            locator=Locator(),
            error=RuntimeError("first failure"),
            operation=operation,
        )
    )

    assert retried is True
    assert steps == ["scroll_into_view", "wait_after_scroll"]
    assert calls == ["retried"]
