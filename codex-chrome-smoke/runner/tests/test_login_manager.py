from __future__ import annotations

import asyncio

from runner.login_manager import ensure_storage_state_for_profile, is_login_state_valid, login_by_profile, resolve_storage_state_path, storage_state_exists


class FakeLocator:
    def __init__(self, visible: bool = True):
        self.calls = []
        self.visible = visible

    @property
    def first(self):
        return self

    async def wait_for(self, state="visible", timeout=5000):
        if not self.visible:
            raise RuntimeError("not visible")

    async def fill(self, value):
        self.calls.append(("fill", value))

    async def click(self):
        self.calls.append(("click", ""))


class FakeContext:
    def __init__(self):
        self.saved_path = ""

    async def storage_state(self, path):
        self.saved_path = path
        with open(path, "w", encoding="utf-8") as file:
            file.write("{}")


class FakePage:
    def __init__(self, redirect_to: str | None = None, redirect_on_wait: str | None = None, success_url: str | None = None):
        self.locators = {}
        self.redirect_to = redirect_to
        self.redirect_on_wait = redirect_on_wait
        self.success_url = success_url

    async def goto(self, url, wait_until, timeout=None):
        self.requested_url = url
        self.wait_until = wait_until
        self.timeout = timeout
        self.url = self.redirect_to or url

    def locator(self, selector):
        self.locators.setdefault(selector, FakeLocator())
        return self.locators[selector]

    async def wait_for_load_state(self, state, timeout=None):
        self.state = state
        self.state_timeout = timeout

    async def wait_for_timeout(self, timeout):
        self.wait_timeout = timeout
        if self.redirect_on_wait:
            self.url = self.redirect_on_wait

    async def wait_for_function(self, expression, *, arg=None, timeout):
        argument = arg
        self.success_wait = (expression, argument, timeout)
        if not self.success_url:
            raise RuntimeError("success route not reached")
        self.url = self.success_url

    def get_by_text(self, text):
        return FakeLocator()


class FakeSession:
    def __init__(self):
        self.page = FakePage()
        self.context = FakeContext()


def test_login_by_profile():
    page = FakePage()
    profile = {
        "login": {
            "url": "http://example.com/login",
            "username": "tester",
            "password": "pwd",
        }
    }

    assert asyncio.run(login_by_profile(page, profile)) is True
    assert page.url == "http://example.com/login"
    assert page.wait_until == "domcontentloaded"


def test_login_by_profile_uses_first_visible_selector_candidate():
    page = FakePage()
    page.locators["input.missing"] = FakeLocator(visible=False)
    profile = {
        "login": {
            "url": "http://example.com/login",
            "username": "tester",
            "password": "pwd",
            "username_selector": "input.missing, input[name=\"username\"]",
        }
    }

    assert asyncio.run(login_by_profile(page, profile)) is True
    assert page.locators['input[name="username"]'].calls == [("fill", "tester")]


def test_login_by_profile_waits_for_spa_success_route():
    page = FakePage(success_url="http://example.com/#/index")
    profile = {
        "login": {
            "url": "http://example.com/#/login",
            "username": "tester",
            "password": "pwd",
            "success_url_contains": "#/index",
        }
    }

    assert asyncio.run(login_by_profile(page, profile)) is True
    assert page.success_wait[1:] == ("#/index", 3000)


def test_storage_state_exists(tmp_path):
    path = tmp_path / "state.json"
    assert storage_state_exists(path) is False
    path.write_text("{}", encoding="utf-8")
    assert storage_state_exists(path) is True


def test_ensure_storage_state_reuses_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text("{}", encoding="utf-8")
    events = []
    relaunches = []

    async def fake_relaunch_context(session, profile, **kwargs):
        relaunches.append(kwargs)

    monkeypatch.setattr("runner.login_manager.relaunch_context", fake_relaunch_context)

    saved = asyncio.run(ensure_storage_state_for_profile(FakeSession(), {"storage_state": str(path)}, progress_callback=events.append))

    assert saved == path
    assert relaunches == [{"storage_state": str(path), "reuse_storage_state": False}]
    assert events == [
        {"stage": "storage_state_loaded", "storage_state": str(path)},
        {"stage": "storage_state_reused", "storage_state": str(path)},
    ]


def test_is_login_state_valid_detects_redirected_login_page() -> None:
    page = FakePage(redirect_to="http://example.com/#/login?redirect=%2Fdashboard")
    profile = {
        "base_url": "http://example.com",
        "pages": [{"page_id": "dashboard", "path": "/#/dashboard"}],
    }

    assert asyncio.run(is_login_state_valid(page, profile)) is False
    assert page.requested_url == "http://example.com/#/dashboard"
    assert page.wait_until == "domcontentloaded"


