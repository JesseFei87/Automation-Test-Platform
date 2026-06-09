from __future__ import annotations

from typing import Any

from playwright.async_api import Locator, Page

from runner.browser import ensure_text_visible, open_user_management
from runner.flows.icm_common import click_dialog_primary, ensure_switch_enabled, prepare_session, settle, wait_for_table_row


async def _device_section(page: Page) -> Locator:
    heading = page.get_by_text("\u7ed1\u5b9a\u7684\u8bbe\u5907\u4fe1\u606f", exact=False).first
    return heading.locator("xpath=ancestor::div[1]")


async def _go_device_page(section: Locator, page_num: str, page: Page) -> None:
    pager = section.locator(".el-pager li.number").filter(has_text=page_num).first
    if await pager.count() == 0:
        return
    classes = await pager.get_attribute("class") or ""
    if "active" in classes:
        return
    await pager.click(force=True)
    await settle(page, 1200)


async def _select_device(page: Page, device_name: str) -> bool:
    section = await _device_section(page)
    await _go_device_page(section, "3", page)
    device_text = section.get_by_text(device_name, exact=False).first
    try:
        if await device_text.count() and await device_text.is_visible():
            device_row = device_text.locator("xpath=ancestor::tr[1]")
            await device_row.locator(".el-checkbox__inner").first.click(force=True)
            await settle(page, 800)
            await _go_device_page(section, "1", page)
            return True
    except Exception:
        return False
    return False


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    values = case.get("automation_asset", {}).get("input_values", {})
    tester = values.get("tester_user", "Tester")
    server_name = values.get("server_name", "Test Server#203")
    device_name = values.get("device_name", "Test_Ins01")

    await prepare_session(page, system)
    await open_user_management(page, system)
    await settle(page, 2000)

    tester_row = await wait_for_table_row(page, tester)
    await tester_row.locator("button").nth(2).click(force=True)
    await settle(page, 500)

    menu_item = page.locator(".el-dropdown-menu__item").filter(
        has_text="\u914d\u7f6e\u670d\u52a1\u5668\u548c\u8bbe\u5907"
    ).last
    await menu_item.click(force=True)
    await settle(page, 1200)

    await page.get_by_text("\u6dfb\u52a0\u670d\u52a1\u5668", exact=False).first.click(force=True)
    await settle(page, 1000)

    server_row = await wait_for_table_row(page, server_name)
    await server_row.locator(".el-checkbox__inner").first.click(force=True)
    await click_dialog_primary(page)
    await settle(page, 1200)

    server_row = await wait_for_table_row(page, server_name)
    await ensure_switch_enabled(page, server_row.locator(".el-switch").nth(1), settle_ms=800)

    if not await _select_device(page, device_name):
        raise RuntimeError(f"Unable to find device row for: {device_name}")

    await settle(page, 800)
    await ensure_text_visible(page, server_name)
    await ensure_text_visible(page, device_name)
