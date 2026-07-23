from __future__ import annotations

import sqlite3
import json
import uuid
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
              batch_case_ids text,
              parent_run_id text,
              trigger text,
              agent_backend text,
              healing_context_path text,
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

            create table if not exists assertion_analyses (
              id integer primary key autoincrement,
              expected_hash text not null,
              provider text not null,
              model text not null,
              assertions_json text not null,
              created_at text not null,
              updated_at text not null,
              unique(expected_hash, provider, model)
            );
            create index if not exists idx_assertion_analyses_hash on assertion_analyses(expected_hash);

            create table if not exists platform_settings (
              id integer primary key check (id = 1),
              runner_json text not null,
              asset_policy_json text not null,
              environment_json text,
              accounts_json text,
              updated_at text not null
            );

            -- 路线 B：每次执行落库（路线 A 也用 case_id 找最新 passed run）
            create table if not exists case_runs (
              id integer primary key autoincrement,
              case_id text not null,
              run_id text not null,
              passed integer not null,
              started_at text not null,
              finished_at text not null,
              attempt integer default 1,
              foreign key(run_id) references run_tasks(id)
            );
            create index if not exists idx_case_runs_case_id on case_runs(case_id);
            create index if not exists idx_case_runs_case_passed on case_runs(case_id, passed);
            create index if not exists idx_case_runs_case_started on case_runs(case_id, started_at desc);

            -- 路线 A：采纳历史
            create table if not exists asset_adoptions (
              id integer primary key autoincrement,
              case_id text not null,
              run_id text not null,
              mode text not null,
              diff_summary_json text,
              adopted_by text,
              adopted_at text not null
            );
            create index if not exists idx_asset_adoptions_case on asset_adoptions(case_id, adopted_at desc);

            -- 路线 B：稳定性扫描任务（先建表，B 路线使用）
            create table if not exists stability_scans (
              id text primary key,
              case_id text not null,
              status text not null,
              times integer not null,
              completed integer default 0,
              passed integer default 0,
              created_at text not null,
              finished_at text
            );
            create index if not exists idx_stability_scans_case on stability_scans(case_id, created_at desc);

            -- P0 · 所属项目下拉化（增量 2026-06-10）
            create table if not exists project_profiles (
              id          text primary key,
              name        text not null unique,
              base_url    text,
              description text,
              created_at  text not null default (datetime('now')),
              updated_at  text not null default (datetime('now'))
            );
            create index if not exists idx_project_profiles_name on project_profiles(name);
            """
        )
        _ensure_project_profiles_table(conn)
        _seed_project_profiles_if_empty(conn)
        ensure_column(conn, "requirements", "analysis_summary", "text")
        ensure_column(conn, "requirements", "risk_summary", "text")
        ensure_column(conn, "requirements", "case_count", "integer default 0")
        ensure_column(conn, "requirements", "project_id", "text")
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
        ensure_column(conn, "run_tasks", "parent_run_id", "text")
        ensure_column(conn, "run_tasks", "batch_case_ids", "text")
        ensure_column(conn, "run_tasks", "trigger", "text")
        ensure_column(conn, "run_tasks", "healing_context_path", "text")
        ensure_column(conn, "run_tasks", "agent_backend", "text")
        ensure_column(conn, "run_tasks", "report_deleted_at", "text")
        ensure_column(conn, "platform_settings", "environment_json", "text")
        ensure_column(conn, "platform_settings", "accounts_json", "text")
        backfill_requirement_project_id(conn)
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


def backfill_requirement_project_id(conn: sqlite3.Connection) -> None:
    icm_project = conn.execute("select id from project_profiles where id = ?", ("proj-icm-default",)).fetchone()
    if not icm_project:
        return
    conn.execute(
        """
        update requirements
        set project_id = 'proj-icm-default'
        where (project_id is null or project_id = '')
          and (
            title like '%ICM%'
            or document like '%ICM%'
            or title like '%登录ICM系统%'
            or document like '%登录ICM系统%'
            or title like '%登录%'
            or document like '%登录%'
          )
        """
    )


# -----------------------------------------------------------------------------
# P0 · 所属项目下拉化（增量 2026-06-10）
# -----------------------------------------------------------------------------

PROJECT_PROFILE_SEED_ROWS: tuple[tuple[str, str, str, str], ...] = (
    # (id, name, base_url, description) — 启动种子，SELECT COUNT(*)=0 时插入
    ("proj-icm-default",   "ICM",   "https://icm.example.com", "请在创建后修改"),
    ("proj-dxone-default", "DxONE", "https://icm.example.com", "请在创建后修改"),
)


def _ensure_project_profiles_table(conn: sqlite3.Connection) -> None:
    """DDL 由 init_db() 内的 executescript 创建；本函数作为幂等兜底（单测 / 手工建表场景）。"""
    conn.executescript(
        """
        create table if not exists project_profiles (
          id          text primary key,
          name        text not null unique,
          base_url    text,
          description text,
          created_at  text not null default (datetime('now')),
          updated_at  text not null default (datetime('now'))
        );
        create index if not exists idx_project_profiles_name on project_profiles(name);
        """
    )


def _seed_project_profiles_if_empty(conn: sqlite3.Connection) -> None:
    """启动种子：表为空时插 2 条（ICM / DxONE，base_url 占位，description 提示"请在创建后修改"）。"""
    count_row = conn.execute("select count(*) as c from project_profiles").fetchone()
    if int(count_row["c"] or 0) > 0:
        return
    now = utc_now()
    for pid, name, base_url, description in PROJECT_PROFILE_SEED_ROWS:
        conn.execute(
            """
            insert or ignore into project_profiles(id, name, base_url, description, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (pid, name, base_url, description, now, now),
        )


