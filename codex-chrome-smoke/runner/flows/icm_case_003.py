from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from runner.browser import open_device_list, ensure_text_visible
from runner.flows.icm_common import prepare_session


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    inputs = case.get("automation_asset", {}).get("input_values", {})
    keyword = inputs.get("device_keyword", "AU5800")
    await prepare_session(page, system)
    await open_device_list(page, system)
    await page.locator("input[placeholder]").first.fill(keyword)
    await page.keyboard.press("Enter")
    await ensure_text_visible(page, keyword)
