from __future__ import annotations

from runner.browser import click_first, ensure_text_visible, fill_first, goto_route


async def run(page, system, case) -> None:
    # Generated from successful Agent exploration. Review before registration.
    await click_first(page, ['div:nth-of-type(1) > form > div:nth-of-type(4) > div > button'])
    await ensure_text_visible(page, '请输入您的账号')
