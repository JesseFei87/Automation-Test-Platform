from __future__ import annotations

from runner.browser import ensure_text_visible, goto_route
from runner.flows.icm_common import (
    click_dialog_primary,
    ensure_fresh_login,
    ensure_switch_enabled,
    search_by_keyword,
    settle,
    wait_for_visible_dialog,
)


async def _choose_dropdown(page, field, value: str) -> None:
    await field.click(force=True)
    await page.wait_for_timeout(300)
    dropdown = page.locator('.el-select-dropdown:visible').last
    option = dropdown.locator('.el-select-dropdown__item').filter(has_text=value).first
    await option.wait_for(state='visible', timeout=5000)
    await option.click(force=True)


async def run(page, system, case) -> None:
    # Generated from successful Agent exploration. Review before registration.
    await ensure_fresh_login(page, system, username='admin', password='Hubble_Service!1088')
    await goto_route(page, system, '#/hubble/device')
    await settle(page, 1200)
    await search_by_keyword(
        page,
        [
            'css=input[placeholder="请输入设备名称"]',
            'css=input[placeholder="输入设备名称"]',
        ],
        'ABCDE',
    )
    if await page.locator('tbody tr').filter(has_text='ABCDE').count():
        await ensure_text_visible(page, 'ABCDE')
        return

    await page.get_by_role('button', name='新增').first.click(force=True)
    dialog = await wait_for_visible_dialog(page)
    inputs = dialog.locator('input')
    await _choose_dropdown(page, inputs.nth(0), '连接器-1')
    await _choose_dropdown(page, inputs.nth(1), '标准设备')
    await inputs.nth(2).fill('ABCDE')
    await inputs.nth(3).fill('192.168.1.100')
    await inputs.nth(4).fill('65535')
    await inputs.nth(5).fill('00-1A-2B-3C-4D-5E')
    await inputs.nth(6).fill('255.255.255.0')
    await inputs.nth(7).fill('vncuser')
    await inputs.nth(8).fill('Vnc@1234')
    await _choose_dropdown(page, inputs.nth(9), '是')
    await ensure_switch_enabled(page, dialog.locator('.el-switch').last)
    remark_field = dialog.locator("textarea:visible, input[placeholder*='备注']:visible, textarea[placeholder*='备注']:visible").first
    if await remark_field.count():
        await remark_field.fill('自动化测试新增')
    await click_dialog_primary(page)
    dialog_after_submit = page.locator('.el-dialog:visible, .el-drawer:visible')
    if await dialog_after_submit.count():
        await dialog_after_submit.first.wait_for(state='hidden', timeout=5000)
    await settle(page, 1200)
    await search_by_keyword(
        page,
        [
            'css=input[placeholder="请输入设备名称"]',
            'css=input[placeholder="输入设备名称"]',
        ],
        'ABCDE',
        settle_ms=1200,
    )
    await ensure_text_visible(page, 'ABCDE')
    await ensure_text_visible(page, '192.168.1.100')
    await ensure_text_visible(page, '在线')
