from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from runner.browser import open_homepage, wait_for_url_contains
from runner.flows.icm_common import prepare_session


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    await prepare_session(page, system)
    await open_homepage(page, system)
    await wait_for_url_contains(page, "#/index")
