from __future__ import annotations

import time
from typing import Any

from playwright.async_api import Locator, Page

from runner.asset_recorder import inherit_asset_recorder
from runner.browser import (
    attach_case_runtime,
    capture_case_screenshot,
    click_first,
    ensure_text_visible,
    wait_for_url_contains,
)
from runner.flows.icm_common import click_dialog_primary, ensure_fresh_login, settle


REQUEST_READY_TIMEOUT_MS = 120000
DETAIL_MATCH_TIMEOUT_MS = 20000


def _copy_case_runtime(source: Page, target: Page) -> None:
    attach_case_runtime(target, getattr(source, "_case_run_id"), getattr(source, "_case_id"))
    inherit_asset_recorder(source, target)


async def _first_device_tile(page: Page, device_name: str) -> Locator:
    label = page.get_by_text(device_name, exact=False).first
    await label.wait_for(state="visible", timeout=20000)
    return label.locator("xpath=ancestor::*[3]").first


async def _close_visible_dialogs(page: Page) -> None:
    close_buttons = page.locator(".el-dialog__headerbtn:visible")
    count = await close_buttons.count()
    for _ in range(count):
        try:
            await close_buttons.first.click(force=True)
            await settle(page, 300)
        except Exception:
            break


async def _request_assistance_button(page: Page, tile: Locator) -> Locator | None:
    candidates = [
        page.locator("button").filter(has_text="请求协助").first,
        page.get_by_text("请求协助", exact=False).first,
        tile.locator("button").filter(has_text="请求协助").first,
    ]
    for locator in candidates:
        try:
            if await locator.count() and await locator.is_visible():
                return locator
        except Exception:
            continue
    return None


async def _wait_for_request_assistance(page: Page, device_name: str) -> Locator:
    deadline = time.monotonic() + REQUEST_READY_TIMEOUT_MS / 1000
    last_state = "unknown"

    while time.monotonic() < deadline:
        tile = await _first_device_tile(page, device_name)
        await tile.hover()
        await settle(page, 800)

        info_entry = tile.locator(".screen-top-head").first
        await info_entry.click(force=True)
        await settle(page, 1200)

        request_button = await _request_assistance_button(page, tile)
        if request_button is not None:
            return request_button

        loading_visible = False
        abnormal_visible = False
        try:
            loading_visible = await tile.locator(".el-loading-mask:visible").count() > 0
        except Exception:
            loading_visible = False
        try:
            abnormal_visible = await tile.get_by_text("网络异常", exact=False).count() > 0
        except Exception:
            abnormal_visible = False

        if loading_visible:
            last_state = "loading"
        elif abnormal_visible:
            last_state = "network_abnormal"
        else:
            last_state = "info_card_open_without_request_button"

        await _close_visible_dialogs(page)
        await settle(page, 1500)

    raise RuntimeError(f"Request Assistance did not become available for {device_name}; last state: {last_state}")


async def _fill_request_dialog(dialog: Locator, values: dict[str, Any]) -> None:
    inputs = dialog.locator("input:not([disabled])")
    textareas = dialog.locator("textarea")

    await inputs.nth(0).fill(str(values["request_valid_days"]))
    await inputs.nth(1).fill(str(values["request_contact"]))
    await inputs.nth(2).fill(str(values["request_phone"]))
    await textareas.first.fill(str(values["request_text"]))


async def _login_dev_portal(page: Page, values: dict[str, Any]) -> None:
    await page.goto(values["jesse_login_url"], wait_until="domcontentloaded")
    await settle(page, 1500)
    await page.locator("input").nth(0).fill(values["jesse_username"])
    await page.locator("input").nth(1).fill(values["jesse_password"])
    await page.locator("button").nth(0).click(force=True)
    await page.wait_for_url("**/index**", timeout=30000)
    await settle(page, 2000)


