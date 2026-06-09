from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from runner.browser import click_first, open_user_management, select_option
from runner.flows.icm_common import prepare_session


async def run(page: Page, system: dict[str, Any], case: dict[str, Any]) -> None:
    await prepare_session(page, system)
    await open_user_management(page, system)
    await page.wait_for_timeout(3000)
    await click_first(page, ["button:has-text(新增)", "button:has-text(+ 新增)", "text=新增"])
    await page.locator('input[placeholder="请输入用户昵称"]').first.fill("Tester")
    await page.locator(".vue-treeselect__control").first.click(force=True)
    await page.wait_for_timeout(500)
    await page.locator(".vue-treeselect__option").first.click(force=True)
    await page.locator('input[placeholder="请输入手机号码"]').first.fill("")
    await page.locator('input[placeholder="请输入邮箱"]').first.fill("")
    usernames = page.locator('input[placeholder="请输入用户名称"]')
    for index in range(await usernames.count()):
        await usernames.nth(index).fill("Tester")
    await page.locator('input[placeholder="请输入用户密码"]').first.fill("123456")
    await select_option(page, ["placeholder=请选择性别"], "男")
    await select_option(page, ["placeholder=请选择岗位"], "普通员工")
    await select_option(page, ["placeholder=请选择角色"], "普通角色")
    await page.locator(".el-dialog__footer button:visible").first.click(force=True)
    await page.wait_for_timeout(1500)
    await page.locator("tbody tr").filter(has_text="Tester").first.wait_for(timeout=20000)
