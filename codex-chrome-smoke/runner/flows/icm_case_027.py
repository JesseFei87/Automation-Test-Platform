from __future__ import annotations

from runner.browser import click_first, fill_first, goto_route, wait_for_login_page, wait_for_url_contains
from runner.case_login import resolve_case_login_credentials


async def run(page, system, case) -> None:
    automation_asset = case.get("automation_asset") or {}
    selectors = automation_asset.get("selectors") or {}
    input_values = automation_asset.get("input_values") or {}
    username_selectors = selectors.get("username_input") or []
    password_selectors = selectors.get("password_input") or []
    login_selectors = selectors.get("login_button") or []
    if not all((username_selectors, password_selectors, login_selectors)):
        raise RuntimeError("TC-ICM-027 is missing persisted login selectors")

    username, password = resolve_case_login_credentials(case, system)
    if not username or not password:
        raise RuntimeError("TC-ICM-027 requires username and password in its case YAML")

    await goto_route(page, system, str((case.get("context_info") or {}).get("env_url") or system["entry_url"]))
    await wait_for_login_page(page, system)
    await fill_first(page, username_selectors, username)
    await fill_first(page, password_selectors, password)
    await click_first(page, login_selectors)
    await wait_for_url_contains(page, str(input_values.get("expected_url_fragment") or "#/icm"))
