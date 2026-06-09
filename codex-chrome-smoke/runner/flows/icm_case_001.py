from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from runner.browser import open_login_page, perform_login, wait_for_login_page, wait_for_url_contains


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    await open_login_page(page, system)
    await wait_for_login_page(page, system)
    await perform_login(page, system)
    await wait_for_url_contains(page, "#/index")
