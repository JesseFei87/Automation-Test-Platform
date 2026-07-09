from __future__ import annotations

from typing import Any

from playwright.async_api import Locator, Page

from runner.browser import (
    click_search_button,
    ensure_logged_in,
    ensure_logged_out,
    fill_first,
    fill_first_in,
    open_device_list,
    open_homepage,
    open_login_page,
    open_remote_help,
    open_server_list,
    open_user_management,
)


async def prepare_session(page: Page, system: dict[str, Any], username: str | None = None, password: str | None = None) -> None:
    await ensure_logged_in(page, system, username=username, password=password)


async def ensure_fresh_login(page: Page, system: dict[str, Any], username: str, password: str) -> None:
    await ensure_logged_out(page, system)
    await ensure_logged_in(page, system, username=username, password=password)


async def settle(page: Page, ms: int = 800) -> None:
    await page.wait_for_timeout(ms)


async def wait_for_table_row(page: Page, row_text: str, timeout: int = 20000) -> Locator:
    row = page.locator("tbody tr").filter(has_text=row_text).first
    await row.wait_for(state="visible", timeout=timeout)
    return row


async def wait_for_visible_dialog(page: Page, timeout: int = 5000) -> Locator:
    dialog = page.locator(".el-dialog:visible, .el-message-box:visible").last
    await dialog.wait_for(state="visible", timeout=timeout)
    return dialog


async def click_dialog_primary(page: Page, timeout: int = 5000) -> None:
    dialog = await wait_for_visible_dialog(page, timeout=timeout)
    button = dialog.locator(".el-dialog__footer .el-button--primary:visible, .el-message-box__btns .el-button--primary:visible, button:has-text('确定')").first
    await button.wait_for(state="visible", timeout=timeout)
    await button.click(force=True)


async def search_by_keyword(
    page: Page,
    selectors: str | list[str],
    keyword: str,
    *,
    settle_ms: int = 800,
    scope: Locator | None = None,
) -> None:
    if scope is None:
        await fill_first(page, selectors, keyword)
    else:
        await fill_first_in(scope, selectors, keyword)
    await click_search_button(page)
    await settle(page, settle_ms)


async def ensure_switch_enabled(page: Page, switch: Locator, settle_ms: int = 300) -> None:
    classes = await switch.get_attribute("class") or ""
    if "is-checked" in classes:
        return
    core = switch.locator(".el-switch__core")
    target = core.first if await core.count() else switch
    await target.click(force=True)
    await settle(page, settle_ms)


__all__ = [
    "prepare_session",
    "ensure_fresh_login",
    "settle",
    "wait_for_table_row",
    "wait_for_visible_dialog",
    "click_dialog_primary",
    "search_by_keyword",
    "ensure_switch_enabled",
    "open_device_list",
    "open_homepage",
    "open_login_page",
    "open_remote_help",
    "open_server_list",
    "open_user_management",
]
