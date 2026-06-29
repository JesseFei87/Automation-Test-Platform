from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import shutil
import time

import yaml
from playwright.async_api import Browser, BrowserContext, Locator, Page, Playwright, async_playwright

from runner.asset_recorder import get_asset_recorder
from runner.evidence_recorder import get_evidence_recorder

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PATH = ROOT / "systems" / "icm-internal.yaml"
SCREENSHOT_ROOT = ROOT / "screenshots"
SCREENSHOT_LATEST_ROOT = SCREENSHOT_ROOT / "latest"
SCREENSHOT_RUNS_ROOT = SCREENSHOT_ROOT / "runs"

# 路线 B · T6：login 复用 storage_state 落盘目录（按 user_key 区分账号）
AUTH_STATE_DIR = ROOT / "platform-data" / "auth"


@dataclass(slots=True)
class BrowserSession:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page


# 路线 B · T6：依据 (system, account) 推导 user_key，用于 storage_state 文件名
_ACCOUNT_PRIORITY = ("tester", "admin", "labo", "jesse")


def _user_key_for_system(system: dict[str, Any]) -> str:
    """从 system 的 accounts / credentials 推导稳定 user_key。

    优先级：tester > admin > labo > jesse > system.credentials.username > anonymous。
    命名空间用 system_id，避免跨系统的 storage_state 互串。
    """
    system_id = (system.get("id") or "default").strip().replace("/", "_").replace(":", "_")
    accounts = system.get("_runtime_accounts") or {}
    for account_name in _ACCOUNT_PRIORITY:
        account = accounts.get(account_name) or {}
        username = (account.get("username") or "").strip()
        if username:
            return f"{system_id}:{account_name}:{username}"
    creds = system.get("credentials") or {}
    username = (creds.get("username") or "").strip()
    if username:
        return f"{system_id}:default:{username}"
    return f"{system_id}:anonymous"


def auth_state_path_for(system: dict[str, Any]) -> Path:
    """返回该 (system, user) 组合对应的 storage_state JSON 文件路径。"""
    user_key = _user_key_for_system(system)
    safe = user_key.replace(":", "_").replace("/", "_")
    return AUTH_STATE_DIR / f"{safe}.json"


async def save_storage_state(context: BrowserContext, system: dict[str, Any]) -> Path | None:
    """登录成功后把当前 context 的 storage_state 落盘到 auth/{user_key}.json。"""
    try:
        path = auth_state_path_for(system)
        AUTH_STATE_DIR.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(path))
        return path
    except Exception:  # pragma: no cover - 防御
        return None


async def relaunch_context(
    session: "BrowserSession",
    system: dict[str, Any] | None = None,
    *,
    reuse_storage_state: bool = True,
) -> None:
    """关闭当前 context，新建一个。如果 system 有 storage_state 落盘则加载复用。"""
    old_context = session.context
    storage_state_arg: str | None = None
    if reuse_storage_state and system is not None:
        path = auth_state_path_for(system)
        if path.exists():
            storage_state_arg = str(path)
    new_context = await session.browser.new_context(
        storage_state=storage_state_arg,
        viewport={"width": 1600, "height": 1100},
        ignore_https_errors=True,
    )
    new_page = await new_context.new_page()
    try:
        await old_context.close()
    except Exception:
        pass
    session.context = new_context
    session.page = new_page


def load_system(system_id: str = "icm-internal") -> dict[str, Any]:
    data = yaml.safe_load(SYSTEM_PATH.read_text(encoding="utf-8"))
    if data["id"] != system_id:
        raise ValueError(f"Unsupported system: {system_id}")
    return apply_platform_runtime_settings(data)


def apply_platform_runtime_settings(system: dict[str, Any]) -> dict[str, Any]:
    settings = load_platform_runtime_settings()
    environment = settings.get("environment") or {}
    accounts = settings.get("accounts") or {}
    admin = accounts.get("admin") or {}
    icm_base_url = environment.get("icm_base_url")
    icm_login_url = environment.get("icm_login_url")
    if icm_base_url:
        system["base_url"] = icm_base_url
    if icm_login_url:
        system["entry_url"] = icm_login_url
        system["login_url"] = icm_login_url
    if admin.get("username") or admin.get("password"):
        system["credentials"] = {
            "username": admin.get("username") or system["credentials"]["username"],
            "password": admin.get("password") or system["credentials"]["password"],
        }
    system["_runtime_environment"] = environment
    system["_runtime_accounts"] = accounts
    return system


