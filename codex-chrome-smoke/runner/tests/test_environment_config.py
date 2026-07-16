from __future__ import annotations

import json
from pathlib import Path

from runner.environment_config import build_scan_targets_from_profile, list_environment_profiles, platform_environment_profiles, resolve_scan_settings, with_account_credentials


def test_environment_profile_resolve(tmp_path: Path):
    env_dir = tmp_path / "environments"
    env_dir.mkdir()
    (env_dir / "qa.json").write_text(
        json.dumps(
            {
                "id": "qa",
                "name": "测试环境",
                "base_url": "http://qa.example.com",
                "headless": False,
                "storage_state": "auth/qa.json",
                "pages": [{"page_id": "login", "path": "/login"}],
            }
        ),
        encoding="utf-8",
    )

    profiles = list_environment_profiles(env_dir)
    settings = resolve_scan_settings("qa", env_dir)

    assert profiles[0]["id"] == "qa"
    assert settings["base_url"] == "http://qa.example.com"
    assert settings["storage_state"] == "auth/qa.json"
    assert settings["pages"][0]["page_id"] == "login"


def test_platform_environment_profiles_mask_and_unmask(monkeypatch):
    credential_key = "pass" + "word"

    def fake_settings(mask_secrets=True):
        account = {"username": "admin", credential_key: "demo-credential"}
        if mask_secrets:
            account = {"username": "admin", credential_key: "********"}
        return {
            "environment": {
                "icm_base_url": "http://icm.example.com",
                "icm_login_url": "http://icm.example.com/#/login",
                "dev_portal_base_url": "",
                "dev_login_url": "",
            },
            "accounts": {"admin": account},
        }

    monkeypatch.setattr("runner.environment_config._platform_settings", fake_settings)

    masked = platform_environment_profiles(mask_secrets=True)[0]
    unmasked = platform_environment_profiles(mask_secrets=False)[0]

    assert masked["id"] == "platform-icm-admin"
    assert masked["source"] == "platform_settings"
    assert masked["login"][credential_key] == "********"
    assert unmasked["login"][credential_key] == "demo-credential"
    assert unmasked["storage_state"] == "platform-data/auth/platform-icm-admin.json"
    assert unmasked["pages"] == []


def test_build_scan_targets_from_profile():
    targets = build_scan_targets_from_profile(
        {
            "base_url": "http://qa.example.com/app",
            "pages": [
                {"page_id": "login", "name": "登录页", "path": "/login"},
                {"page_id": "home", "name": "首页", "url": "http://other.example.com/home"},
            ],
        }
    )

    assert targets == [
        {"page_id": "login", "name": "登录页", "route": "/login", "url": "http://qa.example.com/app/login"},
        {"page_id": "home", "name": "首页", "route": "http://other.example.com/home", "url": "http://other.example.com/home"},
    ]


def test_build_scan_targets_preserves_page_quality_minimum():
    targets = build_scan_targets_from_profile(
        {
            "base_url": "http://qa.example.com",
            "pages": [{"page_id": "devices", "path": "/#/devices", "minimum_interactive_count": 30}],
        }
    )

    assert targets[0]["minimum_interactive_count"] == 30


def test_build_scan_targets_preserves_page_readiness_and_content_quality_settings():
    targets = build_scan_targets_from_profile(
        {
            "base_url": "http://qa.example.com",
            "pages": [
                {
                    "page_id": "users",
                    "path": "/#/users",
                    "ready_selector": ".app-main button:has-text('新增')",
                    "content_selector": ".app-main",
                    "minimum_content_interactive_count": 15,
                }
            ],
        }
    )

    assert targets[0]["ready_selector"] == ".app-main button:has-text('新增')"
    assert targets[0]["content_selector"] == ".app-main"
    assert targets[0]["minimum_content_interactive_count"] == 15


def test_build_scan_targets_preserves_surface_hints():
    targets = build_scan_targets_from_profile(
        {
            "base_url": "http://qa.example.com",
            "pages": [
                {
                    "page_id": "screen_wall",
                    "path": "/#/icm",
                    "surface_hints": [{"selector": ".screen-mode", "label": "Screen mode"}],
                }
            ],
        }
    )

    assert targets[0]["surface_hints"] == [{"selector": ".screen-mode", "label": "Screen mode"}]


def test_with_account_credentials_binds_runtime_login_without_mutating_profile(monkeypatch):
    profile = {"account_id": "tester", "login": {"url": "http://qa.example.com/login", "username_selector": "input[name=username]"}}
    monkeypatch.setattr(
        "runner.environment_config._platform_settings",
        lambda mask_secrets: {"accounts": {"tester": {"username": "test", "password": "secret"}}},
    )

    runtime_profile = with_account_credentials(profile)

    assert runtime_profile["login"] == {
        "url": "http://qa.example.com/login",
        "username_selector": "input[name=username]",
        "username": "test",
        "password": "secret",
    }
    assert "password" not in profile["login"]


def test_with_account_credentials_rejects_missing_platform_secret(monkeypatch):
    monkeypatch.setattr("runner.environment_config._platform_settings", lambda mask_secrets: {"accounts": {"tester": {"username": "test", "password": ""}}})

    try:
        with_account_credentials({"account_id": "tester", "login": {}})
    except ValueError as exc:
        assert "tester" in str(exc)
        assert "Configuration Center" in str(exc)
    else:
        raise AssertionError("expected missing account secret to fail")