async def _open_matching_detail(page: Page, values: dict[str, Any]) -> None:
    request_text = values["request_text"]
    device_name = values["device_name"]
    requester = values["labo_username"]
    valid_days = str(values["request_valid_days"])
    max_candidates = 6

    await page.goto(values["remote_help_url"], wait_until="domcontentloaded")
    await settle(page, 3000)

    rows = page.locator("tbody tr")
    row_count = await rows.count()
    for index in range(min(row_count, max_candidates)):
        row = rows.nth(index)
        row_text = await row.inner_text()
        if requester not in row_text or device_name not in row_text or valid_days not in row_text:
            continue

        process_button = row.locator("button").filter(has_text="处理").first
        if await process_button.count() == 0:
            continue

        await process_button.click(force=True)
        await settle(page, 3000)
        try:
            demand_value = await page.locator("textarea").first.input_value(timeout=DETAIL_MATCH_TIMEOUT_MS)
        except Exception:
            demand_value = ""
        contact_value = ""
        phone_value = ""
        try:
            inputs = page.locator("input")
            count = await inputs.count()
            values_found: list[str] = []
            for pos in range(count):
                value = (await inputs.nth(pos).input_value()).strip()
                if value:
                    values_found.append(value)
            if values_found:
                contact_value = " ".join(values_found)
                phone_value = " ".join(values_found)
        except Exception:
            pass

        if request_text in demand_value and values["request_contact"] in contact_value and values["request_phone"] in phone_value:
            return

        await page.goto(values["remote_help_url"], wait_until="domcontentloaded")
        await settle(page, 2000)
        rows = page.locator("tbody tr")

    raise RuntimeError(f"Unable to locate a matching remote-help detail for request text: {request_text}")


async def _assert_detail_values(page: Page, values: dict[str, Any]) -> None:
    demand_value = await page.locator("textarea").first.input_value()
    if values["request_text"] not in demand_value:
        raise RuntimeError(f"Request detail text mismatch: {demand_value}")

    input_values: list[str] = []
    inputs = page.locator("input")
    for index in range(await inputs.count()):
        value = (await inputs.nth(index).input_value()).strip()
        if value:
            input_values.append(value)
    joined = " ".join(input_values)
    if values["request_contact"] not in joined:
        raise RuntimeError(f"Request contact mismatch: {joined}")
    if values["request_phone"] not in joined:
        raise RuntimeError(f"Request phone mismatch: {joined}")


async def _open_remote_view(page: Page) -> Page:
    async with page.context.expect_page(timeout=20000) as popup_info:
        await page.locator("button").filter(has_text="打开远程界面").first.click(force=True)
    remote = await popup_info.value
    await remote.wait_for_load_state("domcontentloaded")
    await settle(remote, 5000)
    await wait_for_url_contains(remote, "remoteView")
    return remote


async def _trigger_solve(remote: Page) -> None:
    await _close_visible_dialogs(remote)
    await settle(remote, 1000)

    toolbar_icons = remote.locator(".top-center img.el-tooltip")
    if await toolbar_icons.count() < 2:
        raise RuntimeError("Unable to locate remote toolbar solve icon")

    solve_icon = toolbar_icons.nth(1)
    await solve_icon.click(force=True)
    await settle(remote, 2000)

    confirm = remote.locator(".el-message-box__btns button").filter(has_text="确定").first
    if await confirm.count():
        await confirm.click(force=True)
        await settle(remote, 1500)


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    values = case.get("automation_asset", {}).get("input_values", {})
    device_name = values["device_name"]

    await ensure_fresh_login(page, system, username=values["labo_username"], password=values["labo_password"])
    await page.goto(f"{system['base_url'].rstrip('/')}/#/icm", wait_until="domcontentloaded")
    await settle(page, 4000)

    request_button = await _wait_for_request_assistance(page, device_name)
    await capture_case_screenshot(page, "01-entry.png")
    await request_button.click(force=True)
    await settle(page, 1500)

    dialog = page.locator(".el-dialog:visible").last
    await dialog.wait_for(state="visible", timeout=10000)
    await _fill_request_dialog(dialog, values)
    await capture_case_screenshot(page, "02-action.png")
    await click_dialog_primary(page, timeout=10000)
    await settle(page, 3000)

    dev_page = await page.context.new_page()
    _copy_case_runtime(page, dev_page)
    await _login_dev_portal(dev_page, values)
    await _open_matching_detail(dev_page, values)
    await _assert_detail_values(dev_page, values)

    remote = await _open_remote_view(dev_page)
    _copy_case_runtime(page, remote)
    await _trigger_solve(remote)
    await ensure_text_visible(remote, device_name)

    setattr(page, "_case_page", remote)
