from __future__ import annotations

import asyncio

from types import SimpleNamespace
import pytest

from runner import browser as browser_module
from runner.browser import BrowserSession, _maximize_browser_window, _sync_window_viewport, attach_browser_over_cdp, close_browser, relaunch_context


def test_maximize_browser_window_sets_chromium_window_state() -> None:
    calls: list[tuple[str, object]] = []

    class FakeCdp:
        async def send(self, method: str, params: object | None = None):
            calls.append((method, params))
            if method == "Target.getTargetInfo":
                return {"targetInfo": {"targetId": "target-1"}}
            if method == "Browser.getWindowForTarget":
                return {"windowId": 42}
            return {}

    class FakeContext:
        async def new_cdp_session(self, _page):
            return FakeCdp()

    asyncio.run(_maximize_browser_window(type("Page", (), {"context": FakeContext()})()))

    assert calls[-1] == ("Browser.setWindowBounds", {"windowId": 42, "bounds": {"windowState": "maximized"}})


def test_sync_window_viewport_uses_maximized_window_bounds() -> None:
    calls: list[tuple[str, object]] = []

    class FakeCdp:
        async def send(self, method: str, params: object | None = None):
            calls.append((method, params))
            if method == "Target.getTargetInfo":
                return {"targetInfo": {"targetId": "target-2"}}
            if method == "Browser.getWindowForTarget":
                return {"bounds": {"width": 1936, "height": 1048}}
            return {}

    class FakePage:
        class Context:
            async def new_cdp_session(self, _page):
                return FakeCdp()

        context = Context()

    asyncio.run(_sync_window_viewport(FakePage()))

    assert calls[0] == ("Target.getTargetInfo", None)
    assert calls[1] == ("Browser.getWindowForTarget", {"targetId": "target-2"})
    assert calls[2] == (
        "Emulation.setDeviceMetricsOverride",
        {"width": 1920, "height": 1032, "deviceScaleFactor": 1, "mobile": False},
    )


def test_relaunch_context_preserves_window_viewport_settings(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeContext:
        async def close(self):
            calls.append(("close", None))

    class FakeBrowser:
        async def new_context(self, **kwargs):
            calls.append(("new_context", kwargs))
            return FakeNewContext()

    class FakeNewContext:
        async def new_page(self):
            calls.append(("new_page", None))
            return SimpleNamespace()

    async def prepare_page_window_viewport(page, *, headless, maximize_window, viewport_mode):
        calls.append(("prepare", {"headless": headless, "maximize_window": maximize_window, "viewport_mode": viewport_mode}))

    def attach_window_viewport_resync(page, *, headless, maximize_window, viewport_mode):
        calls.append(("attach", {"headless": headless, "maximize_window": maximize_window, "viewport_mode": viewport_mode}))

    monkeypatch.setattr(browser_module, "_prepare_page_window_viewport", prepare_page_window_viewport)
    monkeypatch.setattr(browser_module, "_attach_window_viewport_resync", attach_window_viewport_resync)
    session = BrowserSession(
        playwright=SimpleNamespace(),
        browser=FakeBrowser(),
        context=FakeContext(),
        page=SimpleNamespace(),
        headless=False,
        maximize_window=True,
        viewport_mode="window",
        viewport_width=1600,
        viewport_height=1100,
        ignore_https_errors=False,
    )

    asyncio.run(relaunch_context(session, reuse_storage_state=False))

    assert calls[0] == ("new_context", {"storage_state": None, "viewport": None, "ignore_https_errors": False})
    assert calls[2] == ("prepare", {"headless": False, "maximize_window": True, "viewport_mode": "window"})
    assert calls[3] == ("attach", {"headless": False, "maximize_window": True, "viewport_mode": "window"})


def test_relaunch_context_preserves_fixed_viewport_settings(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeContext:
        async def close(self):
            calls.append(("close", None))

    class FakeBrowser:
        async def new_context(self, **kwargs):
            calls.append(("new_context", kwargs))
            return FakeNewContext()

    class FakeNewContext:
        async def new_page(self):
            return SimpleNamespace()

    async def prepare_page_window_viewport(page, *, headless, maximize_window, viewport_mode):
        calls.append(("prepare", {"headless": headless, "maximize_window": maximize_window, "viewport_mode": viewport_mode}))

    def attach_window_viewport_resync(page, *, headless, maximize_window, viewport_mode):
        calls.append(("attach", {"headless": headless, "maximize_window": maximize_window, "viewport_mode": viewport_mode}))

    monkeypatch.setattr(browser_module, "_prepare_page_window_viewport", prepare_page_window_viewport)
    monkeypatch.setattr(browser_module, "_attach_window_viewport_resync", attach_window_viewport_resync)
    session = BrowserSession(
        playwright=SimpleNamespace(),
        browser=FakeBrowser(),
        context=FakeContext(),
        page=SimpleNamespace(),
        viewport_mode="fixed",
        viewport_width=1920,
        viewport_height=1080,
    )

    asyncio.run(relaunch_context(session, reuse_storage_state=False))

    assert calls[0] == (
        "new_context",
        {"storage_state": None, "viewport": {"width": 1920, "height": 1080}, "ignore_https_errors": True},
    )


def test_attach_browser_over_cdp_rejects_non_local_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback host"):
        asyncio.run(attach_browser_over_cdp("http://192.168.16.203:9222"))


def test_attach_browser_over_cdp_uses_existing_context_and_only_closes_scanner_tab(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakePage:
        async def close(self):
            calls.append(("page.close", None))

    class FakeContext:
        async def new_page(self):
            calls.append(("context.new_page", None))
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

        async def close(self):
            calls.append(("browser.close", None))

    class FakeChromium:
        async def connect_over_cdp(self, endpoint):
            calls.append(("connect_over_cdp", endpoint))
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        async def stop(self):
            calls.append(("playwright.stop", None))

    class FakeManager:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setattr(browser_module, "async_playwright", lambda: FakeManager())
    session = asyncio.run(attach_browser_over_cdp("http://127.0.0.1:9222"))
    asyncio.run(close_browser(session))

    assert session.attached_over_cdp is True
    assert calls == [
        ("connect_over_cdp", "http://127.0.0.1:9222"),
        ("context.new_page", None),
        ("page.close", None),
        ("playwright.stop", None),
    ]
