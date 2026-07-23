from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from runner.browser import capture_case_screenshot, open_homepage, wait_for_url_contains
from runner.flows.icm_common import prepare_session


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    await prepare_session(page, system)
    await open_homepage(page, system)
    await capture_case_screenshot(page, "step-01.png")
    await page.wait_for_load_state("domcontentloaded")
    await capture_case_screenshot(page, "step-02.png")
    await wait_for_url_contains(page, "#/index")
    await capture_case_screenshot(page, "step-03.png")
