from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from icm_platform import api as api_module
from icm_platform import db


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def wait_task_done(task_id: str, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    latest = api_module._element_refresh_task_payload(task_id)
    while time.time() < deadline:
        latest = api_module._element_refresh_task_payload(task_id)
        if latest["status"] in {"done", "failed"}:
            break
        time.sleep(0.05)
    return latest


def test_element_knowledge_payload_reads_library_and_summary(tmp_path):
    library_path = tmp_path / "library.json"
    summary_path = tmp_path / "refresh-summary.json"
    write_json(
        library_path,
        {
            "elements": [
                {
                    "element_id": "users.create_button",
                    "failed_count": 2,
                    "success_rate": 0.5,
                    "healing_issue": "target_not_visible",
                    "healing_suggestion": "Scroll first.",
                }
            ],
            "pages": [{"page_id": "users"}],
        },
    )
    write_json(
        summary_path,
        {
            "element_count": 1,
            "page_count": 1,
            "feedback_record_count": 3,
            "feedback_stat_count": 1,
            "healing_suggestion_count": 1,
            "elements_with_feedback": 1,
            "elements_with_healing": 1,
            "markdown_report_path": "refresh-report.md",
            "html_report_path": "refresh-report.html",
        },
    )

    with patch.object(api_module, "ELEMENT_LIBRARY_PATH", library_path), patch.object(api_module, "ELEMENT_SUMMARY_PATH", summary_path):
        payload = api_module._element_knowledge_payload()

    assert payload["exists"] == {"library": True, "summary": True}
    assert payload["summary"]["element_count"] == 1
    assert payload["hotspots"][0]["element_id"] == "users.create_button"
    assert payload["report_paths"] == {"markdown": "refresh-report.md", "html": "refresh-report.html"}


def test_post_element_knowledge_refresh_accepts_scan_mode_payload(monkeypatch):
    calls = []

    def fake_start(**kwargs):
        calls.append(kwargs)
        return {"id": "ekr-test", "status": "queued", "mode": "element-knowledge-refresh", "logs": []}

    monkeypatch.setattr(api_module, "_start_element_refresh_task", fake_start)

    task = api_module.post_element_knowledge_refresh(
        api_module.ElementKnowledgeRefreshRequest(
            no_scan=False,
            base_url="http://localhost:5173",
            include_states=True,
            headless=True,
            min_healing_failures=2,
        )
    )

    assert task["id"] == "ekr-test"
    assert calls == [
        {
            "no_scan": False,
            "min_healing_failures": 2,
            "base_url": "http://localhost:5173",
            "environment_id": None,
            "target_url": "",
            "target_page_id": "",
            "target_name": "",
            "include_states": True,
            "headless": True,
        }
    ]


def test_start_element_refresh_task_runs_no_scan_in_background(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    data_dir = tmp_path / "data"
    summary = {
        "element_count": 2,
        "healing_suggestion_count": 1,
        "html_report_path": str(tmp_path / "refresh-report.html"),
    }

    with patch.object(db, "DB_PATH", db_path), patch.object(db, "DATA_DIR", data_dir), patch.object(api_module, "refresh_library_file", return_value=summary):
        db.init_db()
        task = api_module._start_element_refresh_task(no_scan=True, min_healing_failures=2)
        assert task["id"].startswith("ekr-")
        assert task["mode"] == "element-knowledge-refresh"
        assert task["status"] in {"queued", "running", "done"}

        latest = wait_task_done(task["id"])

        assert latest["status"] == "done"
        assert latest["return_code"] == 0
        assert latest["report_path"] == summary["html_report_path"]
        assert any("refresh completed" in log["line"] for log in latest["logs"])


def test_post_element_knowledge_refresh_accepts_single_target_payload(monkeypatch):
    calls = []

    def fake_start(**kwargs):
        calls.append(kwargs)
        return {"id": "ekr-target", "status": "queued", "mode": "element-knowledge-refresh", "logs": []}

    monkeypatch.setattr(api_module, "_start_element_refresh_task", fake_start)

    task = api_module.post_element_knowledge_refresh(
        api_module.ElementKnowledgeRefreshRequest(
            no_scan=False,
            target_url="https://example.test/#/login",
            target_page_id="login",
            target_name="被测系统登录页",
            include_states=True,
            headless=True,
        )
    )

    assert task["id"] == "ekr-target"
    assert calls[0]["target_url"] == "https://example.test/#/login"
    assert calls[0]["target_page_id"] == "login"
    assert calls[0]["target_name"] == "被测系统登录页"
    assert calls[0]["base_url"] == ""
    assert calls[0]["environment_id"] is None


def test_start_element_refresh_task_runs_scan_in_background(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    data_dir = tmp_path / "data"
    summary = {
        "element_count": 8,
        "healing_suggestion_count": 2,
        "html_report_path": str(tmp_path / "scan-report.html"),
    }

    async def fake_scan_element_knowledge_async(**kwargs):
        assert kwargs["base_url"] == "http://localhost:5173"
        assert kwargs["include_states"] is True
        assert kwargs["headless"] is True
        assert kwargs["min_healing_failures"] == 2
        assert kwargs["environment_id"] is None
        assert kwargs["target_url"] is None
        assert kwargs["target_page_id"] is None
        assert kwargs["target_name"] is None
        assert callable(kwargs["progress_callback"])
        return summary

    with patch.object(db, "DB_PATH", db_path), patch.object(db, "DATA_DIR", data_dir), patch.object(api_module, "_scan_element_knowledge_async", fake_scan_element_knowledge_async):
        db.init_db()
        task = api_module._start_element_refresh_task(
            no_scan=False,
            base_url="http://localhost:5173",
            include_states=True,
            headless=True,
            min_healing_failures=2,
        )
        latest = wait_task_done(task["id"])

        assert latest["status"] == "done"
        assert latest["report_path"] == summary["html_report_path"]
        assert latest["progress"]["stage"] == "refresh_completed"
        assert latest["progress"]["element_count"] == 8
        assert any("browser scan started" in log["line"] for log in latest["logs"])


def test_element_refresh_payload_extracts_latest_progress(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    data_dir = tmp_path / "data"
    with patch.object(db, "DB_PATH", db_path), patch.object(db, "DATA_DIR", data_dir):
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                """
                insert into run_tasks(id, mode, status, command, created_at)
                values ('ekr-progress', 'element-knowledge-refresh', 'running', 'internal', '2026-07-09T00:00:00Z')
                """
            )
        api_module._append_element_refresh_progress("ekr-progress", {"stage": "scanning_page", "current_page": "login", "page_index": 1, "page_total": 8})
        api_module._append_element_refresh_progress("ekr-progress", {"stage": "page_scanned", "current_page": "login", "element_count": 12, "high_risk_count": 1})
        payload = api_module._element_refresh_task_payload("ekr-progress")

    assert payload["progress"]["stage"] == "page_scanned"
    assert payload["progress"]["current_page"] == "login"
    assert payload["progress"]["element_count"] == 12
    assert payload["progress"]["high_risk_count"] == 1


def test_element_environment_preview_reports_storage_state(tmp_path):
    storage_state = tmp_path / "state.json"
    storage_state.write_text("{}", encoding="utf-8")
    profile = {
        "id": "env-a",
        "name": "环境A",
        "base_url": "http://example.com",
        "storage_state": str(storage_state),
        "login": {"url": "http://example.com/login"},
        "pages": [{"page_id": "home"}],
    }

    payload = api_module._element_environment_preview(profile)

    assert payload["login_configured"] is True
    assert payload["page_count"] == 1
    assert payload["storage_state_exists"] is True
    assert payload["storage_state_path"] == str(storage_state)
    assert payload["storage_state_updated_at"]


def test_element_knowledge_environments_only_returns_profiles_with_pages(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "list_environment_profiles",
        lambda: [
            {"id": "platform-icm-admin", "pages": []},
            {"id": "dev", "pages": [{"page_id": "home", "path": "/"}]},
            {"id": "icm-tested", "element_knowledge_scan_enabled": True, "pages": [{"page_id": "home", "path": "/#/index"}]},
        ],
    )

    assert api_module.get_element_knowledge_environments() == [
        {"id": "icm-tested", "element_knowledge_scan_enabled": True, "pages": [{"page_id": "home", "path": "/#/index"}]}
    ]


def test_scan_refresh_without_base_url_fails(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    data_dir = tmp_path / "data"
    with patch.object(db, "DB_PATH", db_path), patch.object(db, "DATA_DIR", data_dir):
        db.init_db()
        task = api_module._start_element_refresh_task(no_scan=False, base_url="", include_states=False, headless=True)
        latest = wait_task_done(task["id"])

    assert latest["status"] == "failed"
    assert "base_url, environment_id or target_url is required" in latest["error"]


def test_environment_scan_without_page_list_fails(monkeypatch):
    async def fake_launch_browser(**kwargs):
        class Session:
            page = object()

        return Session()

    async def fake_close_browser(_session):
        return None

    async def fake_ensure_storage_state_for_profile(*args, **kwargs):
        return None

    monkeypatch.setattr(api_module, "resolve_scan_settings", lambda _environment_id: {"id": "env-empty", "base_url": "http://example.com", "pages": []})
    monkeypatch.setattr(api_module, "launch_browser", fake_launch_browser)
    monkeypatch.setattr(api_module, "close_browser", fake_close_browser)
    monkeypatch.setattr(api_module, "ensure_storage_state_for_profile", fake_ensure_storage_state_for_profile)

    with pytest.raises(ValueError, match="environment page list is empty"):
        asyncio.run(
            api_module._scan_element_knowledge_async(
                base_url="",
                include_states=False,
                headless=True,
                min_healing_failures=1,
                environment_id="env-empty",
            )
        )


def test_environment_scan_attaches_authenticated_cdp_browser(monkeypatch):
    calls = []
    profile = {
        "id": "icm-tested",
        "base_url": "https://example.test",
        "auth_mode": "cdp_attach",
        "cdp_endpoint": "http://127.0.0.1:9222",
        "pages": [{"page_id": "home", "path": "/#/index"}],
    }

    async def fake_attach(endpoint):
        calls.append(("attach", endpoint))
        return type("Session", (), {"page": object()})()

    async def fake_valid(page, received_profile):
        calls.append(("validate", received_profile["id"]))
        return True

    async def fake_refresh(**kwargs):
        calls.append(("refresh", kwargs["targets"][0]["page_id"], kwargs["preserve_unscanned_pages"]))
        return {"element_count": 1, "page_count": 1}

    async def fake_close(session):
        calls.append(("close", None))

    monkeypatch.setattr(api_module, "resolve_scan_settings", lambda _environment_id: profile)
    monkeypatch.setattr(api_module, "_ensure_dedicated_cdp_browser", lambda endpoint: calls.append(("ensure_cdp", endpoint)) or "reused")
    monkeypatch.setattr(api_module, "attach_browser_over_cdp", fake_attach)
    monkeypatch.setattr(api_module, "is_login_state_valid", fake_valid)
    monkeypatch.setattr(api_module, "refresh_element_knowledge", fake_refresh)
    monkeypatch.setattr(api_module, "close_browser", fake_close)

    result = asyncio.run(
        api_module._scan_element_knowledge_async(
            base_url="",
            include_states=False,
            headless=True,
            min_healing_failures=1,
            environment_id="icm-tested",
        )
    )

    assert result["element_count"] == 1
    assert calls == [
        ("ensure_cdp", "http://127.0.0.1:9222"),
        ("attach", "http://127.0.0.1:9222"),
        ("validate", "icm-tested"),
        ("refresh", "home", True),
        ("close", None),
    ]


def test_environment_scan_discovers_routes_before_scanning(monkeypatch):
    calls = []
    profile = {"id": "env", "base_url": "https://example.test", "pages": [{"page_id": "home", "path": "/#/index"}], "auto_discover_routes": True}

    async def fake_launch(**_kwargs):
        class Page:
            async def goto(self, url, wait_until, timeout):
                calls.append(("discovery_entry", url, wait_until, timeout))

        return type("Session", (), {"page": Page()})()

    async def fake_discover(*_args, **_kwargs):
        return [{"page_id": "users", "name": "Users", "route": "#/users", "url": "https://example.test/#/users"}]

    async def fake_refresh(**kwargs):
        calls.append(kwargs["targets"])
        return {"element_count": 2, "page_count": 2}

    async def fake_close(_session):
        return None

    monkeypatch.setattr(api_module, "resolve_scan_settings", lambda _environment_id: profile)
    monkeypatch.setattr(api_module, "launch_browser", fake_launch)
    monkeypatch.setattr(api_module, "ensure_storage_state_for_profile", lambda *_args, **_kwargs: asyncio.sleep(0))
    monkeypatch.setattr(api_module, "discover_routes", fake_discover)
    monkeypatch.setattr(api_module, "refresh_element_knowledge", fake_refresh)
    monkeypatch.setattr(api_module, "close_browser", fake_close)

    asyncio.run(api_module._scan_element_knowledge_async(base_url="", include_states=False, headless=True, min_healing_failures=1, environment_id="env"))

    assert calls[0] == ("discovery_entry", "https://example.test/#/index", "domcontentloaded", 8000)
    assert [target["page_id"] for target in calls[1]] == ["home", "users"]


def test_environment_scan_cdp_requires_authenticated_profile(monkeypatch):
    closed = []

    async def fake_attach(_endpoint):
        return type("Session", (), {"page": object()})()

    async def fake_valid(*_args):
        return False

    async def fake_close(_session):
        closed.append(True)

    monkeypatch.setattr(api_module, "resolve_scan_settings", lambda _environment_id: {"id": "icm-tested", "base_url": "https://example.test", "auth_mode": "cdp_attach", "cdp_endpoint": "http://127.0.0.1:9222", "pages": [{"page_id": "home", "path": "/#/index"}]})
    monkeypatch.setattr(api_module, "_ensure_dedicated_cdp_browser", lambda _endpoint: "reused")
    monkeypatch.setattr(api_module, "attach_browser_over_cdp", fake_attach)
    monkeypatch.setattr(api_module, "is_login_state_valid", fake_valid)
    monkeypatch.setattr(api_module, "close_browser", fake_close)

    with pytest.raises(RuntimeError, match="not authenticated"):
        asyncio.run(
            api_module._scan_element_knowledge_async(
                base_url="",
                include_states=False,
                headless=True,
                min_healing_failures=1,
                environment_id="icm-tested",
            )
        )

    assert closed == [True]


def test_element_validation_uses_auto_login_environment(monkeypatch):
    calls = []
    profile = {
        "id": "icm-tested",
        "base_url": "https://example.test",
        "auth_mode": "auto_login",
        "headless": False,
        "pages": [{"page_id": "home", "path": "/#/index"}],
    }

    async def fake_launch(**kwargs):
        calls.append(("launch", kwargs["headless"], kwargs["system"]["id"], kwargs["reuse_storage_state"]))
        return type("Session", (), {"page": object()})()

    async def fake_login(_session, received_profile, *, progress_callback):
        calls.append(("login", received_profile["id"]))

    async def fake_validate(_page, library, *, page_readiness, progress_callback):
        calls.append(("validate", library["elements"][0]["element_id"], sorted(page_readiness)))
        return {"page_count": 1, "element_count": 1, "summary": {"valid": 1, "invalid": 0, "needs_review": 0}, "output_path": "validation-report.json"}

    async def fake_close(_session):
        calls.append(("close",))

    monkeypatch.setattr(api_module, "resolve_scan_settings", lambda _environment_id: profile)
    monkeypatch.setattr(api_module, "with_account_credentials", lambda received_profile: received_profile)
    monkeypatch.setattr(api_module, "launch_browser", fake_launch)
    monkeypatch.setattr(api_module, "ensure_storage_state_for_profile", fake_login)
    monkeypatch.setattr(api_module, "load_json_file", lambda _path: {"elements": [{"element_id": "home.menu"}]})
    monkeypatch.setattr(api_module, "validate_element_library", fake_validate)
    monkeypatch.setattr(api_module, "close_browser", fake_close)

    result = asyncio.run(api_module._validate_element_library_async("ekv-test", "icm-tested"))

    assert result["summary"]["valid"] == 1
    assert calls == [
        ("launch", False, "icm-tested", True),
        ("login", "icm-tested"),
        ("validate", "home.menu", ["home"]),
        ("close",),
    ]


def test_ensure_dedicated_cdp_browser_starts_chrome_only_when_endpoint_is_absent(monkeypatch, tmp_path):
    calls = []
    readiness = iter([False, True])

    monkeypatch.setattr(api_module, "_cdp_browser_ready", lambda _endpoint: next(readiness))
    monkeypatch.setattr(api_module, "_find_chrome_executable", lambda: tmp_path / "chrome.exe")
    monkeypatch.setattr(api_module, "_DEDICATED_CDP_PROFILE_ROOT", tmp_path / "profile")
    monkeypatch.setattr(api_module.subprocess, "Popen", lambda args, **_kwargs: calls.append(args))
    monkeypatch.setattr(api_module.time, "sleep", lambda _seconds: None)

    assert api_module._ensure_dedicated_cdp_browser("http://127.0.0.1:9222") == "started"
    assert calls[0][1:] == [
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=9222",
        f"--user-data-dir={tmp_path / 'profile'}",
    ]


def test_list_element_knowledge_refresh_tasks_returns_latest(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    data_dir = tmp_path / "data"
    with patch.object(db, "DB_PATH", db_path), patch.object(db, "DATA_DIR", data_dir):
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                """
                insert into run_tasks(id, mode, status, command, created_at)
                values ('ekr-test', 'element-knowledge-refresh', 'done', 'internal', '2026-07-09T00:00:00Z')
                """
            )
        rows = api_module.list_element_knowledge_refresh_tasks()

    assert rows[0]["id"] == "ekr-test"
    assert rows[0]["mode"] == "element-knowledge-refresh"


def test_runs_api_excludes_element_refresh_tasks(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    data_dir = tmp_path / "data"
    with patch.object(db, "DB_PATH", db_path), patch.object(db, "DATA_DIR", data_dir):
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                """
                insert into run_tasks(id, mode, status, command, created_at)
                values ('run-case-001', 'run-case', 'done', 'internal', '2026-07-10T00:00:00Z')
                """
            )
            conn.execute(
                """
                insert into run_tasks(id, mode, status, command, created_at)
                values ('ekr-001', 'element-knowledge-refresh', 'done', 'internal', '2026-07-10T00:01:00Z')
                """
            )

        rows = api_module.runs()

    ids = {row["id"] for row in rows}
    assert "run-case-001" in ids
    assert "ekr-001" not in ids
