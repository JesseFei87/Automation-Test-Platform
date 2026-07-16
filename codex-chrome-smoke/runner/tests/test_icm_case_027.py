from __future__ import annotations

import asyncio

from runner.flows import icm_case_027


def test_tc_icm_027_uses_persisted_selectors_and_case_credentials(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    async def goto_route(page, system, route) -> None:
        calls.append(("goto", route))

    async def wait_for_login_page(page, system) -> None:
        calls.append(("wait_login", None))

    async def fill_first(page, selectors, value) -> None:
        calls.append(("fill", (selectors, value)))

    async def click_first(page, selectors) -> None:
        calls.append(("click", selectors))

    async def wait_for_url_contains(page, fragment) -> None:
        calls.append(("wait_url", fragment))

    monkeypatch.setattr(icm_case_027, "goto_route", goto_route)
    monkeypatch.setattr(icm_case_027, "wait_for_login_page", wait_for_login_page)
    monkeypatch.setattr(icm_case_027, "fill_first", fill_first)
    monkeypatch.setattr(icm_case_027, "click_first", click_first)
    monkeypatch.setattr(icm_case_027, "wait_for_url_contains", wait_for_url_contains)
    monkeypatch.setattr(icm_case_027, "resolve_case_login_credentials", lambda case, system: ("test", "123456"))

    case = {
        "context_info": {"env_url": "https://example.test/#/login"},
        "automation_asset": {
            "selectors": {
                "username_input": ["css=input[placeholder=\"账号\"]"],
                "password_input": ["css=input[placeholder=\"密码\"]"],
                "login_button": ["css=button.el-button--primary.el-button--medium", "text=登录"],
            },
            "input_values": {"expected_url_fragment": "#/icm"},
        },
    }

    asyncio.run(icm_case_027.run(object(), {"entry_url": "https://fallback.test/#/login"}, case))

    assert calls == [
        ("goto", "https://example.test/#/login"),
        ("wait_login", None),
        ("fill", (["css=input[placeholder=\"账号\"]"], "test")),
        ("fill", (["css=input[placeholder=\"密码\"]"], "123456")),
        ("click", ["css=button.el-button--primary.el-button--medium", "text=登录"]),
        ("wait_url", "#/icm"),
    ]
