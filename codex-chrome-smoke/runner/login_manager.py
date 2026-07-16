from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from runner.browser import relaunch_context

ROOT = Path(__file__).resolve().parents[1]
AUTH_STATE_DIR = ROOT / "platform-data" / "auth"
ACCOUNT_PRIORITY = ("tester", "admin", "labo", "jesse")
LOGIN_NAVIGATION_TIMEOUT_MS = 8000
LOGIN_SUCCESS_TIMEOUT_MS = 3000
LOGIN_STATE_SETTLE_TIMEOUT_MS = 500


def _resolve_env_ref(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("[ENV:") and text.endswith("]"):
        return os.environ.get(text[5:-1].strip(), "")
    return text


def _absolute_url(base_url: str, url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not base_url:
        return url
    return urljoin(base_url.rstrip("/") + "/", url.lstrip("/"))


def _login_check_url(profile: dict[str, Any]) -> str:
    login = profile.get("login") or {}
    explicit = str(login.get("check_url") or login.get("success_url") or "").strip()
    if explicit:
        return explicit
    for item in profile.get("pages") or []:
        route = str(item.get("url") or item.get("route") or item.get("path") or "").strip()
        page_id = str(item.get("page_id") or item.get("id") or "").lower()
        if route and "login" not in route.lower() and "login" not in page_id:
            return route
    return ""


def _looks_like_login_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return "login" in lowered or "redirect=%2fredirect" in lowered


def resolve_storage_state_path(profile: dict[str, Any]) -> Path | None:
    value = str(profile.get("storage_state") or "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def storage_state_exists(path: str | Path | None) -> bool:
    if not path:
        return False
    return Path(path).exists()


def legacy_storage_state_candidates(profile: dict[str, Any]) -> list[Path]:
    login = profile.get("login") or {}
    username = str(login.get("username") or "").strip()
    candidates: list[Path] = []
    if username:
        for account_name in ACCOUNT_PRIORITY:
            candidates.append(AUTH_STATE_DIR / f"icm-internal_{account_name}_{username}.json")
    candidates.extend(sorted(AUTH_STATE_DIR.glob("icm-internal_*.json")) if AUTH_STATE_DIR.exists() else [])
    return candidates


def existing_storage_state_for_profile(profile: dict[str, Any]) -> Path | None:
    configured = resolve_storage_state_path(profile)
    if configured:
        return configured if configured.exists() else None
    for candidate in legacy_storage_state_candidates(profile):
        if candidate.exists():
            return candidate
    return None


def _selector_candidates(selector: str) -> list[str]:
    return [item.strip() for item in str(selector or "").split(",") if item.strip()]


async def _first_visible_locator(page: Any, selector: str):
    last_error: Exception | None = None
    for candidate in _selector_candidates(selector):
        locator = page.locator(candidate).first
        try:
            await locator.wait_for(state="visible", timeout=LOGIN_SUCCESS_TIMEOUT_MS)
            return locator
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"no visible element found for selector: {selector}") from last_error


async def _fill_first_visible(page: Any, selector: str, value: str) -> None:
    locator = await _first_visible_locator(page, selector)
    await locator.fill(value)


async def _click_first_visible(page: Any, selector: str) -> None:
    locator = await _first_visible_locator(page, selector)
    await locator.click()


def has_login_config(profile: dict[str, Any]) -> bool:
    login = profile.get("login") or {}
    return bool(login.get("url") or profile.get("login_url"))


async def login_by_profile(page: Any, profile: dict[str, Any]) -> bool:
    """Execute a generic login flow from an environment profile.

    Secrets should be referenced through environment placeholders such as
    ``[ENV:QA_PASSWORD]`` or explicit ``password_env`` fields instead of being
    stored directly in configuration files.
    """
    login = profile.get("login") or {}
    url = str(login.get("url") or profile.get("login_url") or "").strip()
    if not url:
        return False

    base_url = str(profile.get("base_url") or "").strip()
    username_env = str(login.get("username_env") or "").strip()
    password_env = str(login.get("password_env") or "").strip()
    username = os.environ.get(username_env, "") if username_env else _resolve_env_ref(login.get("username"))
    password = os.environ.get(password_env, "") if password_env else _resolve_env_ref(login.get("password"))
    username_selector = str(login.get("username_selector") or 'input[name="username"]')
    password_selector = str(login.get("password_selector") or 'input[name="password"]')
    submit_selector = str(login.get("submit_selector") or 'button[type="submit"]')
    success_url_contains = str(login.get("success_url_contains") or "").strip()
    success_text = str(login.get("success_text") or "").strip()

    if not username or not password:
        raise RuntimeError("automatic login requires non-empty username and password")

    await page.goto(_absolute_url(base_url, url), wait_until="domcontentloaded", timeout=LOGIN_NAVIGATION_TIMEOUT_MS)
    await _fill_first_visible(page, username_selector, username)
    await _fill_first_visible(page, password_selector, password)
    await _click_first_visible(page, submit_selector)
    if success_url_contains:
        try:
            await page.wait_for_function(
                "expected => window.location.href.includes(expected)",
                arg=success_url_contains,
                timeout=LOGIN_SUCCESS_TIMEOUT_MS,
            )
        except Exception:
            return False
    if success_text:
        try:
            await page.get_by_text(success_text).wait_for(timeout=LOGIN_SUCCESS_TIMEOUT_MS)
        except Exception:
            return False
    return True


async def is_login_state_valid(page: Any, profile: dict[str, Any]) -> bool:
    login = profile.get("login") or {}
    base_url = str(profile.get("base_url") or "").strip()
    check_url = _login_check_url(profile)
    success_url_contains = str(login.get("success_url_contains") or "").strip()
    success_text = str(login.get("success_text") or "").strip()

    if not check_url and not success_url_contains and not success_text:
        return True

    if check_url:
        await page.goto(_absolute_url(base_url, check_url), wait_until="domcontentloaded", timeout=LOGIN_NAVIGATION_TIMEOUT_MS)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=LOGIN_SUCCESS_TIMEOUT_MS)
        except Exception:
            pass
        if hasattr(page, "wait_for_timeout"):
            await page.wait_for_timeout(LOGIN_STATE_SETTLE_TIMEOUT_MS)

    current_url = str(getattr(page, "url", ""))
    if success_url_contains and success_url_contains not in current_url:
        return False
    if _looks_like_login_url(current_url):
        return False
    if success_text:
        try:
            await page.get_by_text(success_text).wait_for(timeout=LOGIN_SUCCESS_TIMEOUT_MS)
        except Exception:
            return False
    return bool(check_url or success_url_contains or success_text)


async def save_storage_state_for_profile(context: Any, profile: dict[str, Any]) -> Path | None:
    path = resolve_storage_state_path(profile)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(path))
    return path


