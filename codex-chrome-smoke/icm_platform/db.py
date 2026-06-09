from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from icm_platform.paths import DATA_DIR, DB_PATH


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            create table if not exists requirements (
              id integer primary key autoincrement,
              title text not null,
              document text not null,
              status text not null,
              created_at text not null,
              updated_at text not null
            );

            create table if not exists test_points (
              id integer primary key autoincrement,
              requirement_id integer,
              name text not null,
              category text not null,
              priority text not null,
              status text not null,
              created_at text not null,
              foreign key(requirement_id) references requirements(id)
            );

            create table if not exists run_tasks (
              id text primary key,
              mode text not null,
              case_id text,
              status text not null,
              command text not null,
              started_at text,
              finished_at text,
              created_at text not null,
              return_code integer,
              report_path text,
              error text
            );

            create table if not exists run_logs (
              id integer primary key autoincrement,
              run_id text not null,
              stream text not null,
              line text not null,
              created_at text not null,
              foreign key(run_id) references run_tasks(id)
            );

            create table if not exists ai_settings (
              id integer primary key check (id = 1),
              provider text not null,
              base_url text not null,
              model text not null,
              api_key text not null,
              updated_at text not null
            );

            create table if not exists case_drafts (
              id integer primary key autoincrement,
              requirement_id integer not null,
              title text not null,
              yaml text not null,
              status text not null,
              created_at text not null,
              updated_at text not null,
              foreign key(requirement_id) references requirements(id)
            );

            create table if not exists report_analyses (
              id integer primary key autoincrement,
              run_id text not null,
              report_hash text not null,
              provider text not null,
              model text not null,
              analysis_json text not null,
              created_at text not null,
              updated_at text not null,
              unique(run_id, report_hash, provider, model)
            );

            create table if not exists report_analysis_versions (
              id integer primary key autoincrement,
              run_id text not null,
              report_hash text not null,
              provider text not null,
              model text not null,
              analysis_json text not null,
              created_at text not null
            );

            create table if not exists platform_settings (
              id integer primary key check (id = 1),
              runner_json text not null,
              asset_policy_json text not null,
              environment_json text,
              accounts_json text,
              updated_at text not null
            );
            """
        )
        ensure_column(conn, "requirements", "analysis_summary", "text")
        ensure_column(conn, "requirements", "risk_summary", "text")
        ensure_column(conn, "requirements", "case_count", "integer default 0")
        ensure_column(conn, "test_points", "description", "text")
        ensure_column(conn, "test_points", "parent_id", "integer")
        ensure_column(conn, "test_points", "sort_order", "integer")
        ensure_column(conn, "test_points", "module", "text")
        ensure_column(conn, "test_points", "source", "text")
        ensure_column(conn, "test_points", "updated_at", "text")
        ensure_column(conn, "case_drafts", "template", "text")
        ensure_column(conn, "case_drafts", "source_test_point_ids", "text")
        ensure_column(conn, "case_drafts", "promoted_case_id", "text")
        ensure_column(conn, "case_drafts", "promoted_path", "text")
        ensure_column(conn, "case_drafts", "error", "text")
        ensure_column(conn, "platform_settings", "environment_json", "text")
        ensure_column(conn, "platform_settings", "accounts_json", "text")
        backfill_test_point_mindmap_columns(conn)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {definition}")


def backfill_test_point_mindmap_columns(conn: sqlite3.Connection) -> None:
    now = utc_now()
    conn.execute("update test_points set sort_order = id where sort_order is null")
    conn.execute("update test_points set source = 'ai_generated' where source is null or source = ''")
    conn.execute("update test_points set updated_at = coalesce(created_at, ?) where updated_at is null or updated_at = ''", (now,))
    conn.execute(
        """
        update test_points
        set module = coalesce(
          nullif(module, ''),
          (select nullif(r.title, '') from requirements r where r.id = test_points.requirement_id),
          '未归属模块'
        )
        where module is null or module = ''
        """
    )


def default_ai_settings() -> dict[str, Any]:
    return {
        "provider": "minimax-m3",
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M3",
        "api_key": "",
    }


def default_platform_settings() -> dict[str, Any]:
    return {
        "runner": {
            "browser_mode": "background",
            "queue_mode": "serial",
            "batch_range": "TC-ICM-001..TC-ICM-012",
            "screenshot_policy": "latest_plus_failed_archive",
            "headless": True,
        },
        "asset_policy": {
            "observed_asset_enabled": True,
            "allow_passed_run_merge": True,
            "merge_strategy": "conservative",
            "require_verified_before_regression": True,
        },
        "environment": {
            "icm_base_url": "https://192.168.16.203:49187",
            "icm_login_url": "https://192.168.16.203:49187/#/login?redirect=%2Fredirect",
            "dev_portal_base_url": "https://dev.tcsoft.net.cn",
            "dev_login_url": "https://dev.tcsoft.net.cn/login?redirect=%2Fredirect",
            "remote_help_url": "https://dev.tcsoft.net.cn/hubble/remoteHelpInfo",
        },
        "accounts": {
            "labo": {"username": "labo", "password": "11111"},
            "jesse": {"username": "jesse", "password": "123456"},
            "tester": {"username": "Tester", "password": "123456"},
            "admin": {"username": "admin", "password": "Hubble_Service!1088"},
        },
    }


def get_platform_settings(mask_secrets: bool = True) -> dict[str, Any]:
    defaults = default_platform_settings()
    with connect() as conn:
        row = conn.execute("select * from platform_settings where id = 1").fetchone()
    if not row:
        data = {**defaults, "updated_at": None}
        return mask_platform_settings(data) if mask_secrets else data
    row_keys = set(row.keys())
    runner = json_object(row["runner_json"])
    asset_policy = json_object(row["asset_policy_json"])
    environment = json_object(row["environment_json"]) if "environment_json" in row_keys else {}
    accounts = json_object(row["accounts_json"]) if "accounts_json" in row_keys else {}
    data = {
        "runner": normalize_runner_settings({**defaults["runner"], **runner}),
        "asset_policy": {**defaults["asset_policy"], **asset_policy},
        "environment": {**defaults["environment"], **environment},
        "accounts": merge_accounts(defaults["accounts"], accounts),
        "updated_at": row["updated_at"],
    }
    return mask_platform_settings(data) if mask_secrets else data


def json_object(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def save_platform_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = get_platform_settings(mask_secrets=False)
    defaults = default_platform_settings()
    runner = normalize_runner_settings({**defaults["runner"], **current.get("runner", {}), **(payload.get("runner") or {})})
    asset_policy = {
        **defaults["asset_policy"],
        **current.get("asset_policy", {}),
        **(payload.get("asset_policy") or {}),
    }
    environment = {**defaults["environment"], **current.get("environment", {}), **(payload.get("environment") or {})}
    accounts = merge_accounts(
        merge_accounts(defaults["accounts"], current.get("accounts", {})),
        payload.get("accounts") or {},
    )
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            insert into platform_settings(id, runner_json, asset_policy_json, environment_json, accounts_json, updated_at)
            values (1, ?, ?, ?, ?, ?)
            on conflict(id) do update set
              runner_json = excluded.runner_json,
              asset_policy_json = excluded.asset_policy_json,
              environment_json = excluded.environment_json,
              accounts_json = excluded.accounts_json,
              updated_at = excluded.updated_at
            """,
            (
                json.dumps(runner, ensure_ascii=False),
                json.dumps(asset_policy, ensure_ascii=False),
                json.dumps(environment, ensure_ascii=False),
                json.dumps(accounts, ensure_ascii=False),
                now,
            ),
        )
    return get_platform_settings(mask_secrets=True)


