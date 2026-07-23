from __future__ import annotations

from runner.browser import capture_case_screenshot, open_logout_prompt, wait_for_login_page
from runner.flows.icm_common import click_dialog_primary, wait_for_visible_dialog


async def run(page, system, case) -> None:
    await capture_case_screenshot(page, "step-01.png")

    await open_logout_prompt(page, system)
    await wait_for_visible_dialog(page)
    await capture_case_screenshot(page, "step-02.png")

    await click_dialog_primary(page)
    await page.wait_for_url("**/#/login**", timeout=20000)
    await wait_for_login_page(page, system)
    await page.locator('input[type="password"]').first.wait_for(state="visible", timeout=5000)
    await capture_case_screenshot(page, "step-03.png")
