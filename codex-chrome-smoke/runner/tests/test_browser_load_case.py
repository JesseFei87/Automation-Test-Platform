from pathlib import Path

import yaml
import pytest

from runner import browser as browser_module


def test_load_case_falls_back_to_source_draft_case_id(tmp_path, monkeypatch):
    case_dir = tmp_path / "test-cases" / "icm"
    case_dir.mkdir(parents=True, exist_ok=True)
    case_path = case_dir / "tc-icm-021-generated.yaml"
    case_path.write_text(
        yaml.safe_dump(
            {
                "id": "TC-ICM-021",
                "title": "填写全部合法字段新增设备信息成功",
                "source_draft_case_id": "ICMDEV_FUN_001",
                "test_data": "连接类型=连接器-1；设备IP=192.168.1.100",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(browser_module, "ROOT", Path(tmp_path))

    loaded = browser_module.load_case("ICMDEV_FUN_001")

    assert loaded["id"] == "TC-ICM-021"
    assert loaded["source_draft_case_id"] == "ICMDEV_FUN_001"


def test_load_system_uses_requested_yaml_and_not_fixed_icm_file(tmp_path, monkeypatch):
    systems_dir = tmp_path / "systems"
    systems_dir.mkdir(parents=True, exist_ok=True)
    (systems_dir / "icm-internal.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "icm-internal",
                "base_url": "https://icm.example",
                "entry_url": "https://icm.example/login",
                "login_url": "https://icm.example/login",
                "credentials": {"username": "admin", "password": "admin"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (systems_dir / "external-template.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "external-template",
                "base_url": "https://example.com",
                "entry_url": "https://example.com",
                "login_url": "https://example.com",
                "credentials": {"username": "", "password": ""},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(browser_module, "SYSTEMS_DIR", systems_dir)
    monkeypatch.setattr(browser_module, "load_platform_runtime_settings", lambda: {})

    loaded = browser_module.load_system("external-template")

    assert loaded["id"] == "external-template"
    assert loaded["base_url"] == "https://example.com"


def test_load_system_applies_case_env_url_for_external_system(tmp_path, monkeypatch):
    systems_dir = tmp_path / "systems"
    systems_dir.mkdir(parents=True, exist_ok=True)
    (systems_dir / "external-template.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "external-template",
                "base_url": "https://example.com",
                "entry_url": "https://example.com",
                "login_url": "https://example.com",
                "credentials": {"username": "", "password": ""},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(browser_module, "SYSTEMS_DIR", systems_dir)
    monkeypatch.setattr(browser_module, "load_platform_runtime_settings", lambda: {})

    loaded = browser_module.load_system(
        "external-template",
        {"context_info": {"env_url": "https://bing.com"}},
    )

    assert loaded["base_url"] == "https://bing.com"
    assert loaded["entry_url"] == "https://bing.com"
    assert loaded["login_url"] == "https://bing.com"


@pytest.mark.asyncio
async def test_is_logged_in_tolerates_external_system_without_login_state_check():
    class _Locator:
        async def count(self):
            return 0

    class _Page:
        url = "https://bing.com"

        def locator(self, _selector):
            return _Locator()

    assert await browser_module.is_logged_in(_Page(), {"id": "external-template"}) is False