def normalize_runner_settings(settings: dict[str, Any]) -> dict[str, Any]:
    browser_mode = settings.get("browser_mode") or "background"
    normalized = {**settings, "browser_mode": browser_mode}
    normalized["headless"] = browser_mode == "background"
    return normalized


def merge_accounts(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in sorted(set(base) | set(patch)):
        current = dict(base.get(key) or {})
        incoming = dict(patch.get(key) or {})
        username = incoming.get("username") or current.get("username") or key
        password = incoming.get("password") if incoming.get("password") not in (None, "") else current.get("password", "")
        merged[key] = {"username": username, "password": password}
    return merged


def mask_platform_settings(data: dict[str, Any]) -> dict[str, Any]:
    accounts = {}
    for key, value in (data.get("accounts") or {}).items():
        password = value.get("password", "")
        accounts[key] = {
            "username": value.get("username", ""),
            "has_password": bool(password),
            "password_masked": f"****{password[-4:]}" if password else "",
        }
    return {**data, "accounts": accounts}


def save_ai_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = get_ai_settings(mask_key=False)
    merged = {
        **default_ai_settings(),
        **current,
        "provider": payload.get("provider") or "minimax-m3",
        "base_url": payload.get("base_url") or current.get("base_url") or default_ai_settings()["base_url"],
        "model": payload.get("model") or current.get("model") or default_ai_settings()["model"],
    }
    if payload.get("api_key") is not None:
        merged["api_key"] = payload.get("api_key") or ""
    elif merged["provider"] == "ollama-local":
        merged["api_key"] = ""
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            insert into ai_settings(id, provider, base_url, model, api_key, updated_at)
            values (1, ?, ?, ?, ?, ?)
            on conflict(id) do update set
              provider = excluded.provider,
              base_url = excluded.base_url,
              model = excluded.model,
              api_key = excluded.api_key,
              updated_at = excluded.updated_at
            """,
            (merged["provider"], merged["base_url"], merged["model"], merged["api_key"], now),
        )
    return get_ai_settings(mask_key=True)


def get_ai_settings(mask_key: bool = True) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("select * from ai_settings where id = 1").fetchone()
    data = {**default_ai_settings(), **(dict(row) if row else {})}
    if not mask_key:
        return data
    api_key = data.get("api_key", "")
    return {
        "provider": data["provider"],
        "base_url": data["base_url"],
        "model": data["model"],
        "has_api_key": bool(api_key),
        "api_key_masked": f"****{api_key[-4:]}" if api_key else "",
        "updated_at": data.get("updated_at"),
    }
