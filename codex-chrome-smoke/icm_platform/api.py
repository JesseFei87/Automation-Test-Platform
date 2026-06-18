from __future__ import annotations

import json
import sqlite3
import importlib.util
import re
import subprocess
import sys
import threading
import uuid
import shutil
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import io
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from icm_platform.ai_service import AIConfigurationError, AIProviderError, AIService
from icm_platform.assets import latest_screenshots, list_batch_child_reports, list_cases, list_reports, parse_report, read_report
from icm_platform.db import (
    connect,
    create_project_profile,
    delete_project_profile,
    get_ai_settings,
    get_platform_settings,
    get_project_profile,
    init_db,
    list_project_profiles,
    rows_to_dicts,
    save_ai_settings,
    save_platform_settings,
    update_project_profile,
    utc_now,
)
from icm_platform.paths import DB_PATH, DRAFT_RUN_DIR, OBSERVED_ASSET_DIR, REPORT_DIR, ROOT, SCREENSHOTS_LATEST_DIR, SCREENSHOTS_RUNS_DIR, SPEC_FILE, TEST_CASE_DIR
from icm_platform.run_views import summarize_run_task
from icm_platform.worker import RunnerWorker
from runner.evidence_recorder import EVIDENCE_ROOT, TRACE_ROOT, evidence_summary
from runner.step_details import load_step_details

app = FastAPI(title="ICM AI Automation Platform", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5175", "http://127.0.0.1:5176", "http://localhost:5175"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

ai_service = AIService()
worker = RunnerWorker()


class AISettingsRequest(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class PlatformSettingsRequest(BaseModel):
    runner: dict | None = None
    asset_policy: dict | None = None
    environment: dict | None = None
    accounts: dict | None = None


class RequirementRequest(BaseModel):
    title: str = "未命名需求"
    document: str
    context_info: dict | None = None
    project_id: str | None = None


class RequirementPatchRequest(BaseModel):
    title: str | None = None
    document: str | None = None
    status: str | None = None
    project_id: str | None = None


class GenerateCasesRequest(BaseModel):
    test_points: list[dict]


class RequirementSpecRequest(BaseModel):
    title: str = "未命名需求"
    document: str


class TestPointPatchRequest(BaseModel):
    parent_id: int | None = None
    name: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    description: str | None = None
    module: str | None = None
    source: str | None = None
    sort_order: int | None = None


class TestPointCreateRequest(BaseModel):
    requirement_id: int | None = None
    parent_id: int | None = None
    name: str
    category: str = "功能"
    priority: str = "P1"
    status: str = "已确认"
    description: str = ""
    module: str = ""
    source: str = "manual"
    sort_order: int | None = None


class TestPointReorderUpdate(BaseModel):
    id: int
    parent_id: int | None = None
    sort_order: int
    module: str | None = None
    category: str | None = None


class TestPointReorderRequest(BaseModel):
    updates: list[TestPointReorderUpdate]


class SelectedTestPointsRequest(BaseModel):
    test_point_ids: list[int]
    template: str = "functional"
    title: str | None = None
    generator: Literal["rule", "ai"] = "rule"


class CaseDraftPatchRequest(BaseModel):
    title: str | None = None
    yaml: str | None = None
    status: str | None = None


class CaseDraftCreateRequest(BaseModel):
    requirement_id: int | None = None
    title: str = "新增用例草稿"
    yaml: str | None = None
    template: str = "manual"


class CaseDraftBatchDeleteRequest(BaseModel):
    draft_ids: list[int]


class PromoteDraftRequest(BaseModel):
    case_id: str
    filename: str | None = None


class ValidateDraftRequest(BaseModel):
    yaml: str | None = None
    case_id: str | None = None


class AnalyzeReportRequest(BaseModel):
    force: bool = False


class RunRequest(BaseModel):
    mode: Literal["run-case", "run-batch", "run-draft", "agent-explore"]
    case_id: str | None = None
    draft_id: int | None = None


# -----------------------------------------------------------------------------
# P0 · 所属项目下拉化（增量 2026-06-10）
# -----------------------------------------------------------------------------


class ProjectCreateRequest(BaseModel):
    """T2 · POST /api/projects 入参。name 必填；base_url / description 可空。"""

    name: str
    base_url: str | None = None
    description: str | None = None


class ProjectPatchRequest(BaseModel):
    """T2 · PATCH /api/projects/{id} 入参。name / base_url / description 三选其一。"""

    name: str | None = None
    base_url: str | None = None
    description: str | None = None


@app.get("/api/projects")
def list_projects() -> list[dict]:
    """T2 · GET /api/projects：返回 project_profiles 全部记录（按 created_at, name 排序）。"""
    return list_project_profiles()


@app.post("/api/projects")
def create_project(payload: ProjectCreateRequest) -> dict:
    """T2 · POST /api/projects：name 必填；UNIQUE 冲突 → 409。"""
    try:
        return create_project_profile(payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("conflict:"):
            raise HTTPException(status_code=409, detail=msg.split(":", 1)[1].strip()) from exc
        if msg.startswith("invalid:"):
            raise HTTPException(status_code=400, detail=msg.split(":", 1)[1].strip()) from exc
        raise


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, payload: ProjectPatchRequest) -> dict:
    """T2 · PATCH /api/projects/{id}：改名 / 补 description / 改 base_url；404 / 409。"""
    try:
        result = update_project_profile(project_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("conflict:"):
            raise HTTPException(status_code=409, detail=msg.split(":", 1)[1].strip()) from exc
        if msg.startswith("invalid:"):
            raise HTTPException(status_code=400, detail=msg.split(":", 1)[1].strip()) from exc
        raise
    if result is None:
        raise HTTPException(status_code=404, detail="project not found")
    return result


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    """T2 · DELETE /api/projects/{id}：返回 {ok: true}；404。"""
    ok = delete_project_profile(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="project not found")
    return {"ok": True}


@app.on_event("startup")
def startup() -> None:
    init_db()
    worker.start()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "runner": "python -m runner.main", "api_version": "0.2.0"}


@app.get("/api/system/health")
def system_health() -> dict:
    runner_entry = ROOT / "runner" / "main.py"
    chrome_candidates = [
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ]
    chrome_path = next((path for path in chrome_candidates if path.exists()), None)
    return {
        "api": {"status": "ok", "version": app.version},
        "runner": {
            "status": "ok" if runner_entry.exists() else "missing",
            "entry": "python -m runner.main",
            "path": str(runner_entry),
        },
        "playwright": {
            "available": importlib.util.find_spec("playwright") is not None,
            "chrome_available": chrome_path is not None,
            "chrome_path": str(chrome_path) if chrome_path else "",
        },
        "paths": {
            "reports": path_health(REPORT_DIR),
            "screenshots_latest": path_health(SCREENSHOTS_LATEST_DIR),
            "screenshots_runs": path_health(SCREENSHOTS_RUNS_DIR),
            "observed_assets": path_health(OBSERVED_ASSET_DIR),
        },
        "sqlite": sqlite_health(),
    }


@app.get("/api/ai/settings")
def ai_settings() -> dict:
    return get_ai_settings(mask_key=True)


@app.put("/api/ai/settings")
def update_ai_settings(payload: AISettingsRequest) -> dict:
    return save_ai_settings(payload.model_dump(exclude_unset=True))


@app.get("/api/platform/settings")
def platform_settings() -> dict:
    return get_platform_settings()


@app.put("/api/platform/settings")
def update_platform_settings(payload: PlatformSettingsRequest) -> dict:
    return save_platform_settings(payload.model_dump(exclude_unset=True))


@app.post("/api/ai/test-connection")
def test_ai_connection() -> dict[str, str]:
    try:
        return ai_service.test_connection(get_ai_settings(mask_key=False))
    except AIConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/ai/ollama/models")
def ollama_models(base_url: str | None = Query(default=None)) -> dict:
    settings = get_ai_settings(mask_key=False)
    target_base_url = base_url or settings.get("base_url") or "http://192.168.12.38:11434/v1"
    try:
        return ai_service.list_ollama_models(target_base_url)
    except AIConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/cases")
def cases() -> list[dict]:
    return list_cases()


def resolve_requirement_project_id(project_id: str | None = None) -> str | None:
    if project_id and get_project_profile(project_id):
        return project_id
    if get_project_profile("proj-icm-default"):
        return "proj-icm-default"
    projects = list_project_profiles()
    return str(projects[0]["id"]) if projects else None


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str) -> dict:
    case_id_norm = normalize_case_id(case_id)
    case_path = find_case_yaml(case_id_norm)
    yaml_text = case_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"case YAML parse failed: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="case YAML root must be an object")
    automation_asset = data.get("automation_asset")
    return {
        "id": str(data.get("id") or case_id_norm),
        "title": str(data.get("title") or case_id_norm),
        "status": str(data.get("status") or ""),
        "path": str(case_path),
        "has_automation_asset": isinstance(automation_asset, dict) and bool(automation_asset),
        "yaml": yaml_text,
    }


@app.get("/api/requirements")
def requirements() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            select r.*,
              (select count(*) from test_points tp where tp.requirement_id = r.id) as test_point_count,
              (select count(*) from case_drafts cd where cd.requirement_id = r.id) as draft_count
            from requirements r
            order by r.created_at desc
            limit 50
            """
        ).fetchall()
    return rows_to_dicts(rows)


@app.post("/api/requirements")
def create_requirement(payload: RequirementRequest) -> dict:
    title = payload.title.strip()
    document = payload.document.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title cannot be empty")
    if not document:
        raise HTTPException(status_code=400, detail="document cannot be empty")
    now = utc_now()
    project_id = resolve_requirement_project_id(payload.project_id)
    with connect() as conn:
        cur = conn.execute(
            """
            insert into requirements(title, document, status, project_id, created_at, updated_at)
            values (?, ?, 'draft', ?, ?, ?)
            """,
            (title, document, project_id, now, now),
        )
        requirement_id = cur.lastrowid
    detail = load_requirement_detail(int(requirement_id))
    if not detail:
        raise HTTPException(status_code=500, detail="requirement created but not found")
    return detail


@app.get("/api/requirements/{requirement_id}")
def requirement_detail(requirement_id: int) -> dict:
    detail = load_requirement_detail(requirement_id)
    if not detail:
        raise HTTPException(status_code=404, detail="requirement not found")
    return detail


@app.patch("/api/requirements/{requirement_id}")
def update_requirement(requirement_id: int, payload: RequirementPatchRequest) -> dict:
    updates: dict[str, str] = {}
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="title cannot be empty")
        updates["title"] = title
    if payload.document is not None:
        document = payload.document.strip()
        if not document:
            raise HTTPException(status_code=400, detail="document cannot be empty")
        updates["document"] = document
    if payload.status is not None:
        status = payload.status.strip()
        if not status:
            raise HTTPException(status_code=400, detail="status cannot be empty")
        updates["status"] = status
    if payload.project_id is not None:
        updates["project_id"] = resolve_requirement_project_id(payload.project_id)
    if not updates:
        detail = load_requirement_detail(requirement_id)
        if not detail:
            raise HTTPException(status_code=404, detail="requirement not found")
        return detail
    updates["updated_at"] = utc_now()
    keys = list(updates)
    with connect() as conn:
        existing = conn.execute("select id from requirements where id = ?", (requirement_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="requirement not found")
        conn.execute(
            f"update requirements set {', '.join(f'{key} = ?' for key in keys)} where id = ?",
            [updates[key] for key in keys] + [requirement_id],
        )
    detail = load_requirement_detail(requirement_id)
    if not detail:
        raise HTTPException(status_code=404, detail="requirement not found")
    return detail


@app.delete("/api/requirements/{requirement_id}")
def delete_requirement(requirement_id: int) -> dict:
    with connect() as conn:
        existing = conn.execute("select id, title from requirements where id = ?", (requirement_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="requirement not found")
        test_point_count = conn.execute(
            "delete from test_points where requirement_id = ?", (requirement_id,)
        ).rowcount
        draft_count = conn.execute(
            "delete from case_drafts where requirement_id = ?", (requirement_id,)
        ).rowcount
        conn.execute("delete from requirements where id = ?", (requirement_id,))
    return {
        "status": "deleted",
        "id": requirement_id,
        "title": existing["title"],
        "deleted_test_points": test_point_count,
        "deleted_case_drafts": draft_count,
    }


@app.get("/api/test-points")
def test_points(status: str | None = None) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            select tp.*, r.title as requirement_title
            from test_points tp
            left join requirements r on r.id = tp.requirement_id
            order by coalesce(tp.sort_order, tp.id), tp.id
            """
        ).fetchall()
    points = rows_to_dicts(rows)
    if status == "confirmed":
        return [point for point in points if is_confirmed_status(str(point.get("status", "")))]
    return points


