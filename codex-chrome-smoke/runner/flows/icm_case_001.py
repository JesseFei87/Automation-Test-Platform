from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from runner.browser import (
    capture_case_screenshot,
    open_login_page,
    perform_login,
    wait_for_login_page,
    wait_for_url_contains,
)


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    await open_login_page(page, system)
    await capture_case_screenshot(page, "step-01.png")
    await wait_for_login_page(page, system)
    await capture_case_screenshot(page, "step-02.png")

    async def capture_login_checkpoint(checkpoint: str) -> None:
        if checkpoint == "password_filled":
            await capture_case_screenshot(page, "step-03.png")

    await perform_login(page, system, checkpoint=capture_login_checkpoint)
    await wait_for_url_contains(page, "#/index")
    await capture_case_screenshot(page, "step-04.png")
