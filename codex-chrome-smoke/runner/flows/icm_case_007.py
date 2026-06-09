from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from runner.browser import capture_case_screenshot, ensure_text_visible, open_server_list
from runner.flows.icm_common import click_dialog_primary, prepare_session, settle, wait_for_table_row, wait_for_visible_dialog


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    values = case.get("automation_asset", {}).get("input_values", {})
    server_name = values.get("server_name", "Test Server#203")
    device_name = values.get("device_name", "Test_Ins01")

    await prepare_session(page, system)
    await open_server_list(page, system)
    await settle(page, 1500)

    row = await wait_for_table_row(page, server_name)
    await row.locator("button").nth(0).click(force=True)

    dialog = await wait_for_visible_dialog(page)
    inputs = dialog.locator("input:visible")
    await inputs.nth(6).fill(device_name)
    await settle(page, 1200)

    device_row = dialog.locator("tbody tr").filter(has_text=device_name).first
    await device_row.wait_for(state="visible", timeout=20000)
    await device_row.locator(".el-checkbox__inner").first.click(force=True)
    await capture_case_screenshot(page, "02-action.png")

    await click_dialog_primary(page)
    await settle(page, 1200)
    await ensure_text_visible(page, device_name)
