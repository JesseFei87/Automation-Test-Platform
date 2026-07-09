from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from runner import browser as browser_module


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com/#/index"
        self.viewport_size = {"width": 1600, "height": 1100}
        self.context = self

    async def wait_for_url(self, *_args, **_kwargs) -> None:
        return None

    async def wait_for_timeout(self, *_args, **_kwargs) -> None:
        return None

    async def clear_cookies(self) -> None:
        return None

    async def evaluate(self, *_args, **_kwargs) -> None:
        return None


class _FakeLocator:
    def __init__(self, username: str, visible_username: str | None) -> None:
        self._username = username
        self._visible_username = visible_username

    async def count(self) -> int:
        return 1 if self._username == self._visible_username else 0

    def nth(self, _index: int):
        return self

    async def is_visible(self) -> bool:
        return self._username == self._visible_username

    async def bounding_box(self):
        if self._username != self._visible_username:
            return None
        return {"x": 1400, "y": 80, "width": 60, "height": 24}


class _FakeHeaderPage(_FakePage):
    def __init__(self, visible_username: str | None) -> None:
        super().__init__()
        self._visible_username = visible_username

    def get_by_text(self, username: str, exact: bool = True):
        return _FakeLocator(username, self._visible_username)


class _FakeEvidence:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str | None]] = []

    def event(self, _page, kind: str, message: str, value: str | None = None) -> None:
        self.events.append((kind, message, value))


def _async_return(value):
    async def _fn(*_args, **_kwargs):
        return value
    return _fn


class BrowserLoginFlowTests(unittest.TestCase):
    def test_decode_token_subject_reads_jwt_sub(self) -> None:
        token = "eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJhZG1pbiIsImxvZ2luX3VzZXJfa2V5IjoiMTIzIn0.signature"
        assert browser_module._decode_token_subject(token) == "admin"

    def test_known_runtime_usernames_preserves_runtime_order_and_deduplicates(self) -> None:
        system = {
            "_runtime_accounts": {
                "tester": {"username": "test"},
                "admin": {"username": "admin"},
                "labo": {"username": "admin"},
            },
            "credentials": {"username": "admin"},
        }

        assert browser_module._known_runtime_usernames(system) == ["test", "admin"]

    def test_perform_login_returns_early_only_for_expected_account(self) -> None:
        page = _FakePage()
        system = {
            "credentials": {"username": "admin", "password": "admin-pass"},
            "account_fields": {"username_label": "用户名", "password_label": "密码", "submit_button": "登录"},
        }
        evidence = _FakeEvidence()
        fill_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        click_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        async def _record_fill(*args, **kwargs):
            fill_calls.append((args, kwargs))

        async def _record_click(*args, **kwargs):
            click_calls.append((args, kwargs))

        with (
            patch.object(browser_module, "open_login_page", _async_return(None)),
            patch.object(browser_module, "current_logged_in_username", _async_return("admin")),
            patch.object(browser_module, "get_evidence_recorder", lambda _page: evidence),
            patch.object(browser_module, "fill_first", _record_fill),
            patch.object(browser_module, "click_first", _record_click),
        ):
            asyncio.run(browser_module.perform_login(page, system, username="admin", password="admin-pass"))

        assert fill_calls == []
        assert click_calls == []
        assert evidence.events == [("login_probe", "already logged in with expected account", "admin")]

    def test_perform_login_forces_relogin_when_current_account_mismatches(self) -> None:
        page = _FakePage()
        system = {
            "credentials": {"username": "admin", "password": "admin-pass"},
            "account_fields": {"username_label": "用户名", "password_label": "密码", "submit_button": "登录"},
        }
        fill_values: list[str] = []
        logout_calls: list[str] = []
        login_state = iter(["admin", None, "test"])

        async def _current_logged_in_username(*_args, **_kwargs):
            return next(login_state)

        async def _record_fill(_page, _labels, value):
            fill_values.append(value)

        async def _record_logout(*_args, **_kwargs):
            logout_calls.append("logout")

        with (
            patch.object(browser_module, "open_login_page", _async_return(None)),
            patch.object(browser_module, "current_logged_in_username", _current_logged_in_username),
            patch.object(browser_module, "ensure_logged_out", _record_logout),
            patch.object(browser_module, "fill_first", _record_fill),
            patch.object(browser_module, "click_first", _async_return(None)),
        ):
            asyncio.run(browser_module.perform_login(page, system, username="test", password="123456"))

        assert logout_calls == ["logout"]
        assert fill_values == ["test", "123456"]


    def test_current_logged_in_username_prefers_visible_header_over_cookie_subject(self) -> None:
        page = _FakeHeaderPage("admin")
        system = {
            "_runtime_accounts": {
                "tester": {"username": "test"},
                "admin": {"username": "admin"},
            },
            "credentials": {"username": "admin", "password": "admin-pass"},
        }

        with patch.object(browser_module, "_cookie_subject_username", _async_return("test")):
            current = asyncio.run(browser_module.current_logged_in_username(page, system))

        assert current == "admin"


if __name__ == "__main__":
    unittest.main()