@app.post("/api/test-points")
def create_test_point(payload: TestPointCreateRequest) -> dict:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="test point name is required")
    now = utc_now()
    requirement_id = payload.requirement_id or ensure_manual_requirement()
    module = payload.module.strip() or load_requirement_title(requirement_id) or "未归属模块"
    sort_order = payload.sort_order if payload.sort_order is not None else next_test_point_sort_order(payload.parent_id)
    with connect() as conn:
        cur = conn.execute(
            """
            insert into test_points(
              requirement_id, parent_id, name, category, priority, status, description,
              module, source, sort_order, created_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                requirement_id,
                payload.parent_id,
                payload.name.strip(),
                payload.category.strip() or "功能",
                payload.priority.strip() or "P1",
                payload.status.strip() or "已确认",
                payload.description.strip(),
                module,
                payload.source.strip() or "manual",
                sort_order,
                now,
                now,
            ),
        )
        test_point_id = cur.lastrowid
    return {"id": test_point_id, "requirement_id": requirement_id}


@app.post("/api/requirements/analyze")
def analyze_requirement(payload: RequirementRequest) -> dict:
    try:
        result = ai_service.generate_test_points(payload.document, get_ai_settings(mask_key=False))
    except AIConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    now = utc_now()
    project_id = resolve_requirement_project_id(payload.project_id)
    with connect() as conn:
        cur = conn.execute(
            """
            insert into requirements(title, document, status, analysis_summary, risk_summary, case_count, project_id, created_at, updated_at)
            values (?, ?, 'analyzed', ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.title,
                payload.document,
                result["analysis_summary"],
                result["risk_summary"],
                result["case_count"],
                project_id,
                now,
                now,
            ),
        )
        requirement_id = cur.lastrowid
        for index, point in enumerate(result["test_points"], start=1):
            conn.execute(
                """
                insert into test_points(
                  requirement_id, parent_id, name, category, priority, status, description,
                  module, source, sort_order, created_at, updated_at
                )
                values (?, null, ?, ?, ?, ?, ?, ?, 'ai_generated', ?, ?, ?)
                """,
                (
                    requirement_id,
                    point.name,
                    point.category,
                    point.priority,
                    point.status,
                    point.description,
                    payload.title,
                    index,
                    now,
                    now,
                ),
            )

    return load_requirement_detail(requirement_id) | {"provider": get_ai_settings(mask_key=False).get("provider", ai_service.provider)}


def _spec_case_summary(cases: list[dict]) -> tuple[str, str]:
    count = len(cases)
    priority_count: dict[str, int] = {}
    type_count: dict[str, int] = {}
    for case in cases:
        priority = str(case.get("priority") or "P?").strip() or "P?"
        case_type = str(case.get("type") or "未分类").strip() or "未分类"
        priority_count[priority] = priority_count.get(priority, 0) + 1
        type_count[case_type] = type_count.get(case_type, 0) + 1
    summary = f"已按《功能测试用例规范》生成 {count} 条测试用例草稿"
    if priority_count:
        summary += "，" + "，".join(f"{key} {value} 条" for key, value in sorted(priority_count.items()))
    risk = "请重点复核前置条件、测试数据和断言字段是否完整。"
    if type_count:
        risk += " 当前覆盖类型：" + "，".join(f"{key} {value} 条" for key, value in sorted(type_count.items()))
    return summary, risk


def _save_spec_case_drafts(requirement_id: int, cases: list[dict], context_info: dict | None = None) -> list[dict]:
    now = utc_now()
    saved: list[dict] = []
    with connect() as conn:
        for case in cases:
            title = str(case.get("title") or case.get("id") or "未命名用例").strip()[:200]
            # P1 · 增量：context_info 写到 case_drafts.yaml 顶层（ARCH §3.2）
            case_payload: dict = dict(case)
            if context_info:
                case_payload["context_info"] = context_info
            yaml_text = yaml.safe_dump(case_payload, allow_unicode=True, sort_keys=False)
            cur = conn.execute(
                """
                insert into case_drafts(requirement_id, title, yaml, status, created_at, updated_at, template)
                values (?, ?, ?, 'draft', ?, ?, 'spec')
                """,
                (requirement_id, title, yaml_text, now, now),
            )
            saved.append({"draft_id": cur.lastrowid, "title": title})
    return saved


@app.patch("/api/test-points/reorder")
def update_test_points_order(payload: TestPointReorderRequest) -> dict[str, int]:
    if not payload.updates:
        raise HTTPException(status_code=400, detail="no test point order updates")

    now = utc_now()
    with connect() as conn:
        existing_ids = {
            row["id"]
            for row in conn.execute(
                f"select id from test_points where id in ({','.join('?' for _ in payload.updates)})",
                [item.id for item in payload.updates],
            ).fetchall()
        }
        missing = [item.id for item in payload.updates if item.id not in existing_ids]
        if missing:
            raise HTTPException(status_code=404, detail=f"test points not found: {missing}")

        for item in payload.updates:
            fields = ["parent_id = ?", "sort_order = ?", "updated_at = ?"]
            values: list[object] = [item.parent_id, item.sort_order, now]
            if item.module is not None:
                fields.append("module = ?")
                values.append(item.module)
            if item.category is not None:
                fields.append("category = ?")
                values.append(item.category)
            values.append(item.id)
            conn.execute(f"update test_points set {', '.join(fields)} where id = ?", values)
    return {"updated": len(payload.updates)}


@app.patch("/api/test-points/{test_point_id}")
def update_test_point(test_point_id: int, payload: TestPointPatchRequest) -> dict:
    values = payload.model_dump(exclude_unset=True)
    allowed = ["parent_id", "name", "category", "priority", "status", "description", "module", "source", "sort_order"]
    keys = [key for key in allowed if key in values]
    if not keys:
        raise HTTPException(status_code=400, detail="no fields to update")

    with connect() as conn:
        row = conn.execute("select requirement_id from test_points where id = ?", (test_point_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="test point not found")
        conn.execute(
            f"update test_points set {', '.join(f'{key} = ?' for key in keys)}, updated_at = ? where id = ?",
            [values[key] for key in keys] + [utc_now(), test_point_id],
        )
        requirement_id = row["requirement_id"]
    return requirement_detail(requirement_id)


@app.delete("/api/test-points/{test_point_id}")
def delete_test_point(test_point_id: int) -> dict[str, str]:
    with connect() as conn:
        row = conn.execute("select id from test_points where id = ?", (test_point_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="test point not found")
        conn.execute("delete from test_points where id = ?", (test_point_id,))
    return {"status": "deleted"}


@app.post("/api/test-points/generate-cases")
def generate_cases_from_test_points(payload: SelectedTestPointsRequest) -> dict:
    ids = sorted(set(payload.test_point_ids))
    if not ids:
        raise HTTPException(status_code=400, detail="please select at least one test point")
    placeholders = ",".join("?" for _ in ids)
    with connect() as conn:
        rows = conn.execute(f"select * from test_points where id in ({placeholders}) order by coalesce(sort_order, id), id", ids).fetchall()
    points = rows_to_dicts(rows)
    if len(points) != len(ids):
        raise HTTPException(status_code=404, detail="some test points were not found")

    try:
        yaml_text = ai_service.generate_cases(
            points,
            template=payload.template,
            title=payload.title,
            settings=get_ai_settings(mask_key=False),
            generator=payload.generator,
        )
    except AIConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    now = utc_now()
    requirement_id = ensure_generated_requirement(points)
    title = payload.title or draft_title_for_template(payload.template)
    with connect() as conn:
        cur = conn.execute(
            """
            insert into case_drafts(
              requirement_id, title, yaml, status, created_at, updated_at,
              template, source_test_point_ids
            )
            values (?, ?, ?, 'draft', ?, ?, ?, ?)
            """,
            (requirement_id, title, yaml_text, now, now, payload.template, json.dumps(ids)),
        )
        draft_id = cur.lastrowid
    return {"draft_id": draft_id, "yaml": yaml_text, "status": "draft"}


@app.post("/api/requirements/{requirement_id}/generate-cases")
def generate_requirement_cases(requirement_id: int) -> dict:
    detail = load_requirement_detail(requirement_id)
    if not detail:
        raise HTTPException(status_code=404, detail="requirement not found")

    try:
        yaml_text = ai_service.generate_cases(detail["test_points"], settings=get_ai_settings(mask_key=False), generator="rule")
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    now = utc_now()
    with connect() as conn:
        cur = conn.execute(
            """
            insert into case_drafts(requirement_id, title, yaml, status, created_at, updated_at, template, source_test_point_ids)
            values (?, ?, ?, 'draft', ?, ?, 'functional', ?)
            """,
            (requirement_id, f"{detail['requirement']['title']} - YAML 草稿", yaml_text, now, now, json.dumps([point["id"] for point in detail["test_points"]])),
        )
        draft_id = cur.lastrowid
    return {"draft_id": draft_id, "yaml": yaml_text, "status": "draft"}


def _load_spec_text() -> str:
    if not SPEC_FILE.exists():
        raise HTTPException(status_code=500, detail=f"spec file not found: {SPEC_FILE}")
    return SPEC_FILE.read_text(encoding="utf-8")


@app.post("/api/requirements/analyze-spec")
def analyze_requirement_spec(payload: RequirementRequest) -> dict:
    standard_text = _load_spec_text()
    # P0 · 增量：按 project_id 查 project_profiles（已有函数 db.get_project_profile），拿不到用空 dict
    project_id = resolve_requirement_project_id(payload.project_id)
    project = get_project_profile(project_id) if project_id else None
    project_for_prompt: dict = project or {}
    context_info = payload.context_info or None
    try:
        result = ai_service.generate_test_cases_spec(
            payload.document,
            standard_text,
            get_ai_settings(mask_key=False),
            project=project_for_prompt or None,
            context_info=context_info,
        )
    except AIConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cases = result.get("cases") or []
    analysis_summary, risk_summary = _spec_case_summary(cases)
    now = utc_now()
    with connect() as conn:
        cur = conn.execute(
            """
            insert into requirements(title, document, status, analysis_summary, risk_summary, case_count, project_id, created_at, updated_at)
            values (?, ?, 'analyzed', ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.title,
                payload.document,
                analysis_summary,
                risk_summary,
                len(cases),
                project_id,
                now,
                now,
            ),
        )
        requirement_id = cur.lastrowid
    _save_spec_case_drafts(requirement_id, cases, context_info=context_info)
    detail = load_requirement_detail(requirement_id)
    if not detail:
        raise HTTPException(status_code=500, detail="failed to load generated requirement")
    detail["provider"] = get_ai_settings(mask_key=False).get("provider")
    detail["requirement"]["analysis_summary"] = analysis_summary
    detail["requirement"]["risk_summary"] = risk_summary
    detail["requirement"]["case_count"] = len(cases)
    detail["generated_cases"] = len(cases)
    return detail


@app.post("/api/requirements/{requirement_id}/generate-spec-cases")
def generate_spec_cases(requirement_id: int) -> dict:
    detail = load_requirement_detail(requirement_id)
    if not detail:
        raise HTTPException(status_code=404, detail="requirement not found")
    standard_text = _load_spec_text()
    try:
        result = ai_service.generate_test_cases_spec(
            detail["requirement"]["document"],
            standard_text,
            get_ai_settings(mask_key=False),
        )
    except AIConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    cases = result.get("cases") or []
    now = utc_now()
    saved: list[dict] = []
    with connect() as conn:
        for case in cases:
            title = str(case.get("title") or case.get("id") or "未命名用例").strip()[:200]
            yaml_text = yaml.safe_dump(case, allow_unicode=True, sort_keys=False)
            cur = conn.execute(
                """
                insert into case_drafts(requirement_id, title, yaml, status, created_at, updated_at, template)
                values (?, ?, ?, 'draft', ?, ?, 'spec')
                """,
                (requirement_id, title, yaml_text, now, now),
            )
            saved.append({"draft_id": cur.lastrowid, "title": title})
    return {
        "requirement_id": requirement_id,
        "count": len(saved),
        "drafts": saved,
    }


def _parse_case_draft_payload(draft: dict) -> dict:
    try:
        data = yaml.safe_load(draft.get("yaml") or "") or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data


def _case_yaml_text(requirement: dict, drafts: list[dict]) -> str:
    out = {
        "requirement": {
            "id": requirement.get("id"),
            "title": requirement.get("title"),
            "document": requirement.get("document"),
        },
        "cases": [_parse_case_draft_payload(d) for d in drafts],
    }
    return yaml.safe_dump(out, allow_unicode=True, sort_keys=False)


def _case_xlsx_bytes(requirement: dict, drafts: list[dict]) -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.title = "TestCases"
    headers = [
        "id", "title", "module", "priority", "type",
        "precondition", "test_data", "steps", "expected",
        "requirement_id", "automation", "author/date", "note",
    ]
    sheet.append(headers)
    header_fill = PatternFill("solid", fgColor="E6F0FF")
    header_font = Font(bold=True, color="1F2A44")
    for col_idx in range(1, len(headers) + 1):
        cell = sheet.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    wrap = Alignment(wrap_text=True, vertical="top")
    for draft in drafts:
        case = _parse_case_draft_payload(draft)
        author = str(case.get("author") or "").strip()
        date_ = str(case.get("date") or "").strip()
        author_date = f"{author} / {date_}" if author or date_ else ""
        steps = case.get("steps")
        expected = case.get("expected")
        steps_text = "\n".join(steps) if isinstance(steps, list) else (str(steps) if steps is not None else "")
        expected_text = "\n".join(expected) if isinstance(expected, list) else (str(expected) if expected is not None else "")
        row = [
            str(case.get("id") or ""),
            str(case.get("title") or draft.get("title") or ""),
            str(case.get("module") or ""),
            str(case.get("priority") or ""),
            str(case.get("type") or ""),
            str(case.get("precondition") or ""),
            str(case.get("test_data") or ""),
            steps_text,
            expected_text,
            str(case.get("requirement_id") or ""),
            str(case.get("automation") or ""),
            author_date,
            str(case.get("note") or ""),
        ]
        sheet.append(row)
    widths = [16, 36, 14, 8, 8, 30, 26, 36, 36, 14, 10, 18, 24]
    for col_idx, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A" + chr(64 + col_idx - 26)].width = width
    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row, max_col=len(headers)):
        for cell in row:
            cell.alignment = wrap
    summary = wb.create_sheet("Summary")
    summary.append(["field", "value"])
    summary.append(["requirement_id", requirement.get("id")])
    summary.append(["requirement_title", requirement.get("title")])
    summary.append(["case_count", len(drafts)])
    priority_count: dict[str, int] = {}
    type_count: dict[str, int] = {}
    for draft in drafts:
        case = _parse_case_draft_payload(draft)
        p = str(case.get("priority") or "P?").strip() or "P?"
        t = str(case.get("type") or "").strip() or "未分类"
        priority_count[p] = priority_count.get(p, 0) + 1
        type_count[t] = type_count.get(t, 0) + 1
    summary.append([])
    summary.append(["priority", "count"])
    for p, c in sorted(priority_count.items()):
        summary.append([p, c])
    summary.append([])
    summary.append(["type", "count"])
    for t, c in sorted(type_count.items()):
        summary.append([t, c])
    summary.column_dimensions["A"].width = 20
    summary.column_dimensions["B"].width = 36
    for col_idx in (1, 2):
        cell = summary.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _safe_filename(prefix: str, requirement: dict) -> str:
    title = str(requirement.get("title") or "requirement").strip()
    slug = re.sub(r"[^\w\-\u4e00-\u9fa5]+", "_", title)[:40] or "requirement"
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{slug}-{requirement.get('id')}-{ts}"


def _download_headers(filename: str) -> dict[str, str]:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "download"
    return {
        "Content-Disposition": f"attachment; filename={ascii_name}; filename*=UTF-8''{quote(filename)}",
    }


@app.get("/api/requirements/{requirement_id}/export")
def export_requirement_cases(requirement_id: int, format: str = "xlsx"):
    detail = load_requirement_detail(requirement_id)
    if not detail:
        raise HTTPException(status_code=404, detail="requirement not found")
    drafts = list(detail.get("drafts") or [])
    if not drafts:
        raise HTTPException(status_code=400, detail="requirement has no case drafts to export")
    requirement = detail["requirement"]
    if format == "yaml":
        content = _case_yaml_text(requirement, drafts).encode("utf-8")
        filename = f"{_safe_filename('cases', requirement)}.yaml"
        return Response(
            content=content,
            media_type="application/x-yaml; charset=utf-8",
            headers=_download_headers(filename),
        )
    if format == "xlsx":
        content = _case_xlsx_bytes(requirement, drafts)
        filename = f"{_safe_filename('cases', requirement)}.xlsx"
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=_download_headers(filename),
        )
    raise HTTPException(status_code=400, detail=f"unsupported format: {format}")


@app.post("/api/cases/generate")
def generate_cases(payload: GenerateCasesRequest) -> dict[str, str]:
    return {"yaml": ai_service.generate_cases(payload.test_points)}


@app.get("/api/case-drafts")
def case_drafts() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            select cd.*, r.title as requirement_title
            from case_drafts cd
            left join requirements r on r.id = cd.requirement_id
            order by cd.created_at desc, cd.id desc
            limit 100
            """
        ).fetchall()
    return [normalize_case_draft(row) for row in rows_to_dicts(rows)]


def build_blank_case_yaml(title: str) -> str:
    payload = {
        "id": "TC-ICM-DRAFT",
        "title": title or "新增用例草稿",
        "status": "draft",
        "type": "功能",
        "priority": "P1",
        "author": "AI",
        "precondition": ["请补充前置条件"],
        "steps": ["请补充执行步骤"],
        "expected_results": ["请补充预期结果"],
        "automation_asset": {
            "operation_steps": ["请补充自动化操作步骤"],
            "selectors": {"todo": ["请补充选择器"]},
            "input_values": {},
            "assertions": ["请补充断言"],
        },
    }
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


@app.post("/api/case-drafts")
def create_case_draft(payload: CaseDraftCreateRequest) -> dict:
    title = (payload.title or "新增用例草稿").strip() or "新增用例草稿"
    requirement_id = payload.requirement_id or ensure_manual_requirement()
    yaml_text = payload.yaml or build_blank_case_yaml(title)
    now = utc_now()
    with connect() as conn:
        requirement = conn.execute("select id from requirements where id = ?", (requirement_id,)).fetchone()
        if not requirement:
            raise HTTPException(status_code=404, detail="requirement not found")
        cur = conn.execute(
            """
            insert into case_drafts(requirement_id, title, yaml, status, created_at, updated_at, template)
            values (?, ?, ?, 'draft', ?, ?, ?)
            """,
            (requirement_id, title, yaml_text, now, now, payload.template or "manual"),
        )
        draft_id = int(cur.lastrowid)
    return case_draft_detail(draft_id)


def _safe_unlink(path: Path, allowed_root: Path) -> bool:
    target = path.resolve()
    root = allowed_root.resolve()
    if not target.exists():
        return False
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail=f"refuse to delete outside allowed root: {path}")
    if target.is_dir():
        raise HTTPException(status_code=400, detail=f"refuse to delete directory: {path}")
    target.unlink()
    return True


def delete_case_draft_assets(draft_id: int) -> dict:
    draft = load_case_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="case draft not found")
    deleted_files = 0
    promoted_case_id = str(draft.get("promoted_case_id") or "").strip()
    promoted_path = str(draft.get("promoted_path") or "").strip()
    if promoted_path:
        deleted_files += int(_safe_unlink(Path(promoted_path), TEST_CASE_DIR))
    elif promoted_case_id:
        try:
            deleted_files += int(_safe_unlink(find_case_yaml(promoted_case_id), TEST_CASE_DIR))
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    if promoted_case_id:
        deleted_files += int(_safe_unlink(compute_target_path(promoted_case_id), ROOT / "runner" / "flows"))
    with connect() as conn:
        deleted_rows = conn.execute("delete from case_drafts where id = ?", (draft_id,)).rowcount
    return {
        "draft_id": draft_id,
        "promoted_case_id": promoted_case_id or None,
        "deleted_files": deleted_files,
        "deleted_rows": deleted_rows,
    }


