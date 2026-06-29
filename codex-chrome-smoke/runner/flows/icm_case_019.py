from __future__ import annotations

from runner.browser import click_first, ensure_text_visible, fill_first, goto_route


async def run(page, system, case) -> None:
    # Generated from successful Agent exploration. Review before registration.
    await fill_first(page, ['input[placeholder="密码"]'], '123456')
