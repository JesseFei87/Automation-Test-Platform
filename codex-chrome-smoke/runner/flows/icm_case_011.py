from __future__ import annotations

import time
from typing import Any

from playwright.async_api import Page

from runner.browser import (
    capture_case_screenshot,
    click_first,
    click_row_action,
    click_row_action_if_present,
    ensure_text_visible,
    fill_first_in,
    open_device_list,
    open_server_list,
    open_user_management,
)
from runner.flows.icm_common import prepare_session, search_by_keyword, settle, wait_for_visible_dialog


async def _confirm_delete(page: Page) -> None:
    confirm = page.locator(".el-message-box__btns button").filter(has_text="\u786e\u5b9a")
    if await confirm.count():
        await confirm.first.click(force=True)
        return
    await click_first(page, ["button:has-text(\u786e\u5b9a)", "button:has-text(\u786e\u8ba4)"])


async def _wait_for_row_gone(page: Page, row_text: str, timeout_ms: int = 8000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            if await page.locator("tr").filter(has_text=row_text).count() == 0:
                return
        except Exception:
            return
        await settle(page, 250)
    raise RuntimeError(f"Row still visible after delete: {row_text}")


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    values = case.get("automation_asset", {}).get("input_values", {})
    tester = values.get("tester_user", "Tester")
    device_name = values.get("device_name", "Test_Ins01")
    server_name = values.get("server_name", "Test Server#203")

    await prepare_session(page, system)

    await open_user_management(page, system)
    await settle(page, 1500)
    if await click_row_action_if_present(page, tester, ["\u5220\u9664", "Delete"]):
        await _confirm_delete(page)
        await settle(page, 1200)
        await _wait_for_row_gone(page, tester)

    await open_device_list(page, system)
    await settle(page, 1500)
    await search_by_keyword(
        page,
        [
            'css=input[placeholder="\u8f93\u5165\u8bbe\u5907\u540d\u79f0"]',
            'css=input[placeholder="\u8bf7\u8f93\u5165\u8bbe\u5907\u540d\u79f0"]',
        ],
        device_name,
        settle_ms=1500,
    )
    await capture_case_screenshot(page, "02-action.png")
    if await click_row_action_if_present(page, device_name, ["\u5220\u9664", "Delete"]):
        await _confirm_delete(page)
        await settle(page, 1200)
        await _wait_for_row_gone(page, device_name)

    await open_server_list(page, system)
    await settle(page, 1500)
    await click_row_action(page, server_name, ["\u4fee\u6539", "Edit"])
    dialog = await wait_for_visible_dialog(page)
    await fill_first_in(
        dialog,
        ["placeholder=device name", "placeholder=\u8bf7\u8f93\u5165\u8bbe\u5907\u540d\u79f0", "css=.el-dialog .el-input__inner"],
        device_name,
    )
    await settle(page, 800)
    await ensure_text_visible(page, server_name)