@app.post("/api/case-drafts/batch-delete")
def batch_delete_case_drafts(payload: CaseDraftBatchDeleteRequest) -> dict:
    results = []
    for draft_id in dict.fromkeys(payload.draft_ids):
        try:
            results.append({"ok": True, **delete_case_draft_assets(int(draft_id))})
        except HTTPException as exc:
            results.append({"ok": False, "draft_id": draft_id, "error": exc.detail})
    return {
        "deleted": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
        "results": results,
    }


@app.delete("/api/case-drafts/{draft_id}")
def delete_case_draft(draft_id: int) -> dict:
    return {"ok": True, **delete_case_draft_assets(draft_id)}


@app.get("/api/case-drafts/{draft_id}")
def case_draft_detail(draft_id: int) -> dict:
    draft = load_case_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="case draft not found")
    return draft


@app.patch("/api/case-drafts/{draft_id}")
def update_case_draft(draft_id: int, payload: CaseDraftPatchRequest) -> dict:
    values = payload.model_dump(exclude_unset=True)
    allowed = ["title", "yaml", "status"]
    keys = [key for key in allowed if key in values]
    if not keys:
        raise HTTPException(status_code=400, detail="no fields to update")
    with connect() as conn:
        row = conn.execute("select id from case_drafts where id = ?", (draft_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="case draft not found")
        conn.execute(
            f"update case_drafts set {', '.join(f'{key} = ?' for key in keys)}, updated_at = ? where id = ?",
            [values[key] for key in keys] + [utc_now(), draft_id],
        )
    return case_draft_detail(draft_id)


@app.post("/api/case-drafts/{draft_id}/validate")
def validate_case_draft(draft_id: int, payload: ValidateDraftRequest | None = None) -> dict:
    draft = load_case_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="case draft not found")
    yaml_text = str(payload.yaml if payload and payload.yaml is not None else draft["yaml"])
    if payload and payload.case_id:
        yaml_text = replace_yaml_case_id(yaml_text, normalize_case_id(payload.case_id))
    return {"draft_id": draft_id, **validate_case_yaml(yaml_text)}


@app.post("/api/case-drafts/{draft_id}/promote")
def promote_case_draft(draft_id: int, payload: PromoteDraftRequest) -> dict:
    draft = load_case_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="case draft not found")
    case_id = normalize_case_id(payload.case_id)
    filename = normalize_case_filename(payload.filename, case_id)
    target = TEST_CASE_DIR / filename
    if target.exists():
        raise HTTPException(status_code=409, detail=f"case file already exists: {filename}")
    yaml_text = replace_yaml_case_id(str(draft["yaml"]), case_id)
    validation = validate_case_yaml(yaml_text)
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=f"YAML validation failed: {'; '.join(validation['errors'])}")
    TEST_CASE_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml_text, encoding="utf-8")
    with connect() as conn:
        conn.execute(
            """
            update case_drafts
            set status = 'promoted', promoted_case_id = ?, promoted_path = ?, updated_at = ?
            where id = ?
            """,
            (case_id, str(target), utc_now(), draft_id),
        )
    return case_draft_detail(draft_id)


@app.post("/api/case-drafts/{draft_id}/run")
def run_case_draft(draft_id: int) -> dict[str, str | None]:
    try:
        return worker.enqueue("run-draft", draft_id=draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/runs")
def create_run(payload: RunRequest) -> dict[str, str | None]:
    try:
        return worker.enqueue(payload.mode, payload.case_id, payload.draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs")
def runs() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("select * from run_tasks order by created_at desc limit 50").fetchall()
    tasks = rows_to_dicts(rows)
    return [{**task, "summary": summarize_run_task(task)} for task in tasks]


def _delete_run_artifacts(run_id: str, task_dict: dict) -> dict[str, int]:
    deleted_files = 0
    deleted_dirs = 0
    deleted_rows = 0
    report_path = str(task_dict.get("report_path") or "").strip()
    file_candidates = [
        Path(report_path) if report_path else None,
        REPORT_DIR / f"{run_id}.md",
        (ROOT / "reports" / "step-details" / f"{run_id}.json"),
    ]
    dir_candidates = [
        ROOT / "reports" / "agent-explore" / run_id,
        DRAFT_RUN_DIR / run_id,
        SCREENSHOTS_RUNS_DIR / run_id,
        EVIDENCE_ROOT / run_id,
        TRACE_ROOT / run_id,
    ]
    for path in file_candidates:
        if path and path.exists() and path.is_file():
            path.unlink()
            deleted_files += 1
    for path in dir_candidates:
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
            deleted_dirs += 1
    with connect() as conn:
        deleted_rows += conn.execute("delete from run_logs where run_id = ?", (run_id,)).rowcount
        deleted_rows += conn.execute("delete from run_tasks where id = ?", (run_id,)).rowcount
    return {"deleted_files": deleted_files, "deleted_dirs": deleted_dirs, "deleted_rows": deleted_rows}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str) -> dict:
    with connect() as conn:
        task = conn.execute("select * from run_tasks where id = ?", (run_id,)).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="run not found")
    result = _delete_run_artifacts(run_id, dict(task))
    return {"ok": True, "run_id": run_id, **result}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    with connect() as conn:
        task = conn.execute("select * from run_tasks where id = ?", (run_id,)).fetchone()
        logs = conn.execute("select * from run_logs where run_id = ? order by id", (run_id,)).fetchall()
    if not task:
        raise HTTPException(status_code=404, detail="run not found")

    report = ""
    screenshots: list[dict[str, str]] = []
    task_dict = dict(task)
    children = list_batch_child_reports(run_id) if task_dict.get("mode") == "run-batch" else []
    if task_dict.get("report_path"):
        try:
            report = read_report(run_id)
            screenshots = parse_report(report)["screenshots"]
        except FileNotFoundError:
            report = ""
    if not screenshots and task_dict.get("case_id"):
        screenshots = [screenshot_payload(task_dict["case_id"], path) for path in latest_screenshots(task_dict["case_id"])]
    agent_explore = load_agent_explore_artifacts(run_id) if task_dict.get("mode") == "agent-explore" else None
    log_dicts = rows_to_dicts(logs)
    if not log_dicts and task_dict.get("mode") == "agent-explore":
        log_dicts = _synthetic_logs_from_evidence(run_id)
    evidence_lines = evidence_log_lines(run_id)
    return {
        "task": task_dict,
        "summary": summarize_run_task(task_dict),
        "logs": log_dicts,
        "children": children,
        "report": report,
        "screenshots": screenshots,
        "evidence": evidence_summary(run_id),
        "agent_explore": agent_explore,
        "analysis": ai_service.analyze_run_report(report, screenshots, [row["line"] for row in log_dicts] + evidence_lines) if report else None,
    }


def _normalized_mode(mode: str) -> str:
    return "agent" if mode == "agent-explore" else "worker"


def _normalized_status(status: str) -> str:
    if status == "passed":
        return "completed"
    return status or "queued"


def _run_screenshots(run_id: str) -> list[dict[str, str]]:
    run_dir = SCREENSHOTS_RUNS_DIR / run_id
    if not run_dir.exists():
        return []
    return [run_screenshot_payload(run_id, str(path)) for path in sorted(run_dir.glob("*.png"))]


def _report_screenshots(task_dict: dict, report_text: str) -> list[dict[str, str]]:
    screenshots: list[dict[str, str]] = []
    if report_text:
        screenshots = parse_report(report_text)["screenshots"]
    if not screenshots:
        screenshots = _run_screenshots(str(task_dict.get("id") or ""))
    if not screenshots and task_dict.get("case_id"):
        screenshots = [screenshot_payload(task_dict["case_id"], path) for path in latest_screenshots(task_dict["case_id"])]
    return screenshots