async def ensure_storage_state_for_profile(session: Any, profile: dict[str, Any], *, progress_callback=None) -> Path | None:
    path = resolve_storage_state_path(profile)
    existing = existing_storage_state_for_profile(profile)
    if existing:
        await relaunch_context(session, profile, storage_state=str(existing), reuse_storage_state=False)
        if progress_callback:
            progress_callback({"stage": "storage_state_loaded", "storage_state": str(existing)})
        if await is_login_state_valid(session.page, profile):
            if progress_callback:
                progress_callback({"stage": "storage_state_reused", "storage_state": str(existing)})
            return existing
        if progress_callback:
            progress_callback({"stage": "storage_state_invalid", "storage_state": str(existing)})
    if not has_login_config(profile):
        if progress_callback:
            progress_callback({"stage": "login_skipped", "reason": "no_login_config"})
        return None
    if progress_callback:
        progress_callback({"stage": "auto_login_started", "storage_state": str(path) if path else ""})
    ok = await login_by_profile(session.page, profile)
    if not ok:
        if progress_callback:
            progress_callback({"stage": "auto_login_failed", "storage_state": str(path) if path else "", "error": "configured login success condition was not reached"})
        raise RuntimeError("automatic login failed: configured login success condition was not reached")
    saved = await save_storage_state_for_profile(session.context, profile)
    if progress_callback:
        progress_callback({"stage": "storage_state_saved", "storage_state": str(saved) if saved else ""})
    return saved
