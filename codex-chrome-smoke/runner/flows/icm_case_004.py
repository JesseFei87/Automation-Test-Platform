from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from runner.browser import open_device_list
from runner.flows.icm_common import prepare_session


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    await prepare_session(page, system)
    await open_device_list(page, system)
    row = page.locator("tbody tr").filter(has_text="AU5800").first
    await row.wait_for(timeout=20000)
    button = row.locator("button").first
    await button.click(force=True)
    await page.get_by_text("修改设备信息", exact=False).first.wait_for(timeout=20000)