def list_project_profiles() -> list[dict[str, Any]]:
    """T2 · GET /api/projects：从 project_profiles 取所有项目档案（按 name 升序稳定排序）。"""
    with connect() as conn:
        rows = conn.execute(
            "select id, name, base_url, description, created_at, updated_at from project_profiles order by name, created_at"
        ).fetchall()
    return [dict(row) for row in rows]


def get_project_profile(project_id: str) -> dict[str, Any] | None:
    """T2 · GET /api/projects/{id}（虽 ARCH §4 未列出，但供 T8 间接验证 409 后回查）。"""
    with connect() as conn:
        row = conn.execute(
            "select id, name, base_url, description, created_at, updated_at from project_profiles where id = ?",
            (project_id,),
        ).fetchone()
    return dict(row) if row else None


def create_project_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """T2 · POST /api/projects：name 必填，UNIQUE 冲突抛 ValueError('conflict')，空值抛 ValueError('invalid')。"""
    name_raw = (payload.get("name") or "").strip()
    if not name_raw:
        raise ValueError("invalid: name is required")
    base_url = (payload.get("base_url") or "").strip() or None
    description = (payload.get("description") or "").strip() or None
    project_id = (payload.get("id") or "").strip() or f"proj-{uuid.uuid4().hex[:12]}"
    now = utc_now()
    with connect() as conn:
        try:
            conn.execute(
                """
                insert into project_profiles(id, name, base_url, description, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (project_id, name_raw, base_url, description, now, now),
            )
        except sqlite3.IntegrityError as exc:
            msg = str(exc).lower()
            if "unique" in msg:
                raise ValueError("conflict: project name already exists") from exc
            raise
    fetched = get_project_profile(project_id)
    if not fetched:
        # 理论上不可达；保守抛错
        raise ValueError("conflict: project profile insert failed silently")
    return fetched


def update_project_profile(project_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """T2 · PATCH /api/projects/{id}：name / base_url / description 三选其一；UNIQUE 冲突 → ValueError('conflict')。"""
    allowed = ("name", "base_url", "description")
    patch: dict[str, Any] = {}
    for key in allowed:
        if key in payload and payload[key] is not None:
            value = str(payload[key]).strip()
            if key == "name" and not value:
                raise ValueError("invalid: name cannot be empty")
            patch[key] = value or None
    if not patch:
        raise ValueError("invalid: no fields to update")
    fields = ["{0} = ?".format(key) for key in patch]
    values: list[Any] = list(patch.values()) + [utc_now(), project_id]
    with connect() as conn:
        existing = conn.execute("select id from project_profiles where id = ?", (project_id,)).fetchone()
        if not existing:
            return None
        try:
            cur = conn.execute(
                f"update project_profiles set {', '.join(fields)}, updated_at = ? where id = ?",
                values,
            )
        except sqlite3.IntegrityError as exc:
            msg = str(exc).lower()
            if "unique" in msg:
                raise ValueError("conflict: project name already exists") from exc
            raise
        if cur.rowcount == 0:
            return None
    return get_project_profile(project_id)


def delete_project_profile(project_id: str) -> bool:
    """T2 · DELETE /api/projects/{id}：返回是否删除了 1 行。"""
    with connect() as conn:
        cur = conn.execute("delete from project_profiles where id = ?", (project_id,))
    return cur.rowcount > 0


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
            "screenshot_policy": "latest_plus_failed_archive",
            "headless": True,
            "maximize_window": False,
            "viewport_mode": "fixed",
            "viewport_width": 1600,
            "viewport_height": 1100,
            "ignore_https_errors": True,
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
            "labo": {"username": "labo", "password": ""},
            "jesse": {"username": "jesse", "password": ""},
            "tester": {"username": "Tester", "password": ""},
            "admin": {"username": "admin", "password": ""},
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
    viewport_mode = settings.get("viewport_mode") if settings.get("viewport_mode") in {"fixed", "window"} else "fixed"
    normalized = {
        **settings,
        "browser_mode": browser_mode,
        "viewport_mode": viewport_mode,
        "viewport_width": max(320, min(7680, int(settings.get("viewport_width") or 1600))),
        "viewport_height": max(240, min(4320, int(settings.get("viewport_height") or 1100))),
        "maximize_window": bool(settings.get("maximize_window", False)),
        "ignore_https_errors": bool(settings.get("ignore_https_errors", True)),
    }
    normalized.pop("batch_range", None)
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