def _build_agent_steps(agent_explore: dict | None, logs: list[dict], screenshots: list[dict[str, str]]) -> list[dict]:
    trace = (agent_explore or {}).get("trace") or {}
    history = trace.get("history") or []
    steps: list[dict] = []
    for index, item in enumerate(history, start=1):
        decision = item.get("decision") if isinstance(item, dict) else {}
        execution = item.get("execution") if isinstance(item, dict) else {}
        decision = decision if isinstance(decision, dict) else {}
        execution = execution if isinstance(execution, dict) else {}
        screenshot = screenshots[min(index - 1, len(screenshots) - 1)] if screenshots else None
        steps.append(
            {
                "step_index": int(item.get("step", index)) if isinstance(item, dict) else index,
                "step_code": f"agent_{index:02d}",
                "title": str(decision.get("action") or f"Step {index}"),
                "status": "failed" if execution.get("error") else ("completed" if trace.get("ok") else "running"),
                "started_at": None,
                "finished_at": None,
                "duration_seconds": None,
                "summary": str(decision.get("reason") or execution.get("result") or ""),
                "error_message": str(execution.get("error") or ""),
                "screenshot_url": screenshot["url"] if screenshot else "",
                "ai_analysis": str(decision.get("reason") or ""),
                "final_url": str(trace.get("finalUrl") or trace.get("final_url") or ""),
                "command_output": [row["line"] for row in logs[-8:]],
                "selectors": [],
                "inputs": [],
                "console_logs": [],
                "network_logs": [],
                "dom_snapshot_url": "",
                "events": [item] if isinstance(item, dict) else [],
            }
        )
    return steps


def _build_unified_run_detail(run_id: str) -> dict:
    with connect() as conn:
        task = conn.execute("select * from run_tasks where id = ?", (run_id,)).fetchone()
        logs = conn.execute("select * from run_logs where run_id = ? order by id", (run_id,)).fetchall()
    if not task:
        raise HTTPException(status_code=404, detail="run not found")
    task_dict = dict(task)
    log_dicts = rows_to_dicts(logs)
    if not log_dicts and task_dict.get("mode") == "agent-explore":
        log_dicts = _synthetic_logs_from_evidence(run_id)
    report_text = ""
    if task_dict.get("report_path") and Path(str(task_dict["report_path"])).suffix.lower() == ".md":
        try:
            report_text = read_report(run_id)
        except FileNotFoundError:
            report_text = ""
    screenshots = _report_screenshots(task_dict, report_text)
    analysis = ai_service.analyze_run_report(report_text, screenshots, [row["line"] for row in log_dicts] + evidence_log_lines(run_id)) if report_text else None
    agent_explore = load_agent_explore_artifacts(run_id) if task_dict.get("mode") == "agent-explore" else None
    step_detail_payload = load_step_details(run_id)
    if step_detail_payload:
        steps = step_detail_payload.get("steps") or []
        final_url = step_detail_payload.get("final_url") or ""
        summary = step_detail_payload.get("summary") or {}
    else:
        steps = _build_agent_steps(agent_explore, log_dicts, screenshots)
        trace = (agent_explore or {}).get("trace") or {}
        final_url = str(trace.get("finalUrl") or trace.get("final_url") or "")
        summary = {
            "title": task_dict.get("case_id") or run_id,
            "conclusion": str(trace.get("summary") or ""),
            "failure_reason": str(trace.get("error") or task_dict.get("error") or ""),
            "ai_analysis": str(trace.get("summary") or ""),
        }
    case_name = task_dict.get("case_id") or run_id
    if report_text:
        report_meta = parse_report(report_text)
        case_name = report_meta.get("case_name") or case_name
    return {
        "run_id": run_id,
        "case_id": task_dict.get("case_id"),
        "case_name": case_name,
        "mode": _normalized_mode(str(task_dict.get("mode") or "")),
        "trigger": str(task_dict.get("trigger") or "manual"),
        "parent_run_id": task_dict.get("parent_run_id"),
        "status": _normalized_status(str(task_dict.get("status") or "")),
        "operator": "admin",
        "started_at": task_dict.get("started_at") or task_dict.get("created_at"),
        "finished_at": task_dict.get("finished_at"),
        "duration_seconds": task_dict.get("summary", {}).get("duration_seconds") if isinstance(task_dict.get("summary"), dict) else None,
        "final_url": final_url,
        "summary": {
            "title": summary.get("title") or case_name,
            "conclusion": summary.get("conclusion") or "",
            "failure_reason": summary.get("failure_reason") or "",
            "ai_analysis": analysis["conclusion"] if analysis else (summary.get("ai_analysis") or ""),
        },
        "steps": steps,
        "artifacts": {
            "report_markdown_url": f"/api/reports/{run_id}" if report_text else "",
            "observed_asset_path": (step_detail_payload or {}).get("artifacts", {}).get("observed_asset_path", ""),
            "observed_asset_merge_url": f"/api/runs/{run_id}/merge-observed-asset",
            "trace_download_url": f"/api/runs/{run_id}/evidence/trace" if evidence_summary(run_id).get("trace", {}).get("exists") else "",
            "candidate_flow_url": f"/api/runs/{run_id}/agent-explore/candidate-flow" if agent_explore and agent_explore.get("candidate_flow_path") else "",
        },
        "raw_report": report_text,
        "logs": log_dicts,
        "screenshots": screenshots,
        "evidence": evidence_summary(run_id),
        "agent_explore": agent_explore,
        "analysis": analysis,
        "healing_hint": str(((agent_explore or {}).get("trace") or {}).get("healing_hint") or ""),
    }


@app.get("/api/runs/{run_id}/detail")
def run_detail_view(run_id: str) -> dict:
    return _build_unified_run_detail(run_id)


def load_agent_explore_artifacts(run_id: str) -> dict | None:
    root = ROOT / "reports" / "agent-explore" / run_id
    trace_path = root / "trace.json"
    if not trace_path.exists():
        return None
    candidate_path = root / "candidate_flow.py"
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        trace = {"ok": False, "error": "invalid agent trace json"}
    return {
        "trace_path": str(trace_path.relative_to(ROOT)),
        "candidate_flow_path": str(candidate_path.relative_to(ROOT)) if candidate_path.exists() else "",
        "trace": trace,
    }


def _load_case_source_for_agent_run(run_id: str, task_dict: dict, trace: dict) -> tuple[str, str]:
    draft_path = DRAFT_RUN_DIR / run_id / "case.yaml"
    if draft_path.exists():
        return draft_path.read_text(encoding="utf-8"), str(draft_path)
    case_arg = str(trace.get("case_arg") or "").strip()
    if case_arg:
        path = Path(case_arg)
        if path.exists():
            return path.read_text(encoding="utf-8"), str(path)
    case_id = str(task_dict.get("case_id") or "").strip()
    if case_id:
        path = find_case_yaml(case_id)
        return path.read_text(encoding="utf-8"), str(path)
    raise HTTPException(status_code=404, detail="case source not found for self heal")


def _self_heal_hint(trace: dict, events: list[dict]) -> str:
    error = str(trace.get("error") or "").strip()
    if "unknown ref: empty" in error:
        return "上一轮在成功页后又追加了空 ref 尾动作；若已离开登录页且出现目标用户名，立即 finish，不要再补无意义点击或填充。"
    if "login" in error.lower():
        return "优先使用用例 test_data 中的账号密码；一旦进入目标工作台且出现目标用户名，不要继续尝试默认账号。"
    for item in reversed(events):
        if str(item.get("kind") or "") == "agent_action_failed":
            return f"避免重复失败动作：{item.get('message') or 'agent_action_failed'}。"
    return "结合上一轮失败尾部步骤修复，不要重复无效动作；若成功信号已出现，优先 finish。"


def _build_self_heal_context(run_id: str, task_dict: dict, trace: dict) -> dict:
    events = evidence_summary(run_id).get("events", {}).get("latest", [])
    history = trace.get("history") or []
    return {
        "parent_run_id": run_id,
        "trigger": "self_heal",
        "failure_summary": str(trace.get("error") or task_dict.get("error") or trace.get("summary") or "").strip(),
        "healing_hint": _self_heal_hint(trace, events if isinstance(events, list) else []),
        "last_history": history[-5:] if isinstance(history, list) else [],
    }


@app.get("/api/runs/{run_id}/agent-explore/trace")
def agent_explore_trace_file(run_id: str) -> FileResponse:
    path = ROOT / "reports" / "agent-explore" / run_id / "trace.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="agent trace not found")
    return FileResponse(path, media_type="application/json", filename=f"{run_id}-agent-trace.json")


@app.get("/api/runs/{run_id}/agent-explore/candidate-flow")
def agent_explore_candidate_flow_file(run_id: str) -> FileResponse:
    path = ROOT / "reports" / "agent-explore" / run_id / "candidate_flow.py"
    if not path.exists():
        raise HTTPException(status_code=404, detail="agent candidate flow not found")
    return FileResponse(path, media_type="text/x-python", filename=f"{run_id}-candidate-flow.py")


def _next_agent_case_id() -> str:
    numbers = [
        int(match.group(1))
        for path in TEST_CASE_DIR.glob("TC-ICM-*.yaml")
        for match in [re.search(r"TC-ICM-(\d+)", path.name, flags=re.IGNORECASE)]
        if match
    ]
    return f"TC-ICM-{(max(numbers) if numbers else 12) + 1:03d}"


def _draft_for_agent_run(run_id: str) -> tuple[dict, Path]:
    draft_path = DRAFT_RUN_DIR / run_id / "case.yaml"
    if not draft_path.exists():
        raise HTTPException(status_code=400, detail="only draft Agent Explore runs can be promoted")
    try:
        data = yaml.safe_load(draft_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"draft case YAML is invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="draft case YAML root must be an object")
    return data, draft_path


def _formal_case_id_for_draft(data: dict) -> str:
    raw_case_id = str(data.get("id") or "").strip().upper()
    if re.fullmatch(r"TC-ICM-[0-9A-Z-]+", raw_case_id):
        try:
            find_case_yaml(raw_case_id)
        except HTTPException:
            return raw_case_id
    return _next_agent_case_id()


def _existing_promoted_case_for_draft(draft_path: Path) -> str | None:
    yaml_text = draft_path.read_text(encoding="utf-8")
    with connect() as conn:
        row = conn.execute(
            """
            select promoted_case_id from case_drafts
            where yaml = ? and promoted_case_id is not null and promoted_case_id != ''
            order by id desc limit 1
            """,
            (yaml_text,),
        ).fetchone()
    return str(row["promoted_case_id"]) if row else None


def _existing_promoted_case_for_run(run_id: str) -> tuple[str, Path] | None:
    matches: list[tuple[str, Path]] = []
    for path in sorted(TEST_CASE_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict) or str(data.get("source_run_id") or "") != run_id:
            continue
        case_id = str(data.get("id") or "").strip()
        if case_id:
            matches.append((case_id, path))
    return matches[0] if matches else None


def _mark_matching_draft_promoted(draft_path: Path, case_id: str, target: Path) -> int | None:
    yaml_text = draft_path.read_text(encoding="utf-8")
    now = utc_now()
    with connect() as conn:
        row = conn.execute("select id from case_drafts where yaml = ? order by id desc limit 1", (yaml_text,)).fetchone()
        if not row:
            data = yaml.safe_load(yaml_text) or {}
            row = conn.execute(
                "select id from case_drafts where title = ? order by id desc limit 1",
                (str(data.get("title") or ""),),
            ).fetchone()
        if not row:
            return None
        draft_id = int(row["id"])
        conn.execute(
            """
            update case_drafts
            set status = 'promoted', promoted_case_id = ?, promoted_path = ?, updated_at = ?
            where id = ?
            """,
            (case_id, str(target), now, draft_id),
        )
        return draft_id


def _agent_trace_asset(trace: dict, draft_data: dict) -> dict:
    history = trace.get("history") or []
    operation_steps: list[str] = []
    selectors: dict[str, str] = {}
    input_values: dict[str, str] = {}
    for index, item in enumerate(history, start=1):
        decision = item.get("decision") if isinstance(item, dict) else {}
        execution = item.get("execution") if isinstance(item, dict) else {}
        decision = decision if isinstance(decision, dict) else {}
        execution = execution if isinstance(execution, dict) else {}
        action = str(decision.get("action") or f"step_{index}")
        selector = str(execution.get("selector") or "").strip()
        value = str(decision.get("value") or "").strip()
        operation_steps.append(str(decision.get("reason") or action))
        if selector:
            selectors[f"{action}_{index}"] = selector
        if value:
            input_values[f"{action}_{index}"] = value
    expected = draft_data.get("expected_results") or draft_data.get("expected") or []
    assertions = [str(item) for item in expected] if isinstance(expected, list) else [str(expected)] if expected else []
    return {
        "status": "verified",
        "source": "agent-explore",
        "operation_steps": operation_steps or [str(item) for item in (draft_data.get("steps") or [])],
        "selectors": selectors or {"agent_candidate": "candidate_flow.py"},
        "input_values": input_values,
        "assertions": assertions or [str(trace.get("summary") or "Agent Explore passed")],
    }


def _normalize_agent_draft_for_regression(draft_data: dict, case_id: str, run_id: str, trace: dict) -> dict:
    data = dict(draft_data)
    if "expected_results" not in data and "expected" in data:
        data["expected_results"] = data.get("expected")
    if "preconditions" not in data and "precondition" in data:
        data["preconditions"] = [str(data.get("precondition"))]
    data["id"] = case_id
    data["status"] = "formal"
    data["source"] = "agent-explore"
    data["source_run_id"] = run_id
    data["automation"] = "Yes"
    data["automation_asset"] = merge_automation_asset(data.get("automation_asset") if isinstance(data.get("automation_asset"), dict) else {}, _agent_trace_asset(trace, data))
    return data


@app.post("/api/runs/{run_id}/agent-explore/promote-regression")
def promote_agent_explore_regression(run_id: str) -> dict:
    with connect() as conn:
        task = conn.execute("select * from run_tasks where id = ?", (run_id,)).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="run not found")
    task_dict = dict(task)
    if task_dict.get("mode") != "agent-explore":
        raise HTTPException(status_code=400, detail="only Agent Explore runs can be promoted")
    if _normalized_status(str(task_dict.get("status") or "")) != "completed":
        raise HTTPException(status_code=400, detail="only passed Agent Explore runs can be promoted")

    agent_explore = load_agent_explore_artifacts(run_id)
    trace = (agent_explore or {}).get("trace") or {}
    if trace.get("ok") is False or str(trace.get("status") or "").lower() in {"failed", "error"}:
        raise HTTPException(status_code=400, detail="only passed Agent Explore traces can be promoted")

    candidate_path = ROOT / "reports" / "agent-explore" / run_id / "candidate_flow.py"
    if not candidate_path.exists():
        raise HTTPException(status_code=404, detail=f"candidate flow not found for run_id={run_id}")
    candidate_text = candidate_path.read_text(encoding="utf-8")
    if not candidate_text.strip():
        raise HTTPException(status_code=400, detail="candidate_flow.py is empty")
    try:
        ast.parse(candidate_text)
    except SyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"candidate_flow.py syntax error: {exc}") from exc

    draft_data, draft_path = _draft_for_agent_run(run_id)
    existing_by_run = _existing_promoted_case_for_run(run_id)
    if existing_by_run:
        existing_case_id, existing_case_path = existing_by_run
        existing_flow_path = compute_target_path(existing_case_id)
        return {
            "case_id": existing_case_id,
            "case_path": str(existing_case_path),
            "flow_path": str(existing_flow_path),
            "draft_id": _mark_matching_draft_promoted(draft_path, existing_case_id, existing_case_path),
            "status": "promoted",
        }
    case_id = _existing_promoted_case_for_draft(draft_path) or _formal_case_id_for_draft(draft_data)
    case_filename = normalize_case_filename(None, case_id)
    case_target = TEST_CASE_DIR / case_filename
    flow_target = compute_target_path(case_id)
    if case_target.exists() and flow_target.exists():
        return {
            "case_id": case_id,
            "case_path": str(case_target),
            "flow_path": str(flow_target),
            "draft_id": _mark_matching_draft_promoted(draft_path, case_id, case_target),
            "status": "promoted",
        }
    if case_target.exists():
        raise HTTPException(status_code=409, detail=f"case file already exists: {case_filename}")
    if flow_target.exists():
        raise HTTPException(status_code=409, detail=f"flow file already exists: {flow_target.name}")

    draft_data = _normalize_agent_draft_for_regression(draft_data, case_id, run_id, trace)
    yaml_text = yaml.safe_dump(draft_data, allow_unicode=True, sort_keys=False)
    validation = validate_case_yaml(yaml_text)
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=f"YAML validation failed: {'; '.join(validation['errors'])}")

    TEST_CASE_DIR.mkdir(parents=True, exist_ok=True)
    flow_target.parent.mkdir(parents=True, exist_ok=True)
    try:
        case_target.write_text(yaml_text, encoding="utf-8")
        flow_target.write_text(candidate_text, encoding="utf-8")
        py_compile.compile(str(flow_target), doraise=True)
    except Exception as exc:
        case_target.unlink(missing_ok=True)
        flow_target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"failed to promote regression case: {exc}") from exc

    draft_id = _mark_matching_draft_promoted(draft_path, case_id, case_target)
    return {
        "case_id": case_id,
        "case_path": str(case_target),
        "flow_path": str(flow_target),
        "draft_id": draft_id,
        "status": "promoted",
    }


