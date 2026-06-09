from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from runner.asset_recorder import inherit_asset_recorder
from runner.browser import capture_case_screenshot, ensure_text_visible, wait_for_url_contains
from runner.flows.icm_common import ensure_fresh_login


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    values = case.get("automation_asset", {}).get("input_values", {})
    username = values.get("username", "Tester")
    password = values.get("password", "123456")
    device_name = values.get("device_name", "Test_Ins01")

    await ensure_fresh_login(page, system, username=username, password=password)
    await page.goto(f"{system['base_url'].rstrip('/')}/#/icm", wait_until="domcontentloaded")
    await page.wait_for_timeout(4000)

    await ensure_text_visible(page, device_name)
    tile = page.get_by_text(device_name, exact=False).first.locator("xpath=ancestor::*[4]")
    await tile.hover()
    await page.wait_for_timeout(500)
    await capture_case_screenshot(page, "02-action.png")

    async with page.context.expect_page(timeout=10000) as popup_info:
        await page.locator(".screen-mask-img").first.click(force=True)
    remote = await popup_info.value
    inherit_asset_recorder(page, remote)
    await remote.wait_for_load_state("domcontentloaded")
    await wait_for_url_contains(remote, "#/remoteView")
    await remote.wait_for_timeout(3000)
    await ensure_text_visible(remote, device_name)

    setattr(page, "_case_page", remote)
