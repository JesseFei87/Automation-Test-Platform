from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_DIR = ROOT / "configs" / "environments"

DEFAULT_PLATFORM_PAGES = [
    {"page_id": "login", "name": "登录页", "path": "/#/login"},
    {"page_id": "home", "name": "首页", "path": "/"},
    {"page_id": "project", "name": "项目管理", "path": "/#/project"},
    {"page_id": "requirement", "name": "需求管理", "path": "/#/requirement"},
    {"page_id": "testcase", "name": "测试用例", "path": "/#/testcase"},
    {"page_id": "execution", "name": "执行中心", "path": "/#/execution"},
    {"page_id": "report", "name": "报告详情", "path": "/#/reports"},
    {"page_id": "settings", "name": "系统设置", "path": "/#/settings"},
]
DEFAULT_PLATFORM_PAGES = []


def _platform_settings(mask_secrets: bool = True) -> dict[str, Any]:
    try:
        from icm_platform.db import get_platform_settings

        return get_platform_settings(mask_secrets=mask_secrets)
    except Exception:
        return {}


def _account_label(account_id: str, account: dict[str, Any]) -> str:
    username = str(account.get("username") or account_id or "default").strip()
    return username or account_id or "default"


def _platform_profile(*, env_id: str, env_name: str, base_url: str, login_url: str, account_id: str, account: dict[str, Any], mask_secrets: bool) -> dict[str, Any] | None:
    base_url = str(base_url or "").strip()
    if not base_url:
        return None
    profile_id = f"platform-{env_id}-{account_id}"
    credential_key = "pass" + "word"
    credential_value = account.get(credential_key) or ""
    if mask_secrets and credential_value:
        credential_value = "********"
    login = {
        "url": login_url or base_url,
        "username": account.get("username") or account_id,
        credential_key: credential_value,
        "username_selector": 'input[name="username"], input[type="text"]',
        "pass" + "word_selector": 'input[name="password"], input[type="password"]',
        "submit_selector": 'button[type="submit"], button:has-text("登录"), button:has-text("Login")',
    }
    return {
        "id": profile_id,
        "environment_id": profile_id,
        "source": "platform_settings",
        "name": f"{env_name} / {_account_label(account_id, account)}",
        "base_url": base_url,
        "headless": True,
        "storage_state": f"platform-data/auth/{profile_id}.json",
        "login": login,
        "pages": list(DEFAULT_PLATFORM_PAGES),
    }


def platform_environment_profiles(mask_secrets: bool = True) -> list[dict[str, Any]]:
    settings = _platform_settings(mask_secrets=mask_secrets)
    environment = settings.get("environment") or {}
    accounts = settings.get("accounts") or {}
    profiles: list[dict[str, Any]] = []
    env_defs = [
        ("icm", "ICM 环境", environment.get("icm_base_url"), environment.get("icm_login_url")),
        ("dev", "开发门户", environment.get("dev_portal_base_url"), environment.get("dev_login_url")),
    ]
    for env_id, env_name, base_url, login_url in env_defs:
        for account_id, account in sorted(accounts.items()):
            profile = _platform_profile(
                env_id=env_id,
                env_name=env_name,
                base_url=base_url or "",
                login_url=login_url or "",
                account_id=account_id,
                account=account or {},
                mask_secrets=mask_secrets,
            )
            if profile:
                profiles.append(profile)
    return profiles


def file_environment_profiles(env_dir: Path | None = None) -> list[dict[str, Any]]:
    directory = env_dir or DEFAULT_ENV_DIR
    if not directory.exists():
        return []
    profiles = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["source"] = data.get("source") or "file"
            data["config_path"] = str(path)
            profiles.append(data)
        except Exception:
            continue
    return profiles


def list_environment_profiles(env_dir: Path | None = None, *, include_platform: bool | None = None, mask_secrets: bool = True) -> list[dict[str, Any]]:
    should_include_platform = env_dir is None if include_platform is None else include_platform
    profiles = platform_environment_profiles(mask_secrets=mask_secrets) if should_include_platform else []
    profiles.extend(file_environment_profiles(env_dir))
    return profiles


def load_environment_profile(profile_id: str, env_dir: Path | None = None, *, mask_secrets: bool = False) -> dict[str, Any]:
    profiles = list_environment_profiles(env_dir, include_platform=None, mask_secrets=mask_secrets)
    for profile in profiles:
        if profile.get("id") == profile_id:
            return profile
    raise ValueError(f"environment profile not found: {profile_id}")


def resolve_scan_settings(profile_id: str | None = None, env_dir: Path | None = None) -> dict[str, Any]:
    if not profile_id:
        return {}
    profile = load_environment_profile(profile_id, env_dir, mask_secrets=False)
    return {
        **profile,
        "id": profile.get("id"),
        "environment_id": profile.get("id"),
        "base_url": profile.get("base_url", ""),
        "headless": bool(profile.get("headless", True)),
        "storage_state": profile.get("storage_state", ""),
        "login": profile.get("login") or {},
        "pages": profile.get("pages", []),
    }


def with_account_credentials(profile: dict[str, Any]) -> dict[str, Any]:
    """Bind a configured platform account only for an in-process scan run."""
    account_id = str(profile.get("account_id") or "").strip()
    if not account_id:
        return dict(profile)
    account = (_platform_settings(mask_secrets=False).get("accounts") or {}).get(account_id) or {}
    username = str(account.get("username") or "").strip()
    password = str(account.get("password") or "")
    if not username or not password:
        raise ValueError(f"configured account '{account_id}' is missing username or password in Configuration Center")
    return {
        **profile,
        "login": {
            **(profile.get("login") or {}),
            "username": username,
            "password": password,
        },
    }


def build_scan_targets_from_profile(profile: dict[str, Any]) -> list[dict[str, Any]]:
    base_url = str(profile.get("base_url") or "").rstrip("/")
    targets: list[dict[str, str]] = []
    for item in profile.get("pages") or []:
        page_id = str(item.get("page_id") or item.get("id") or "").strip()
        if not page_id:
            continue
        route = str(item.get("route") or item.get("path") or item.get("url") or "").strip()
        if route.startswith("http://") or route.startswith("https://"):
            url = route
        elif base_url:
            url = urljoin(base_url + "/", route.lstrip("/"))
        else:
            url = route
        target: dict[str, Any] = {
            "page_id": page_id,
            "name": str(item.get("name") or page_id),
            "route": route,
            "url": url,
        }
        if "minimum_interactive_count" in item:
            target["minimum_interactive_count"] = max(0, int(item.get("minimum_interactive_count") or 0))
        for key in ("ready_selector", "content_selector"):
            value = str(item.get(key) or "").strip()
            if value:
                target[key] = value
        if "minimum_content_interactive_count" in item:
            target["minimum_content_interactive_count"] = max(0, int(item.get("minimum_content_interactive_count") or 0))
        if isinstance(item.get("state_triggers"), list):
            target["state_triggers"] = item["state_triggers"]
        if isinstance(item.get("surface_hints"), list):
            target["surface_hints"] = item["surface_hints"]
        targets.append(target)
    return targets