@app.post("/api/runs/{run_id}/agent-explore/self-heal")
def self_heal_agent_explore(run_id: str) -> dict:
    with connect() as conn:
        task = conn.execute("select * from run_tasks where id = ?", (run_id,)).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="run not found")
    task_dict = dict(task)
    if task_dict.get("mode") != "agent-explore":
        raise HTTPException(status_code=400, detail="only Agent Explore runs can self heal")
    agent_explore = load_agent_explore_artifacts(run_id)
    trace = (agent_explore or {}).get("trace") or {}
    if not trace:
        raise HTTPException(status_code=404, detail="trace not found for self heal")
    case_yaml, _ = _load_case_source_for_agent_run(run_id, task_dict, trace)
    context = _build_self_heal_context(run_id, task_dict, trace)
    return worker.enqueue_agent_self_heal(run_id, case_yaml, context, case_id=task_dict.get("case_id"))


@app.post("/api/runs/{run_id}/agent-explore/promote-candidate")
def promote_agent_explore_candidate(run_id: str) -> dict:
    """资产流通闭环（路线 D · 增量）：把 agent-explore 生成的 candidate_flow.py
    提升为 case_drafts 草稿。

    - 读取 ``reports/agent-explore/{run_id}/candidate_flow.py``
    - 解析为 case_draft YAML 顶层骨架（标题默认用 run_id；status=draft；template=spec）
    - 复制 candidate_flow.py 全文到 ``operation_steps`` 注释区，方便后续手工补全
    - 失败：文件不存在 → 404；内容不是 UTF-8 → 400
    - 成功：返回新建 case_draft 详情（同 ``case_draft_detail``）
    """
    candidate_path = ROOT / "reports" / "agent-explore" / run_id / "candidate_flow.py"
    if not candidate_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"candidate flow not found for run_id={run_id}",
        )
    try:
        candidate_text = candidate_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"candidate_flow.py is not readable: {exc}") from exc
    if not candidate_text.strip():
        raise HTTPException(status_code=400, detail="candidate_flow.py is empty")

    # 骨架：top-level 字段 + 占位步骤骨架 + 注释区贴候选脚本原文
    # 避免 Python 文件里出现非 ASCII YAML 转义问题，统一 allow_unicode
    draft_payload: dict = {
        "title": run_id,
        "template": "spec",
        "status": "draft",
        "priority": "P2",
        "type": "智能探索采纳",
        "source": "agent-explore",
        "source_run_id": run_id,
        "steps": [
            f"待补充：从 {run_id} 的 candidate_flow 拷贝逻辑",
        ],
        "_candidate_flow_excerpt": candidate_text,
    }
    yaml_text = yaml.safe_dump(draft_payload, allow_unicode=True, sort_keys=False)

    now = utc_now()
    title = run_id[:200]
    requirement_id = ensure_manual_requirement()
    with connect() as conn:
        cur = conn.execute(
            """
            insert into case_drafts(requirement_id, title, yaml, status, created_at, updated_at, template)
            values (?, ?, ?, 'draft', ?, ?, 'spec')
            """,
            (requirement_id, title, yaml_text, now, now),
        )
        new_id = int(cur.lastrowid)
    return case_draft_detail(new_id)


def evidence_log_lines(run_id: str) -> list[str]:
    summary = evidence_summary(run_id)
    lines: list[str] = []
    for item in summary.get("events", {}).get("latest", []):
        lines.append(f"[evidence:event] {item.get('kind', '')} {item.get('message', '')} {item.get('url', '')}")
    for item in summary.get("console", {}).get("latest", []):
        lines.append(f"[evidence:console] {item.get('level', '')} {item.get('text', '')}")
    for item in summary.get("network", {}).get("latest", []):
        lines.append(f"[evidence:network] {item.get('method', '')} {item.get('status', '')} {item.get('url', '')}")
    dom_count = summary.get("dom", {}).get("count", 0)
    if summary.get("trace", {}).get("exists"):
        lines.append("[evidence:trace] trace.zip generated")
    if dom_count:
        lines.append(f"[evidence:dom] {dom_count} DOM snapshots generated")
    return lines


def _synthetic_logs_from_evidence(run_id: str) -> list[dict]:
    summary = evidence_summary(run_id)
    rows: list[dict] = []
    index = 1
    for item in summary.get("events", {}).get("latest", []):
        line = f"[{item.get('kind', '')}] {item.get('message', '')}".strip()
        if item.get("value") not in (None, ""):
            line = f"{line} value={item.get('value')}"
        if item.get("url"):
            line = f"{line} url={item.get('url')}"
        rows.append(
            {
                "id": index,
                "run_id": run_id,
                "stream": "evidence",
                "line": line,
                "created_at": item.get("created_at") or "",
            }
        )
        index += 1
    for item in summary.get("console", {}).get("latest", []):
        rows.append(
            {
                "id": index,
                "run_id": run_id,
                "stream": "console",
                "line": f"[console:{item.get('level', '')}] {item.get('text', '')}".strip(),
                "created_at": item.get("created_at") or "",
            }
        )
        index += 1
    return rows


@app.get("/api/runs/{run_id}/evidence/trace")
def run_evidence_trace(run_id: str) -> FileResponse:
    path = TRACE_ROOT / run_id / "trace.zip"
    if not path.exists():
        raise HTTPException(status_code=404, detail="trace not found")
    return FileResponse(path, media_type="application/zip", filename=f"{run_id}-trace.zip")


@app.get("/api/runs/{run_id}/evidence/{kind}")
def run_evidence_jsonl(run_id: str, kind: Literal["events", "console", "network"]) -> FileResponse:
    path = EVIDENCE_ROOT / run_id / f"{kind}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{kind} evidence not found")
    return FileResponse(path, media_type="application/jsonl", filename=f"{run_id}-{kind}.jsonl")


@app.get("/api/runs/{run_id}/evidence/dom/{filename}")
def run_evidence_dom(run_id: str, filename: str) -> FileResponse:
    path = EVIDENCE_ROOT / run_id / "dom" / filename
    if not path.exists() or path.suffix.lower() != ".html":
        raise HTTPException(status_code=404, detail="dom snapshot not found")
    return FileResponse(path, media_type="text/html", filename=filename)


@app.get("/api/runs/{run_id}/observed-asset")
def run_observed_asset(run_id: str) -> dict:
    return load_observed_asset_for_run(run_id)


@app.post("/api/runs/{run_id}/merge-observed-asset")
def merge_run_observed_asset(run_id: str) -> dict:
    with connect() as conn:
        task = conn.execute("select * from run_tasks where id = ?", (run_id,)).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="run not found")
    if task["status"] != "passed":
        raise HTTPException(status_code=400, detail="only passed runs can merge observed automation assets")
    if not task["case_id"]:
        raise HTTPException(status_code=400, detail="batch parent runs cannot merge a single case asset")

    observed = load_observed_asset_for_run(run_id)
    case_path = find_case_yaml(str(task["case_id"]))
    data = yaml.safe_load(case_path.read_text(encoding="utf-8")) or {}
    existing = data.get("automation_asset") if isinstance(data.get("automation_asset"), dict) else {}
    data["automation_asset"] = merge_automation_asset(existing, observed)
    validation = validate_case_yaml(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=f"merged YAML validation failed: {'; '.join(validation['errors'])}")
    case_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"case_id": task["case_id"], "path": str(case_path), "automation_asset": data["automation_asset"]}


# -----------------------------------------------------------------------------
# 路线 A · 资产采纳主流程化（diff 预览 + adoptions 持久化）
# -----------------------------------------------------------------------------


def _find_latest_passed_run_for_case(case_id: str) -> dict | None:
    """从 run_tasks 查指定 case 的最新 passed run（优先用 case_runs，否则回退 run_tasks.status='passed'）"""
    with connect() as conn:
        # 优先 case_runs（更精确，记录每次执行）
        try:
            row = conn.execute(
                """
                select cr.run_id, rt.finished_at, cr.started_at
                from case_runs cr
                left join run_tasks rt on rt.id = cr.run_id
                where cr.case_id = ? and cr.passed = 1
                order by cr.started_at desc
                limit 1
                """,
                (case_id,),
            ).fetchone()
            if row:
                return {"run_id": row["run_id"], "finished_at": row["finished_at"], "started_at": row["started_at"]}
        except sqlite3.OperationalError:
            pass
        # 回退 run_tasks（case_runs 暂未落库的兼容路径）
        row = conn.execute(
            """
            select id as run_id, finished_at, started_at
            from run_tasks
            where case_id = ? and status = 'passed'
            order by coalesce(finished_at, started_at, created_at) desc
            limit 1
            """,
            (case_id,),
        ).fetchone()
        if row:
            return {"run_id": row["run_id"], "finished_at": row["finished_at"], "started_at": row["started_at"]}
    return None