def test_is_login_state_valid_accepts_protected_page() -> None:
    page = FakePage(redirect_to="http://example.com/#/dashboard")
    profile = {
        "base_url": "http://example.com",
        "pages": [{"page_id": "dashboard", "path": "/#/dashboard"}],
    }

    assert asyncio.run(is_login_state_valid(page, profile)) is True


def test_is_login_state_valid_waits_for_spa_login_redirect() -> None:
    page = FakePage(redirect_on_wait="http://example.com/#/login?redirect=%2Fdashboard")
    profile = {
        "base_url": "http://example.com",
        "pages": [{"page_id": "dashboard", "path": "/#/dashboard"}],
    }

    assert asyncio.run(is_login_state_valid(page, profile)) is False
    assert page.wait_timeout == 500


def test_ensure_storage_state_relogs_when_existing_state_redirects_to_login(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text("{}", encoding="utf-8")
    session = FakeSession()
    session.page = FakePage(redirect_to="http://example.com/#/login?redirect=%2Fdashboard")
    events = []
    profile = {
        "base_url": "http://example.com",
        "storage_state": str(path),
        "pages": [{"page_id": "dashboard", "path": "/#/dashboard"}],
        "login": {
            "url": "http://example.com/#/login",
            "username": "tester",
            "password": "pwd",
        },
    }
    relaunches = []

    async def fake_relaunch_context(session, profile, **kwargs):
        relaunches.append(kwargs)

    monkeypatch.setattr("runner.login_manager.relaunch_context", fake_relaunch_context)

    saved = asyncio.run(ensure_storage_state_for_profile(session, profile, progress_callback=events.append))

    assert saved == path
    assert relaunches == [{"storage_state": str(path), "reuse_storage_state": False}]
    assert [event["stage"] for event in events] == ["storage_state_loaded", "storage_state_invalid", "auto_login_started", "storage_state_saved"]


def test_ensure_storage_state_reuses_legacy_icm_state(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    legacy = auth_dir / "icm-internal_tester_Tester.json"
    legacy.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("runner.login_manager.AUTH_STATE_DIR", auth_dir)
    events = []
    relaunches = []

    async def fake_relaunch_context(session, profile, **kwargs):
        relaunches.append(kwargs)

    monkeypatch.setattr("runner.login_manager.relaunch_context", fake_relaunch_context)

    saved = asyncio.run(
        ensure_storage_state_for_profile(
            FakeSession(),
            {"login": {"username": "Tester", "url": "http://example.com/login"}},
            progress_callback=events.append,
        )
    )

    assert saved == legacy
    assert relaunches == [{"storage_state": str(legacy), "reuse_storage_state": False}]
    assert events == [
        {"stage": "storage_state_loaded", "storage_state": str(legacy)},
        {"stage": "storage_state_reused", "storage_state": str(legacy)},
    ]


def test_configured_missing_storage_state_does_not_reuse_unrelated_legacy_state(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    (auth_dir / "icm-internal_tester_Tester.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("runner.login_manager.AUTH_STATE_DIR", auth_dir)
    profile = {"storage_state": str(tmp_path / "icm-tested-admin.json")}

    assert asyncio.run(ensure_storage_state_for_profile(FakeSession(), profile)) is None


def test_login_by_profile_rejects_missing_password() -> None:
    profile = {"login": {"url": "http://example.com/login", "username": "admin", "password": ""}}

    try:
        asyncio.run(login_by_profile(FakePage(), profile))
    except RuntimeError as exc:
        assert str(exc) == "automatic login requires non-empty username and password"
    else:
        raise AssertionError("expected missing login credential to fail")


def test_ensure_storage_state_auto_logs_in_and_saves(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    monkeypatch.setattr("runner.login_manager.AUTH_STATE_DIR", auth_dir)
    path = tmp_path / "state.json"
    session = FakeSession()
    events = []
    profile = {
        "storage_state": str(path),
        "login": {
            "url": "http://example.com/login",
            "username": "tester",
            "password": "pwd",
        },
    }

    saved = asyncio.run(ensure_storage_state_for_profile(session, profile, progress_callback=events.append))

    assert saved == path
    assert path.exists()
    assert session.context.saved_path == str(path)
    assert [event["stage"] for event in events] == ["auto_login_started", "storage_state_saved"]


def test_resolve_storage_state_path_accepts_relative_path():
    path = resolve_storage_state_path({"storage_state": "platform-data/auth/example.json"})

    assert path is not None
    assert path.parts[-3:] == ("platform-data", "auth", "example.json")
