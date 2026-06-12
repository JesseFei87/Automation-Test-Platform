from __future__ import annotations

from typing import Any

from playwright.async_api import Locator, Page

from runner.browser import capture_case_screenshot, ensure_text_visible, open_device_list
from runner.flows.icm_common import click_dialog_primary, ensure_switch_enabled, prepare_session, search_by_keyword, settle, wait_for_visible_dialog


async def _choose_dropdown(page: Page, field: Locator, value: str) -> None:
    await field.click(force=True)
    await page.wait_for_timeout(300)
    visible_dropdown = page.locator(".el-select-dropdown:visible").last
    option = visible_dropdown.locator(".el-select-dropdown__item").filter(has_text=value).first
    await option.wait_for(state="visible", timeout=5000)
    await option.click(force=True)


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    values = case.get("automation_asset", {}).get("input_values", {})
    device_name = values.get("device_name", "Test_Ins01")
    connection_type = values.get("connection_type", "\u8fde\u63a5\u5668-1")
    device_type = values.get("device_type", "\u6807\u51c6\u8bbe\u5907")
    device_ip = values.get("device_ip", "192.168.16.11")
    device_port = values.get("device_port", "5900")
    vnc_password = values.get("vnc_password", "")
    allow_control = values.get("allow_control", "\u662f")
    device_enabled = values.get("device_enabled", True)

    await prepare_session(page, system)
    await open_device_list(page, system)
    await settle(page, 1200)

    await search_by_keyword(
        page,
        [
            'css=input[placeholder="\u8bf7\u8f93\u5165\u8bbe\u5907\u540d\u79f0"]',
            'css=input[placeholder="\u8f93\u5165\u8bbe\u5907\u540d\u79f0"]',
        ],
        device_name,
    )
    if await page.locator("tbody tr").filter(has_text=device_name).count():
        await ensure_text_visible(page, device_name)
        return

    await page.get_by_role("button", name="\u65b0\u589e").first.click(force=True)
    dialog = await wait_for_visible_dialog(page)
    inputs = dialog.locator("input")

    await _choose_dropdown(page, inputs.nth(0), connection_type)
    await _choose_dropdown(page, inputs.nth(1), device_type)
    await inputs.nth(2).fill(device_name)
    await inputs.nth(3).fill(device_ip)
    await inputs.nth(4).fill(device_port)
    await inputs.nth(8).fill(vnc_password)
    await _choose_dropdown(page, inputs.nth(9), allow_control)
    if device_enabled:
        await ensure_switch_enabled(page, dialog.locator(".el-switch").last)

    await capture_case_screenshot(page, "02-action.png")
    await click_dialog_primary(page)
    await settle(page, 1200)

    await search_by_keyword(
        page,
        [
            'css=input[placeholder="\u8bf7\u8f93\u5165\u8bbe\u5907\u540d\u79f0"]',
            'css=input[placeholder="\u8f93\u5165\u8bbe\u5907\u540d\u79f0"]',
        ],
        device_name,
        settle_ms=1200,
    )
    await ensure_text_visible(page, device_name)