def compute_observed_asset_diff(existing: dict, observed: dict) -> dict:
    """纯函数：计算 observed vs existing automation_asset 的三段 diff。

    - kept：existing 中非空且与 observed 等价的字段子集（conservative 语义）
    - added：observed 独有但 existing 缺失的字段
    - missing：YAML 验证要求必须有的字段，且 existing / observed 都缺失

    不写库，便于单测。
    """
    existing = existing if isinstance(existing, dict) else {}
    observed = observed if isinstance(observed, dict) else {}

    def _is_non_empty(value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, (list, dict, str)) and len(value) == 0:
            return False
        return True

    def _equivalent(a: object, b: object) -> bool:
        """比较两个值是否等价（list 转 set 排序后再比，dict 比较 key 集合）"""
        if a is None or b is None:
            return a is None and b is None
        if isinstance(a, dict) and isinstance(b, dict):
            keys = set(a) | set(b)
            return all(_equivalent(a.get(k), b.get(k)) for k in keys)
        if isinstance(a, list) and isinstance(b, list):
            try:
                return sorted([json.dumps(x, ensure_ascii=False, sort_keys=True) for x in a]) == sorted(
                    [json.dumps(x, ensure_ascii=False, sort_keys=True) for x in b]
                )
            except TypeError:
                return a == b
        return a == b

    track_fields = ("operation_steps", "selectors", "input_values", "assertions")

    kept: dict = {}
    added: dict = {}
    for field in track_fields:
        ex_value = existing.get(field)
        ob_value = observed.get(field)
        if _is_non_empty(ex_value) and _is_non_empty(ob_value) and _equivalent(ex_value, ob_value):
            kept[field] = ex_value
        elif _is_non_empty(ob_value) and not _is_non_empty(ex_value):
            added[field] = ob_value
        elif _is_non_empty(ob_value) and _is_non_empty(ex_value):
            # 双方都有但不完全等价：保守视为 kept(existing)，并把差异的 observed 计入 added（提示用户）
            kept[field] = ex_value
            if not _equivalent(ex_value, ob_value):
                added[field] = ob_value
        # ex 非空 + ob 为空 → kept（保守不覆盖）
        elif _is_non_empty(ex_value):
            kept[field] = ex_value

    # missing：YAML 验证要求必须有，但两边都缺
    missing: list[str] = []
    if not _is_non_empty(existing.get("operation_steps")) and not _is_non_empty(observed.get("operation_steps")):
        missing.append("automation_asset.operation_steps")
    if not _is_non_empty(existing.get("assertions")) and not _is_non_empty(observed.get("assertions")):
        missing.append("automation_asset.assertions")
    if not _is_non_empty(existing.get("selectors")) and not _is_non_empty(observed.get("selectors")):
        missing.append("automation_asset.selectors")
    if not isinstance(existing.get("input_values"), dict):
        if not isinstance(observed.get("input_values"), dict):
            missing.append("automation_asset.input_values")

    return {"kept": kept, "added": added, "missing": missing}


@app.get("/api/cases/{case_id}/observed-asset-diff")
def get_observed_asset_diff(case_id: str) -> dict:
    """路线 A · T2：返回该 case 最新 passed run 的 observed vs 现有 YAML 的三段 diff。"""
    case_id_norm = normalize_case_id(case_id)
    latest = _find_latest_passed_run_for_case(case_id_norm)
    if not latest:
        raise HTTPException(status_code=404, detail="no passed run for case")
    run_id = latest["run_id"]

    try:
        observed = load_observed_asset_for_run(run_id)
    except HTTPException:
        raise
    case_path = find_case_yaml(case_id_norm)
    try:
        data = yaml.safe_load(case_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"case YAML parse failed: {exc}") from exc
    existing = data.get("automation_asset") if isinstance(data.get("automation_asset"), dict) else {}

    diff = compute_observed_asset_diff(existing, observed)
    return {
        "case_id": case_id_norm,
        "run_id": run_id,
        "diff": diff,
        "observed_at": observed.get("observed_at"),
    }


class AdoptionRequest(BaseModel):
    run_id: str
    mode: Literal["accept", "reject"]
    adopted_by: str | None = None


YAML_BACKUP_DIR = ROOT / ".codex-tmp" / "yaml-backup"


def _backup_yaml_before_write(case_id: str, case_path: Path) -> Path:
    """在覆盖 YAML 前备份到 .codex-tmp/yaml-backup/{case_id}-{ts}.yaml"""
    YAML_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    target = YAML_BACKUP_DIR / f"{case_id}-{ts}.yaml"
    target.write_text(case_path.read_text(encoding="utf-8"), encoding="utf-8")
    return target


