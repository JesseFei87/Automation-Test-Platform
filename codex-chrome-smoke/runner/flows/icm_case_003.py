from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from runner.browser import capture_case_screenshot, ensure_text_visible, open_device_list
from runner.flows.icm_common import prepare_session


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    inputs = case.get("automation_asset", {}).get("input_values", {})
    keyword = inputs.get("device_keyword", "AU5800")
    await prepare_session(page, system)
    await open_device_list(page, system)
    await capture_case_screenshot(page, "step-01.png")
    query_input = page.locator("input[placeholder]").first
    await query_input.wait_for(state="visible", timeout=20000)
    await capture_case_screenshot(page, "step-02.png")
    await query_input.fill(keyword)
    await capture_case_screenshot(page, "step-03.png")
    await page.keyboard.press("Enter")
    await ensure_text_visible(page, keyword)
    await capture_case_screenshot(page, "step-04.png")