def load_platform_runtime_settings() -> dict[str, Any]:
    try:
        from icm_platform.db import get_platform_settings

        return get_platform_settings(mask_secrets=False)
    except Exception:
        return {}


def load_case(case_id: str) -> dict[str, Any]:
    for case_path in sorted(ROOT.glob(f"test-cases/icm/{case_id}*.yaml")):
        data = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        if data.get("id") == case_id:
            return data
    normalized_case_id = str(case_id or "").strip().upper()
    for case_path in sorted(ROOT.glob("test-cases/icm/*.yaml")):
        data = yaml.safe_load(case_path.read_text(encoding="utf-8")) or {}
        if str(data.get("source_draft_case_id") or "").strip().upper() == normalized_case_id:
            return data
    raise FileNotFoundError(f"Case not found: {case_id}")


def load_case_file(case_path: str | Path) -> dict[str, Any]:
    path = Path(case_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not data.get("id"):
        raise ValueError(f"Draft case YAML missing id: {path}")
    return data


def _base_url(system: dict[str, Any]) -> str:
    return system["base_url"].rstrip("/")


def case_url(system: dict[str, Any], route: str) -> str:
    if route.startswith("http://") or route.startswith("https://"):
        return route
    if not route.startswith("#"):
        route = route if route.startswith("/") else f"/{route}"
    return f"{_base_url(system)}{route}"


async def launch_browser(
    headless: bool = False,
    system: dict[str, Any] | None = None,
    *,
    reuse_storage_state: bool = True,
) -> BrowserSession:
    """系统级启动浏览器。

    - 若传 system 且存在对应 storage_state 落盘文件，则 context 加载该 state 复用登录会话
    - 若 storage_state 不存在或未传 system，走默认 context（每次重新登录）
    """
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(channel="chrome", headless=headless)
    except Exception:
        browser = await playwright.chromium.launch(headless=headless)
    storage_state_arg: str | None = None
    if reuse_storage_state and system is not None:
        path = auth_state_path_for(system)
        if path.exists():
            storage_state_arg = str(path)
    context = await browser.new_context(
        storage_state=storage_state_arg,
        viewport={"width": 1600, "height": 1100},
        ignore_https_errors=True,
    )
    page = await context.new_page()
    return BrowserSession(playwright=playwright, browser=browser, context=context, page=page)


async def close_browser(session: BrowserSession) -> None:
    await session.context.close()
    await session.browser.close()
    await session.playwright.stop()


async def wait_for_screenshot_ready(page: Page, timeout_ms: int = 5000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    for state in ("domcontentloaded", "load"):
        remaining = max(1, int((deadline - time.monotonic()) * 1000))
        if remaining <= 1:
            break
        try:
            await page.wait_for_load_state(state, timeout=remaining)
        except Exception:
            pass

    try:
        await page.evaluate(
            """async () => {
                if (document.fonts && document.fonts.ready) {
                    try {
                        await document.fonts.ready;
                    } catch (error) {
                        // Ignore font readiness errors and continue with the capture.
                    }
                }
            }"""
        )
    except Exception:
        pass

    try:
        await page.evaluate("() => new Promise(requestAnimationFrame)")
        await page.evaluate("() => new Promise(requestAnimationFrame)")
    except Exception:
        pass

    while time.monotonic() < deadline:
        loading_candidates = [
            ".el-loading-mask:visible",
            ".loading:visible",
            ".spinner:visible",
            "[aria-busy='true']",
        ]
        busy = False
        for selector in loading_candidates:
            try:
                if await page.locator(selector).count():
                    busy = True
                    break
            except Exception:
                continue
        if not busy:
            break
        await page.wait_for_timeout(250)

    await page.wait_for_timeout(250)


def _archive_screenshot_path(run_id: str, name: str) -> Path:
    return SCREENSHOT_RUNS_ROOT / run_id / name


def _latest_screenshot_path(case_id: str, name: str) -> Path:
    return SCREENSHOT_LATEST_ROOT / case_id / name


async def screenshot(page: Page, run_id: str, case_id: str, name: str) -> Path:
    out_dir = _archive_screenshot_path(run_id, name).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    await wait_for_screenshot_ready(page)
    try:
        setattr(page, "_last_known_title", await page.title())
    except Exception:
        pass
    await page.screenshot(path=str(path), full_page=True)
    evidence = get_evidence_recorder(page)
    if evidence:
        evidence.event(page, "screenshot", f"captured screenshot {name}", path=str(path.relative_to(ROOT)))
        await evidence.dom_snapshot(page, name.replace(".png", ".html"))
    captured = getattr(page, "_case_captured_stages", None)
    if isinstance(captured, set):
        captured.add(name)
    recorder = get_asset_recorder(page)
    if recorder:
        recorder.screenshot(str(path.relative_to(ROOT)))
    return path


async def capture_case_screenshot(page: Page, name: str) -> Path:
    run_id = getattr(page, "_case_run_id", None)
    case_id = getattr(page, "_case_id", None)
    if not run_id or not case_id:
        raise RuntimeError("Case runtime is not attached to this page")
    return await screenshot(page, run_id, case_id, name)


def attach_case_runtime(page: Page, run_id: str, case_id: str) -> None:
    setattr(page, "_case_run_id", run_id)
    setattr(page, "_case_id", case_id)
    setattr(page, "_case_captured_stages", set())


def finalize_screenshots(run_id: str, case_id: str, screenshot_names: Iterable[str], keep_archive: bool) -> list[str]:
    paths: list[str] = []
    archive_dir = SCREENSHOT_RUNS_ROOT / run_id
    latest_dir = SCREENSHOT_LATEST_ROOT / case_id
    latest_dir.mkdir(parents=True, exist_ok=True)

    for name in screenshot_names:
        archive_path = archive_dir / name
        latest_path = latest_dir / name
        if archive_path.exists():
            shutil.copy2(archive_path, latest_path)
        chosen = archive_path if keep_archive else latest_path
        paths.append(str(chosen.relative_to(ROOT)))

    if not keep_archive and archive_dir.exists():
        shutil.rmtree(archive_dir, ignore_errors=True)
    return paths


def _to_selectors(values: str | Iterable[str]) -> list[str]:
    if isinstance(values, str):
        return [values]
    return [value for value in values if value]


def _locator_for(page: Page, selector: str) -> Locator:
    if selector.startswith("placeholder="):
        return page.get_by_placeholder(selector.removeprefix("placeholder="))
    if selector.startswith("label="):
        return page.get_by_label(selector.removeprefix("label="))
    if selector.startswith("text="):
        return page.get_by_text(selector.removeprefix("text="), exact=False)
    if selector.startswith("xpath="):
        return page.locator(selector.removeprefix("xpath="))
    if selector.startswith("css="):
        return page.locator(selector.removeprefix("css="))
    return page.locator(selector)


async def first_visible(page: Page, selectors: str | Iterable[str]) -> Locator | None:
    for selector in _to_selectors(selectors):
        locator = _locator_for(page, selector)
        try:
            if await locator.count() and await locator.first.is_visible():
                return locator.first
        except Exception:
            continue
    return None


async def fill_first(page: Page, selectors: str | Iterable[str], value: str) -> None:
    locator = await first_visible(page, selectors)
    if locator is None:
        raise RuntimeError(f"Unable to fill field for selectors: {list(_to_selectors(selectors))}")
    await locator.fill(value)
    evidence = get_evidence_recorder(page)
    if evidence:
        evidence.event(page, "fill", "filled visible field", selectors=_to_selectors(selectors), value=value)
    recorder = get_asset_recorder(page)
    if recorder:
        recorder.fill(_to_selectors(selectors), value)


async def fill_first_in(scope: Locator, selectors: str | Iterable[str], value: str) -> None:
    if isinstance(selectors, str):
        candidates = [selectors]
    else:
        candidates = [value for value in selectors if value]
    for selector in candidates:
        if selector.startswith("placeholder="):
            placeholder = selector.removeprefix("placeholder=")
            locator = scope.locator(f'[placeholder="{placeholder}"]')
        elif selector.startswith("label="):
            label = selector.removeprefix("label=")
            locator = scope.locator(f'label:has-text("{label}")')
        elif selector.startswith("text="):
            locator = scope.locator(f'text={selector.removeprefix("text=")}')
        elif selector.startswith("xpath="):
            locator = scope.locator(selector.removeprefix("xpath="))
        elif selector.startswith("css="):
            locator = scope.locator(selector.removeprefix("css="))
        else:
            locator = scope.locator(selector)
        try:
            if await locator.count() and await locator.first.is_visible():
                await locator.first.fill(value)
                evidence = get_evidence_recorder(scope.page)
                if evidence:
                    evidence.event(scope.page, "fill", "filled visible scoped field", selectors=candidates, value=value)
                recorder = get_asset_recorder(scope.page)
                if recorder:
                    recorder.fill(candidates, value)
                return
        except Exception:
            continue
    raise RuntimeError(f"Unable to fill field for selectors: {list(candidates)}")


async def click_first(page: Page, selectors: str | Iterable[str]) -> None:
    locator = await first_visible(page, selectors)
    if locator is None:
        raise RuntimeError(f"Unable to click control for selectors: {list(_to_selectors(selectors))}")
    await locator.click(force=True)
    evidence = get_evidence_recorder(page)
    if evidence:
        evidence.event(page, "click", "clicked visible control", selectors=_to_selectors(selectors))
    recorder = get_asset_recorder(page)
    if recorder:
        recorder.click(_to_selectors(selectors))


async def click_first_in(scope: Locator, selectors: str | Iterable[str]) -> None:
    if isinstance(selectors, str):
        candidates = [selectors]
    else:
        candidates = [value for value in selectors if value]
    for selector in candidates:
        if selector.startswith("placeholder="):
            placeholder = selector.removeprefix("placeholder=")
            locator = scope.locator(f'[placeholder="{placeholder}"]')
        elif selector.startswith("label="):
            label = selector.removeprefix("label=")
            locator = scope.locator(f'label:has-text("{label}")')
        elif selector.startswith("text="):
            locator = scope.locator(f'text={selector.removeprefix("text=")}')
        elif selector.startswith("xpath="):
            locator = scope.locator(selector.removeprefix("xpath="))
        elif selector.startswith("css="):
            locator = scope.locator(selector.removeprefix("css="))
        else:
            locator = scope.locator(selector)
        try:
            if await locator.count() and await locator.first.is_visible():
                await locator.first.click(force=True)
                evidence = get_evidence_recorder(scope.page)
                if evidence:
                    evidence.event(scope.page, "click", "clicked visible scoped control", selectors=candidates)
                recorder = get_asset_recorder(scope.page)
                if recorder:
                    recorder.click(candidates)
                return
        except Exception:
            continue
    raise RuntimeError(f"Unable to click control for selectors: {list(candidates)}")


async def click_text(page: Page, text: str) -> None:
    locator = page.get_by_text(text, exact=False)
    if await locator.count() == 0:
        raise RuntimeError(f"Unable to find text: {text}")
    await locator.first.click(force=True)
    evidence = get_evidence_recorder(page)
    if evidence:
        evidence.event(page, "click", "clicked visible text", selectors=[f"text={text}"])
    recorder = get_asset_recorder(page)
    if recorder:
        recorder.click([f"text={text}"])


async def select_option(page: Page, field_selectors: str | Iterable[str], option_text: str) -> None:
    await click_first(page, field_selectors)
    await page.wait_for_timeout(200)
    option_candidates = [
        page.get_by_text(option_text, exact=False),
        page.locator(".el-select-dropdown__item").filter(has_text=option_text),
        page.locator(".vue-treeselect__option").filter(has_text=option_text),
        page.locator(f"text={option_text}"),
    ]
    for locator in option_candidates:
        try:
            if await locator.count():
                await locator.first.click(force=True)
                evidence = get_evidence_recorder(page)
                if evidence:
                    evidence.event(page, "select", "selected option", selectors=_to_selectors(field_selectors), value=option_text)
                recorder = get_asset_recorder(page)
                if recorder:
                    recorder.select(_to_selectors(field_selectors), option_text)
                return
        except Exception:
            continue
    raise RuntimeError(f"Unable to select option: {option_text}")


async def select_option_in(scope: Locator, field_selectors: str | Iterable[str], option_text: str) -> None:
    if isinstance(field_selectors, str):
        candidates = [field_selectors]
    else:
        candidates = [value for value in field_selectors if value]
    for selector in candidates:
        if selector.startswith("placeholder="):
            placeholder = selector.removeprefix("placeholder=")
            locator = scope.locator(f'[placeholder="{placeholder}"]')
        elif selector.startswith("label="):
            label = selector.removeprefix("label=")
            locator = scope.locator(f'label:has-text("{label}")')
        elif selector.startswith("text="):
            locator = scope.locator(f'text={selector.removeprefix("text=")}')
        elif selector.startswith("xpath="):
            locator = scope.locator(selector.removeprefix("xpath="))
        elif selector.startswith("css="):
            locator = scope.locator(selector.removeprefix("css="))
        else:
            locator = scope.locator(selector)
        try:
            if await locator.count() and await locator.first.is_visible():
                await locator.first.click(force=True)
                await scope.page.wait_for_timeout(200)
                option_candidates = [
                    scope.page.locator(f'text={option_text}'),
                    scope.page.locator(".el-select-dropdown__item").filter(has_text=option_text),
                    scope.page.locator(".vue-treeselect__option").filter(has_text=option_text),
                    scope.page.locator(f'text={option_text}'),
                ]
                for option_locator in option_candidates:
                    try:
                        if await option_locator.count():
                            await option_locator.first.click(force=True)
                            evidence = get_evidence_recorder(scope.page)
                            if evidence:
                                evidence.event(scope.page, "select", "selected scoped option", selectors=candidates, value=option_text)
                            recorder = get_asset_recorder(scope.page)
                            if recorder:
                                recorder.select(candidates, option_text)
                            return
                    except Exception:
                        continue
        except Exception:
            continue
    raise RuntimeError(f"Unable to select option: {option_text}")


async def wait_for_any_text(page: Page, texts: Iterable[str], timeout: int = 20000) -> None:
    for text in texts:
        try:
            await page.get_by_text(text, exact=False).first.wait_for(timeout=timeout)
            return
        except Exception:
            continue
    await page.wait_for_timeout(500)


async def goto_route(page: Page, system: dict[str, Any], route: str) -> None:
    await page.goto(case_url(system, route), wait_until="domcontentloaded")
    try:
        await page.wait_for_load_state("load", timeout=5000)
    except Exception:
        pass
    await page.wait_for_timeout(500)
    recorder = get_asset_recorder(page)
    if recorder:
        recorder.route(route)
    evidence = get_evidence_recorder(page)
    if evidence:
        evidence.event(page, "route", f"opened route {route}", selectors=[route])


async def open_homepage(page: Page, system: dict[str, Any]) -> None:
    await goto_route(page, system, "#/index")


async def open_login_page(page: Page, system: dict[str, Any]) -> None:
    await goto_route(page, system, system["entry_url"])


async def open_device_list(page: Page, system: dict[str, Any]) -> None:
    await goto_route(page, system, "#/hubble/device")


async def open_server_list(page: Page, system: dict[str, Any]) -> None:
    await goto_route(page, system, "#/hubble/server")


async def open_user_management(page: Page, system: dict[str, Any]) -> None:
    await goto_route(page, system, "#/system/user")


async def open_remote_help(page: Page, system: dict[str, Any]) -> None:
    await goto_route(page, system, "#/hubble/remoteHelpInfo")


def _login_labels(system: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    fields = system["account_fields"]
    usernames = ["账号", fields["username_label"], "account", "用户名", "user name", "username", 'input[type="text"]']
    passwords = ["密码", fields["password_label"], "password", 'input[type="password"]']
    submits = ["登录", fields["submit_button"], "login", 'button.el-button--primary.el-button--medium']
    return usernames, passwords, submits


async def is_logged_in(page: Page, system: dict[str, Any]) -> bool:
    url = page.url.lower()
    if "#/login" in url:
        return False
    for signal in system["login_state_check"]["logged_in_signals"]:
        if signal and signal.lower() in url:
            return True
    avatar = page.locator("img.user-avatar")
    if await avatar.count():
        try:
            if await avatar.first.is_visible():
                return True
        except Exception:
            pass
    return False


async def wait_for_login_page(page: Page, system: dict[str, Any]) -> None:
    locator = await first_visible(page, ["placeholder=账号", "placeholder=密码", "button:has-text(登录)", 'input[type="password"]'])
    if locator is None:
        await page.wait_for_timeout(500)


async def perform_login(page: Page, system: dict[str, Any], username: str | None = None, password: str | None = None) -> None:
    await open_login_page(page, system)
    if await is_logged_in(page, system):
        evidence = get_evidence_recorder(page)
        if evidence:
            evidence.event(page, "login_probe", "already logged in after opening login page")
        return
    usernames, passwords, submits = _login_labels(system)
    await fill_first(page, usernames, username or system["credentials"]["username"])
    await fill_first(page, passwords, password or system["credentials"]["password"])
    await click_first(page, submits)
    try:
        await page.wait_for_url("**/#/index**", timeout=20000)
    except Exception:
        await page.wait_for_timeout(1000)


async def ensure_logged_in(page: Page, system: dict[str, Any], username: str | None = None, password: str | None = None) -> None:
    if await is_logged_in(page, system):
        return
    await perform_login(page, system, username=username, password=password)


async def ensure_logged_out(page: Page, system: dict[str, Any]) -> None:
    if not await is_logged_in(page, system):
        await wait_for_login_page(page, system)
        return
    await page.context.clear_cookies()
    await page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
    await open_login_page(page, system)
    await wait_for_login_page(page, system)


async def click_row_action(page: Page, row_text: str, action_texts: Iterable[str]) -> None:
    row = page.locator("tr").filter(has_text=row_text).first
    if await row.count() == 0:
        raise RuntimeError(f"Unable to find row for: {row_text}")
    for action_text in action_texts:
        candidates = [
            row.get_by_role("button", name=action_text),
            row.locator(f"button:has-text({action_text})"),
            row.get_by_text(action_text, exact=False),
        ]
        for locator in candidates:
            try:
                if await locator.count() and await locator.first.is_visible():
                    await locator.first.click(force=True)
                    recorder = get_asset_recorder(page)
                    if recorder:
                        recorder.click([f"row={row_text}", f"text={action_text}"])
                    return
            except Exception:
                continue
    raise RuntimeError(f"Unable to click row action for {row_text}: {list(action_texts)}")


async def click_row_action_if_present(page: Page, row_text: str, action_texts: Iterable[str], timeout_ms: int = 5000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    row = page.locator("tr").filter(has_text=row_text).first
    while time.monotonic() < deadline:
        try:
            if await row.count():
                for action_text in action_texts:
                    candidates = [
                        row.get_by_role("button", name=action_text),
                        row.locator(f"button:has-text({action_text})"),
                        row.get_by_text(action_text, exact=False),
                    ]
                    for locator in candidates:
                        try:
                            if await locator.count() and await locator.first.is_visible():
                                await locator.first.click(force=True)
                                recorder = get_asset_recorder(page)
                                if recorder:
                                    recorder.click([f"row={row_text}", f"text={action_text}"])
                                return True
                        except Exception:
                            continue
        except Exception:
            pass
        await page.wait_for_timeout(250)
    return False


async def click_search_button(page: Page) -> None:
    candidates = [
        "button:has-text(\u641c\u7d22)",
        "button:has-text(\u67e5\u8be2)",
        "button:has-text(Search)",
        "text=\u641c\u7d22",
        "text=\u67e5\u8be2",
    ]
    await click_first(page, candidates)


async def ensure_text_visible(page: Page, text: str) -> None:
    if await page.get_by_text(text, exact=False).count() == 0:
        raise RuntimeError(f"Expected text not visible: {text}")
    evidence = get_evidence_recorder(page)
    if evidence:
        evidence.event(page, "assert_text", "asserted visible text", value=text)
    recorder = get_asset_recorder(page)
    if recorder:
        recorder.assert_text(text)


async def wait_for_url_contains(page: Page, fragment: str, timeout: int = 20000) -> None:
    await page.wait_for_url(f"**/{fragment}**", timeout=timeout)