@app.post("/api/cases/{case_id}/adoptions")
def post_adoption(case_id: str, payload: AdoptionRequest) -> dict:
    """路线 A · T3：accept → 合并 + 备份 + 落盘；reject → 仅写 asset_adoptions"""
    case_id_norm = normalize_case_id(case_id)
    run_id = payload.run_id
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id required")

    with connect() as conn:
        task = conn.execute("select * from run_tasks where id = ?", (run_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="run not found")
        if task["status"] != "passed":
            raise HTTPException(status_code=400, detail="only passed runs can be adopted")

    case_path = find_case_yaml(case_id_norm)
    try:
        original_text = case_path.read_text(encoding="utf-8")
        data = yaml.safe_load(original_text) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"case YAML parse failed: {exc}") from exc
    existing = data.get("automation_asset") if isinstance(data.get("automation_asset"), dict) else {}

    diff_summary: dict = {"kept": 0, "added": 0, "missing": 0}

    if payload.mode == "accept":
        try:
            observed = load_observed_asset_for_run(run_id)
        except HTTPException:
            raise
        diff = compute_observed_asset_diff(existing, observed)
        diff_summary = {
            "kept": len(diff.get("kept", {})),
            "added": len(diff.get("added", {})),
            "missing": len(diff.get("missing", [])),
        }

        # 备份原文件
        backup_path = _backup_yaml_before_write(case_id_norm, case_path)
        try:
            data["automation_asset"] = merge_automation_asset(existing, observed)
            new_text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
            validation = validate_case_yaml(new_text)
            if not validation["valid"]:
                # 回滚
                backup_text = backup_path.read_text(encoding="utf-8")
                case_path.write_text(backup_text, encoding="utf-8")
                raise HTTPException(
                    status_code=400,
                    detail=f"merged YAML validation failed: {'; '.join(validation['errors'])}",
                )
            case_path.write_text(new_text, encoding="utf-8")
        except Exception:
            # 任何异常都回滚
            if backup_path.exists():
                backup_text = backup_path.read_text(encoding="utf-8")
                case_path.write_text(backup_text, encoding="utf-8")
            raise
    else:
        # reject：YAML 不写，diff_summary 留空
        diff_summary = {"kept": 0, "added": 0, "missing": 0, "rejected": True}

    with connect() as conn:
        cur = conn.execute(
            """
            insert into asset_adoptions(case_id, run_id, mode, diff_summary_json, adopted_by, adopted_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                case_id_norm,
                run_id,
                payload.mode,
                json.dumps(diff_summary, ensure_ascii=False),
                payload.adopted_by,
                utc_now(),
            ),
        )
        adoption_id = cur.lastrowid

    result = {
        "case_id": case_id_norm,
        "run_id": run_id,
        "mode": payload.mode,
        "asset_adoption_id": adoption_id,
        "diff_summary": diff_summary,
    }
    if payload.mode == "accept":
        result["yaml_path"] = str(case_path)
    return result


@app.get("/api/cases/{case_id}/adoptions")
def get_adoptions(case_id: str, limit: int = Query(default=10, ge=1, le=50)) -> list[dict]:
    """路线 A · T3：按 adopted_at DESC 返回该 case 最近 N 条采纳历史"""
    case_id_norm = normalize_case_id(case_id)
    with connect() as conn:
        rows = conn.execute(
            """
            select id, case_id, run_id, mode, diff_summary_json, adopted_by, adopted_at
            from asset_adoptions
            where case_id = ?
            order by adopted_at desc
            limit ?
            """,
            (case_id_norm, limit),
        ).fetchall()
    results: list[dict] = []
    for row in rows:
        item = dict(row)
        try:
            item["diff_summary"] = json.loads(item.pop("diff_summary_json") or "null")
        except (TypeError, json.JSONDecodeError):
            item["diff_summary"] = None
        results.append(item)
    return results


# 路线 C · T11 / T12：YAML → Python codegen 端点
import py_compile  # 内置模块；用 import 形式方便 monkey-patch 测试
import ast

CODEGEN_TEMPLATE_REL = Path("runner") / "flows" / "templates" / "icm_case.py.j2"
FLOW_BACKUP_DIR = ROOT / ".codex-tmp" / "flow-backup"
CODEGEN_TEMPLATE_DIR = ROOT / "runner" / "flows" / "templates"

# 关键词正则清单（架构 §2 C2）：每个 tuple = (regex, dispatch_kind)
# dispatch_kind 仅用于 validate_operation_steps 的命中判定；模板内部用相同正则。
CODEGEN_KEYWORD_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"登录|prepare|已登录|确保登录|login"), "prepare_session"),
    (re.compile(r"打开|open|navigate|访问|进入|跳到|跳至"), "open_route"),
    (re.compile(r"搜索|查询|query|keyword|关键字"), "search"),
    (re.compile(r"输入|填写|fill|enter|键入"), "fill"),
    (re.compile(r"点击|click|按下|触发|submit|提交"), "click"),
    (re.compile(r"断言|assert|verify|确认|验证|可见"), "assert"),
    (re.compile(r"settle|等待|wait", re.IGNORECASE), "settle"),
)


class CodegenRequest(BaseModel):
    write: bool = False
    template: Literal["functional", "negative", "regression"] = "functional"


def compute_target_path(case_id: str) -> Path:
    """架构 §2 C3 命名规则：runner/flows/icm_case_XXX.py

    XXX 默认从 case_id 提取 TC-ICM- 后面的数字段。
    提取不到时回退到末段数字；都没有则用 case_id 全小写。
    """
    match = re.search(r"TC-ICM-(\d+)", case_id, flags=re.IGNORECASE)
    if match:
        suffix = match.group(1)
    else:
        tail = re.search(r"(\d+)$", case_id)
        suffix = tail.group(1) if tail else (case_id.lower() or "case")
    return ROOT / "runner" / "flows" / f"icm_case_{suffix}.py"


def validate_operation_steps(steps: list[str] | None) -> list[str]:
    """架构 §2 C2：未命中关键词的步骤进 errors（不允许落盘）。

    返回错误列表；空 list 表示全部命中。
    """
    if not steps:
        return ["missing operation_steps"]
    errors: list[str] = []
    for idx, raw in enumerate(steps):
        text = (raw or "").strip() if isinstance(raw, str) else ""
        if not text:
            errors.append(f"operation_steps[{idx}] is empty")
            continue
        if not any(rule.search(text) for rule, _ in CODEGEN_KEYWORD_RULES):
            errors.append(f"unsupported step kind: {text}")
    return errors


def _render_codegen_template(
    case_id: str,
    title: str,
    system_id: str,
    operation_steps: list[str],
    selectors: dict,
    input_values: dict,
    assertions: list[str],
    template_name: str,
) -> str:
    """用 Jinja2 渲染模板到内存字符串（架构 §2 C3 步骤 4）。"""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    env = Environment(
        loader=FileSystemLoader(str(CODEGEN_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )
    tpl = env.get_template("icm_case.py.j2")
    return tpl.render(
        case_id=case_id,
        title=title,
        system_id=system_id,
        operation_steps=list(operation_steps or []),
        selectors=dict(selectors or {}),
        input_values=dict(input_values or {}),
        assertions=list(assertions or []),
        template=template_name,
    )


def _append_codegen_log(case_id: str, message: str) -> None:
    """所有 codegen dry-run / write 进 run_logs，关键字前缀 codegen（架构 §8）。

    run_id 使用 'codegen-{case_id}-{ts}' 避免与真实 run 冲突。
    """
    try:
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        with connect() as conn:
            conn.execute(
                """
                insert into run_logs(run_id, stream, line, created_at)
                values (?, ?, ?, ?)
                """,
                (
                    f"codegen-{case_id}-{ts}",
                    "codegen",
                    message,
                    utc_now(),
                ),
            )
    except Exception:  # pragma: no cover - 防御
        pass


def _backup_flow_before_write(target: Path, case_id: str) -> Path | None:
    """落盘前备份：.codex-tmp/flow-backup/{case_id}-{ts}.py（首次生成时跳过）。"""
    if not target.exists():
        return None
    FLOW_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup = FLOW_BACKUP_DIR / f"{case_id}-{ts}.py"
    backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


@app.post("/api/cases/{case_id}/codegen")
def post_codegen(case_id: str, payload: CodegenRequest | None = None) -> dict:
    """路线 C · T11 / T12：dry-run / 落盘 + py_compile 自检。

    dry-run (write=false): 渲染模板到内存，py_compile 自检，**不**落盘。
    write=true: 备份旧 .py → 写盘 → 再次 py_compile → 失败回滚。提示人工检查 cases.py。
    """
    case_id_norm = normalize_case_id(case_id)
    payload = payload or CodegenRequest()
    target_path = compute_target_path(case_id_norm)

    # 1) 加载 case YAML
    try:
        case_path = find_case_yaml(case_id_norm)
    except HTTPException:
        return {
            "ok": False,
            "code": "",
            "target_path": str(target_path),
            "errors": [f"case YAML not found: {case_id_norm}"],
            "warnings": [],
        }

    try:
        data = yaml.safe_load(case_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {
            "ok": False,
            "code": "",
            "target_path": str(target_path),
            "errors": [f"case YAML parse failed: {exc}"],
            "warnings": [],
        }

    asset = data.get("automation_asset") or {}
    operation_steps: list[str] = [str(s) for s in (asset.get("operation_steps") or [])]
    selectors: dict = dict(asset.get("selectors") or {})
    input_values: dict = dict(asset.get("input_values") or {})
    assertions: list[str] = [str(a) for a in (asset.get("assertions") or [])]
    system_id = str(data.get("system") or "icm-internal")
    title = str(data.get("title") or case_id_norm)

    # 2) 优先拦截空 operation_steps（架构 §10 验收 #11 + PRD §4 REQ-C-05 细分错误码）
    if not operation_steps:
        _append_codegen_log(case_id_norm, "codegen missing operation_steps")
        return {
            "ok": False,
            "code": "",
            "target_path": str(target_path),
            "errors": ["missing operation_steps"],
            "warnings": [],
        }

    # 3) validate_case_yaml（基础字段 / selectors / assertions 等）
    validation = validate_case_yaml(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    if not validation["valid"]:
        return {
            "ok": False,
            "code": "",
            "target_path": str(target_path),
            "errors": list(validation.get("errors", [])),
            "warnings": list(validation.get("warnings", [])),
        }

    # 4) validate_operation_steps（关键词派发校验；架构 §2 C2）
    step_errors = validate_operation_steps(operation_steps)

    # 5) 渲染模板到内存
    try:
        code = _render_codegen_template(
            case_id=case_id_norm,
            title=title,
            system_id=system_id,
            operation_steps=operation_steps,
            selectors=selectors,
            input_values=input_values,
            assertions=assertions,
            template_name=payload.template,
        )
    except Exception as exc:
        _append_codegen_log(case_id_norm, f"codegen render failed: {exc}")
        return {
            "ok": False,
            "code": "",
            "target_path": str(target_path),
            "errors": [f"template render failed: {exc}"],
            "warnings": list(validation.get("warnings", [])),
        }

    # 6) 内存源码语法自检（满足 PRD §8 安全沙箱）
    try:
        ast.parse(code)
    except SyntaxError as exc:
        _append_codegen_log(case_id_norm, f"codegen syntax check failed (memory): {exc}")
        return {
            "ok": False,
            "code": code,
            "target_path": str(target_path),
            "errors": [f"py_compile failed: {exc}"],
            "warnings": list(validation.get("warnings", [])),
        }

    result: dict = {
        "ok": not step_errors,
        "code": code,
        "target_path": str(target_path),
        "errors": step_errors,
        "warnings": list(validation.get("warnings", [])),
    }

    # 6) 落盘流程
    if not payload.write:
        result["written"] = False
        _append_codegen_log(
            case_id_norm,
            f"codegen dry-run ok ({len(operation_steps)} steps, errors={len(step_errors)})",
        )
        return result

    # write=true：必须通过关键词校验才允许落盘
    if step_errors:
        result["ok"] = False
        result["written"] = False
        result["errors"] = step_errors + ["refused: operation_steps validation failed"]
        _append_codegen_log(case_id_norm, f"codegen write refused: {step_errors}")
        return result

    # 备份旧文件
    backup_path = _backup_flow_before_write(target_path, case_id_norm)
    wrote_existed_before = target_path.exists()

    # 写盘
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(code, encoding="utf-8")
    except Exception as exc:
        _append_codegen_log(case_id_norm, f"codegen write failed: {exc}")
        raise HTTPException(status_code=500, detail=f"failed to write flow: {exc}") from exc

    # 再次 py_compile 落盘文件
    try:
        py_compile.compile(str(target_path), doraise=True)
    except py_compile.PyCompileError as exc:
        # 回滚：若之前存在则恢复；否则删除（满足 P1 mock 覆盖目标）
        try:
            if backup_path is not None and backup_path.exists():
                target_path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
                _append_codegen_log(case_id_norm, f"codegen rollback: restored from {backup_path}")
            elif not wrote_existed_before:
                target_path.unlink(missing_ok=True)
                _append_codegen_log(case_id_norm, "codegen rollback: removed newly created file (no prior content)")
            else:
                # 理论上不会进此分支（wrote_existed_before==True 时 backup_path 必非 None），
                # 但保留防御性清理。
                target_path.unlink(missing_ok=True)
                _append_codegen_log(case_id_norm, "codegen rollback: removed inconsistent file (defensive)")
        except Exception as rollback_exc:  # pragma: no cover - 防御
            _append_codegen_log(
                case_id_norm,
                f"codegen rollback FAILED: {rollback_exc}; manual cleanup may be required for {target_path}",
            )
            raise HTTPException(
                status_code=500,
                detail=f"py_compile failed and rollback also failed: {rollback_exc}",
            ) from exc
        _append_codegen_log(case_id_norm, f"codegen write py_compile failed, rolled back: {exc}")
        return {
            "ok": False,
            "code": code,
            "target_path": str(target_path),
            "errors": [f"py_compile on disk failed, rolled back: {exc}"],
            "warnings": [],
        }

    _append_codegen_log(case_id_norm, f"codegen write ok: {target_path}")
    result["written"] = True
    result["backup_path"] = str(backup_path) if backup_path is not None else None
    result["message"] = "已写入，请人工检查 runner/cases.py:CASE_RUNNERS 是否需要追加"
    return result


# 路线 B · T7 / T8：稳定性计算 + scan 端点
STABILITY_THRESHOLD_DEFAULT = 0.95
STABILITY_UNSTABLE_THRESHOLD_DEFAULT = 0.80
STABILITY_INSUFFICIENT_THRESHOLD = 5  # 样本 < 5 视为 insufficient
SCAN_LOG_DIR = ROOT / "platform-data" / "runner-logs"


def _utc_now_iso() -> str:
    return utc_now()


def _compute_stability(case_id: str, window: int = 20) -> dict:
    """从 case_runs 派生稳定分（纯函数，不写库）。"""
    window = max(1, min(int(window or 20), 200))
    with connect() as conn:
        rows = conn.execute(
            """
            select passed, started_at, finished_at
            from case_runs
            where case_id = ?
            order by coalesce(started_at, finished_at) desc, id desc
            limit ?
            """,
            (case_id, window),
        ).fetchall()

    total = len(rows)
    passed = sum(1 for r in rows if int(r["passed"] or 0) == 1)
    pass_rate = (passed / total) if total else 0.0

    last_passed_at: str | None = None
    last_failed_at: str | None = None
    for r in rows:
        ts = r["finished_at"] or r["started_at"]
        if last_passed_at is None and int(r["passed"] or 0) == 1:
            last_passed_at = ts
        elif last_failed_at is None and int(r["passed"] or 0) == 0:
            last_failed_at = ts
        if last_passed_at and last_failed_at:
            break

    if total < STABILITY_INSUFFICIENT_THRESHOLD:
        status = "insufficient"
    elif pass_rate >= STABILITY_THRESHOLD_DEFAULT:
        status = "stable"
    elif pass_rate >= STABILITY_UNSTABLE_THRESHOLD_DEFAULT:
        status = "flaky"
    else:
        status = "unstable"

    return {
        "case_id": case_id,
        "total": total,
        "passed": passed,
        "pass_rate": round(pass_rate, 4),
        "status": status,
        "last_passed_at": last_passed_at,
        "last_failed_at": last_failed_at,
        "thresholds": {
            "stable": STABILITY_THRESHOLD_DEFAULT,
            "unstable": STABILITY_UNSTABLE_THRESHOLD_DEFAULT,
        },
        "insufficient_threshold": STABILITY_INSUFFICIENT_THRESHOLD,
        "window": window,
    }


@app.get("/api/cases/{case_id}/stability")
def get_case_stability(case_id: str, window: int = Query(default=20, ge=1, le=200)) -> dict:
    """路线 B · T7：从 case_runs 派生稳定分（默认窗口 20）。"""
    case_id_norm = normalize_case_id(case_id)
    return _compute_stability(case_id_norm, window=window)


def _append_scan_log(scan_id: str, message: str) -> None:
    try:
        SCAN_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = SCAN_LOG_DIR / f"{scan_id}.log"
        with log_path.open("a", encoding="utf-8") as fp:
            fp.write(f"[{_utc_now_iso()}] {message}\n")
    except Exception:  # pragma: no cover - 防御
        pass


def _run_stability_scan_thread(scan_id: str, case_id: str, times: int) -> None:
    """线程入口：在 stability_scans 中跑 N 次 case，写 case_runs，更新进度。"""
    _append_scan_log(scan_id, f"start scan_id={scan_id} case_id={case_id} times={times}")
    completed = 0
    passed_count = 0
    try:
        with connect() as conn:
            conn.execute("update stability_scans set status = 'running' where id = ?", (scan_id,))

        for i in range(1, times + 1):
            run_id = f"{scan_id}-{i:02d}"
            _append_scan_log(scan_id, f"running attempt {i}/{times} run_id={run_id}")
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "runner.main", "run-case", case_id, run_id, "--retry", "0"],
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=600,
                    check=False,
                )
                # 从 case_runs 查最新一行（runner 每次 attempt 都会写）
                with connect() as conn:
                    row = conn.execute(
                        """
                        select passed from case_runs
                        where case_id = ? and run_id = ?
                        order by id desc limit 1
                        """,
                        (case_id, run_id),
                    ).fetchone()
                if row is None:
                    _append_scan_log(scan_id, f"attempt {i} no case_runs row (rc={proc.returncode})")
                else:
                    if int(row["passed"] or 0) == 1:
                        passed_count += 1
                    _append_scan_log(
                        scan_id, f"attempt {i} passed={int(row['passed'] or 0)} rc={proc.returncode}"
                    )
            except subprocess.TimeoutExpired:
                _append_scan_log(scan_id, f"attempt {i} timed out")
            except Exception as exc:
                _append_scan_log(scan_id, f"attempt {i} error: {exc}")

            completed = i
            try:
                with connect() as conn:
                    conn.execute(
                        "update stability_scans set completed = ?, passed = ? where id = ?",
                        (completed, passed_count, scan_id),
                    )
            except Exception:
                pass

        final_status = "done" if completed == times else "failed"
        with connect() as conn:
            conn.execute(
                """
                update stability_scans
                set status = ?, completed = ?, passed = ?, finished_at = ?
                where id = ?
                """,
                (final_status, completed, passed_count, _utc_now_iso(), scan_id),
            )
        _append_scan_log(
            scan_id, f"scan {final_status} completed={completed} passed={passed_count}/{times}"
        )
    except Exception as exc:
        try:
            with connect() as conn:
                conn.execute(
                    """
                    update stability_scans
                    set status = 'failed', finished_at = ?
                    where id = ?
                    """,
                    (_utc_now_iso(), scan_id),
                )
        except Exception:
            pass
        _append_scan_log(scan_id, f"scan crashed: {exc}")


def _start_stability_scan(case_id: str, times: int) -> dict:
    """辅助函数（T7/T8 共享）：创建 stability_scans 行 + 启线程，返回 scan_id。"""
    if times < 1:
        raise HTTPException(status_code=400, detail="times must be >= 1")
    if times > 50:
        raise HTTPException(status_code=400, detail="times must be <= 50")

    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    now = _utc_now_iso()
    with connect() as conn:
        conn.execute(
            """
            insert into stability_scans(id, case_id, status, times, completed, passed, created_at)
            values (?, ?, 'queued', ?, 0, 0, ?)
            """,
            (scan_id, case_id, times, now),
        )
    thread = threading.Thread(
        target=_run_stability_scan_thread,
        args=(scan_id, case_id, times),
        name=f"icm-stability-scan-{scan_id}",
        daemon=True,
    )
    thread.start()
    return {
        "scan_id": scan_id,
        "case_id": case_id,
        "status": "queued",
        "times": times,
        "started_at": now,
    }


class StabilityScanRequest(BaseModel):
    times: int = 10


@app.post("/api/cases/{case_id}/stability-scan")
def post_stability_scan(case_id: str, payload: StabilityScanRequest | None = None) -> dict:
    """路线 B · T7：触发 stability scan。times 默认 10。返回 scan_id（异步执行不阻塞）。"""
    case_id_norm = normalize_case_id(case_id)
    times = (payload.times if payload else 10) or 10
    return _start_stability_scan(case_id_norm, times)


@app.post("/api/cases/{case_id}/recompute-stability")
def post_recompute_stability(case_id: str) -> dict:
    """路线 B · T8：固定 N=10 次重跑（与 PRD US-B4 "跑 10 次" 对齐）。"""
    case_id_norm = normalize_case_id(case_id)
    return _start_stability_scan(case_id_norm, times=10)


@app.get("/api/stability-scans/{scan_id}")
def get_stability_scan(scan_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            """
            select id, case_id, status, times, completed, passed, created_at, finished_at
            from stability_scans
            where id = ?
            """,
            (scan_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="scan not found")
    return dict(row)


@app.get("/api/reports")
def reports() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("select * from run_tasks order by created_at desc limit 100").fetchall()
    tasks = rows_to_dicts(rows)
    report_meta = {item["run_id"]: item for item in list_reports(limit=100)}
    items: list[dict] = []
    for task in tasks:
        detail = load_step_details(str(task["id"])) or {}
        report = report_meta.get(str(task["id"]), {})
        items.append(
            {
                "id": str(task["id"]),
                "run_id": str(task["id"]),
                "case_id": task.get("case_id"),
                "case_name": detail.get("case_name") or report.get("case_name") or task.get("case_id") or str(task["id"]),
                "mode": _normalized_mode(str(task.get("mode") or "")),
                "status": _normalized_status(str(task.get("status") or "")),
                "operator": "admin",
                "started_at": task.get("started_at") or task.get("created_at"),
                "finished_at": task.get("finished_at"),
                "has_report": bool(task.get("report_path")),
                "has_evidence": bool(evidence_summary(str(task["id"])).get("root")),
            }
        )
    items.sort(key=lambda item: (0 if item["status"] == "failed" else 1, item.get("finished_at") or item.get("started_at") or ""), reverse=False)
    return items


@app.get("/api/reports/{run_id}")
def report_detail(run_id: str) -> dict:
    try:
        report = read_report(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc
    meta = parse_report(report)
    screenshots = meta["screenshots"]
    if not screenshots and meta["case_id"]:
        screenshots = [screenshot_payload(meta["case_id"], path) for path in latest_screenshots(meta["case_id"])]
    analysis = load_cached_report_analysis(run_id, report) or ai_service.analyze_run_report(report, screenshots, evidence_log_lines(run_id))
    return {
        "run_id": run_id,
        "metadata": meta,
        "markdown": report,
        "screenshots": screenshots,
        "evidence": evidence_summary(run_id),
        "analysis": analysis,
    }


@app.post("/api/reports/{run_id}/analyze")
def analyze_report_with_ai(run_id: str, payload: AnalyzeReportRequest | None = None) -> dict:
    try:
        report = read_report(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc
    meta = parse_report(report)
    screenshots = meta["screenshots"]
    if not screenshots and meta["case_id"]:
        screenshots = [screenshot_payload(meta["case_id"], path) for path in latest_screenshots(meta["case_id"])]
    settings = get_ai_settings(mask_key=False)
    force = bool(payload.force) if payload else False
    cached = None if force else load_cached_report_analysis(run_id, report, settings)
    if cached:
        return {**cached, "cached": True}
    with connect() as conn:
        rows = conn.execute("select line from run_logs where run_id = ? order by id", (run_id,)).fetchall()
    try:
        analysis = ai_service.analyze_run_report_with_ai(
            report,
            screenshots,
            [row["line"] for row in rows] + evidence_log_lines(run_id),
            settings,
        )
        save_report_analysis(run_id, report, settings, analysis)
        return {**analysis, "cached": False}
    except AIConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/reports/{run_id}/analyses")
def report_analysis_versions(run_id: str) -> list[dict]:
    try:
        report = read_report(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc
    return load_report_analysis_versions(run_id, report)


@app.get("/api/screenshots/latest/{case_id}/{filename}")
def screenshot_file(case_id: str, filename: str) -> FileResponse:
    path = SCREENSHOTS_LATEST_DIR / case_id / filename
    if not path.exists() or path.suffix.lower() != ".png":
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(path)


@app.get("/api/screenshots/runs/{run_id}/{filename}")
def run_screenshot_file(run_id: str, filename: str) -> FileResponse:
    path = SCREENSHOTS_RUNS_DIR / run_id / filename
    if not path.exists() or path.suffix.lower() != ".png":
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(path)


def screenshot_payload(case_id: str, path: str) -> dict[str, str]:
    filename = path.replace("\\", "/").rsplit("/", 1)[-1]
    return {
        "case_id": case_id,
        "filename": filename,
        "path": path,
        "url": f"/api/screenshots/latest/{case_id}/{filename}",
    }


def run_screenshot_payload(run_id: str, path: str) -> dict[str, str]:
    filename = path.replace("\\", "/").rsplit("/", 1)[-1]
    return {
        "case_id": run_id,
        "filename": filename,
        "path": path,
        "url": f"/api/screenshots/runs/{run_id}/{filename}",
    }


def path_health(path: Path) -> dict:
    exists = path.exists()
    stat = path.stat() if exists else None
    return {
        "path": str(path),
        "exists": exists,
        "is_dir": path.is_dir() if exists else False,
        "updated_at": datetime_from_mtime(stat.st_mtime) if stat else None,
    }


def sqlite_health() -> dict:
    exists = DB_PATH.exists()
    stat = DB_PATH.stat() if exists else None
    return {
        "path": str(DB_PATH),
        "exists": exists,
        "size_bytes": stat.st_size if stat else 0,
        "updated_at": datetime_from_mtime(stat.st_mtime) if stat else None,
    }


def datetime_from_mtime(mtime: float) -> str:
    return datetime.fromtimestamp(mtime).isoformat(timespec="seconds")


def report_hash(report: str) -> str:
    return sha256(report.encode("utf-8")).hexdigest()


def load_cached_report_analysis(run_id: str, report: str, settings: dict | None = None) -> dict | None:
    digest = report_hash(report)
    provider = settings.get("provider") if settings else None
    model = settings.get("model") if settings else None
    with connect() as conn:
        if provider and model:
            row = conn.execute(
                """
                select * from report_analyses
                where run_id = ? and report_hash = ? and provider = ? and model = ?
                order by updated_at desc
                limit 1
                """,
                (run_id, digest, provider, model),
            ).fetchone()
        else:
            row = conn.execute(
                """
                select * from report_analyses
                where run_id = ? and report_hash = ?
                order by updated_at desc
                limit 1
                """,
                (run_id, digest),
            ).fetchone()
    if not row:
        return None
    try:
        analysis = json.loads(row["analysis_json"])
    except json.JSONDecodeError:
        return None
    return {**analysis, "cached": True, "cached_at": row["updated_at"]}


def save_report_analysis(run_id: str, report: str, settings: dict, analysis: dict) -> None:
    now = utc_now()
    provider = str(settings.get("provider", ""))
    model = str(settings.get("model", ""))
    payload = json.dumps(analysis, ensure_ascii=False)
    digest = report_hash(report)
    with connect() as conn:
        conn.execute(
            """
            insert into report_analysis_versions(run_id, report_hash, provider, model, analysis_json, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (run_id, digest, provider, model, payload, now),
        )
        conn.execute(
            """
            insert into report_analyses(run_id, report_hash, provider, model, analysis_json, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(run_id, report_hash, provider, model) do update set
              analysis_json = excluded.analysis_json,
              updated_at = excluded.updated_at
            """,
            (run_id, digest, provider, model, payload, now, now),
        )


def load_report_analysis_versions(run_id: str, report: str) -> list[dict]:
    digest = report_hash(report)
    with connect() as conn:
        rows = conn.execute(
            """
            select * from report_analysis_versions
            where run_id = ? and report_hash = ?
            order by created_at desc, id desc
            limit 20
            """,
            (run_id, digest),
        ).fetchall()
    versions: list[dict] = []
    for row in rows:
        try:
            analysis = json.loads(row["analysis_json"])
        except json.JSONDecodeError:
            continue
        versions.append(
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "provider": row["provider"],
                "model": row["model"],
                "created_at": row["created_at"],
                "analysis": {**analysis, "cached": True, "cached_at": row["created_at"]},
            }
        )
    return versions


def is_confirmed_status(status: str) -> bool:
    normalized = status.strip().lower()
    return normalized in {"已确认", "confirmed", "passed", "通过"} or "确认" in status


def load_requirement_title(requirement_id: int | None) -> str:
    if not requirement_id:
        return ""
    with connect() as conn:
        row = conn.execute("select title from requirements where id = ?", (requirement_id,)).fetchone()
    return str(row["title"]) if row else ""


def next_test_point_sort_order(parent_id: int | None) -> int:
    with connect() as conn:
        if parent_id is None:
            row = conn.execute("select coalesce(max(sort_order), 0) + 1 as next_order from test_points where parent_id is null").fetchone()
        else:
            row = conn.execute(
                "select coalesce(max(sort_order), 0) + 1 as next_order from test_points where parent_id = ?",
                (parent_id,),
            ).fetchone()
    return int(row["next_order"] if row else 1)


def ensure_manual_requirement() -> int:
    title = "测试点思维导图手工维护"
    project_id = resolve_requirement_project_id()
    with connect() as conn:
        row = conn.execute("select id from requirements where title = ? order by id limit 1", (title,)).fetchone()
        if row:
            conn.execute("update requirements set project_id = coalesce(nullif(project_id, ''), ?) where id = ?", (project_id, int(row["id"])))
            return int(row["id"])
        now = utc_now()
        cur = conn.execute(
            """
            insert into requirements(title, document, status, analysis_summary, risk_summary, case_count, project_id, created_at, updated_at)
            values (?, ?, 'manual', '', '', 0, 'proj-icm-default', ?, ?)
            """,
            (title, "测试点菜单中手工新增的测试点。", now, now),
        )
        return int(cur.lastrowid)


def ensure_generated_requirement(points: list[dict]) -> int:
    title = "测试点思维导图选中生成"
    document = "\n".join(str(point.get("name", "")) for point in points)
    now = utc_now()
    with connect() as conn:
        cur = conn.execute(
            """
            insert into requirements(title, document, status, analysis_summary, risk_summary, case_count, project_id, created_at, updated_at)
            values (?, ?, 'draft', '', '', ?, 'proj-icm-default', ?, ?)
            """,
            (title, document, len(points), now, now),
        )
        return int(cur.lastrowid)


def load_case_draft(draft_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            """
            select cd.*, r.title as requirement_title
            from case_drafts cd
            left join requirements r on r.id = cd.requirement_id
            where cd.id = ?
            """,
            (draft_id,),
        ).fetchone()
    return normalize_case_draft(dict(row)) if row else None


def normalize_case_draft(row: dict) -> dict:
    raw_ids = row.get("source_test_point_ids") or "[]"
    try:
        source_ids = json.loads(raw_ids)
    except (TypeError, json.JSONDecodeError):
        source_ids = []
    return {**row, "source_test_point_ids": source_ids if isinstance(source_ids, list) else []}


def draft_title_for_template(template: str) -> str:
    return {
        "functional": "测试点生成 - 功能用例草稿",
        "negative": "测试点生成 - 异常用例草稿",
        "regression": "测试点生成 - 回归用例草稿",
        "e2e": "测试点生成 - 端到端链路草稿",
    }.get(template, "测试点生成 - YAML 草稿")


def normalize_case_id(case_id: str) -> str:
    value = case_id.strip().upper()
    if not re.fullmatch(r"TC-ICM-[0-9A-Z-]+", value):
        raise HTTPException(status_code=400, detail="case_id must look like TC-ICM-013")
    return value


def normalize_case_filename(filename: str | None, case_id: str) -> str:
    value = (filename or f"{case_id.lower()}-generated.yaml").strip()
    if not value.endswith((".yaml", ".yml")):
        value = f"{value}.yaml"
    if "/" in value or "\\" in value or ".." in value:
        raise HTTPException(status_code=400, detail="filename must be a plain yaml filename")
    if not value.lower().startswith(case_id.lower()):
        value = f"{case_id.lower()}-{value}"
    return value


def replace_yaml_case_id(yaml_text: str, case_id: str) -> str:
    if re.search(r"^id:\s*.+$", yaml_text, flags=re.MULTILINE):
        return re.sub(r"^id:\s*.+$", f"id: {case_id}", yaml_text, count=1, flags=re.MULTILINE)
    return f"id: {case_id}\n{yaml_text}"


def load_observed_asset_for_run(run_id: str) -> dict:
    path = OBSERVED_ASSET_DIR / f"{run_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="observed asset not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="observed asset is not valid JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="observed asset root must be an object")
    return data


def find_case_yaml(case_id: str) -> Path:
    for path in sorted(TEST_CASE_DIR.glob(f"{case_id}*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if data.get("id") == case_id:
            return path
    raise HTTPException(status_code=404, detail=f"case YAML not found: {case_id}")


def merge_automation_asset(existing: dict, observed: dict) -> dict:
    merged = {
        "status": "verified",
        "source": observed.get("source", "playwright_observed"),
        "observed_at": observed.get("observed_at"),
        "evidence": observed.get("evidence", {}),
        "operation_steps": existing.get("operation_steps") or observed.get("operation_steps") or [],
        "selectors": existing.get("selectors") or observed.get("selectors") or {},
        "input_values": existing.get("input_values") or observed.get("input_values") or {},
        "assertions": existing.get("assertions") or observed.get("assertions") or [],
    }
    return {key: value for key, value in merged.items() if value is not None}


def validate_case_yaml(yaml_text: str) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return {"valid": False, "errors": [f"YAML syntax error: {exc}"], "warnings": [], "parsed_id": None}

    if not isinstance(data, dict):
        return {"valid": False, "errors": ["YAML root must be a mapping/object"], "warnings": [], "parsed_id": None}

    for field in ("id", "title", "status"):
        if not is_non_empty_scalar(data.get(field)):
            errors.append(f"missing or empty required field: {field}")

    for field in ("steps", "expected_results"):
        if not is_non_empty_list(data.get(field)):
            errors.append(f"missing or empty required list: {field}")

    asset = data.get("automation_asset")
    if not isinstance(asset, dict):
        errors.append("missing or invalid required mapping: automation_asset")
    else:
        for field in ("operation_steps", "assertions"):
            if not is_non_empty_list(asset.get(field)):
                errors.append(f"automation_asset.{field} must be a non-empty list")
        if not is_non_empty_selectors(asset.get("selectors")):
            errors.append("automation_asset.selectors must be a non-empty list or mapping")
        if "input_values" not in asset or not isinstance(asset.get("input_values"), dict):
            errors.append("automation_asset.input_values must be a mapping")
        elif not asset.get("input_values"):
            warnings.append("automation_asset.input_values is empty; confirm this case really has no inputs")

    parsed_id = str(data.get("id")) if data.get("id") is not None else None
    if parsed_id == "TC-ICM-DRAFT":
        warnings.append("case id is still TC-ICM-DRAFT; promote will replace it with the formal case id")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "parsed_id": parsed_id}


def is_non_empty_scalar(value: object) -> bool:
    return isinstance(value, (str, int, float)) and str(value).strip() != ""


def is_non_empty_list(value: object) -> bool:
    return isinstance(value, list) and len(value) > 0


def is_non_empty_selectors(value: object) -> bool:
    return (isinstance(value, list) and len(value) > 0) or (isinstance(value, dict) and len(value) > 0)


def load_requirement_detail(requirement_id: int) -> dict | None:
    with connect() as conn:
        requirement = conn.execute("select * from requirements where id = ?", (requirement_id,)).fetchone()
        if not requirement:
            return None
        points = conn.execute(
            "select * from test_points where requirement_id = ? order by coalesce(sort_order, id), id",
            (requirement_id,),
        ).fetchall()
        drafts = conn.execute("select * from case_drafts where requirement_id = ? order by created_at desc", (requirement_id,)).fetchall()
    return {
        "requirement": dict(requirement),
        "test_points": rows_to_dicts(points),
        "drafts": rows_to_dicts(drafts),
    }
