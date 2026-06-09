from __future__ import annotations

import json
import importlib.util
import re
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
from icm_platform.db import connect, get_ai_settings, get_platform_settings, init_db, rows_to_dicts, save_ai_settings, save_platform_settings, utc_now
from icm_platform.paths import DB_PATH, OBSERVED_ASSET_DIR, REPORT_DIR, ROOT, SCREENSHOTS_LATEST_DIR, SCREENSHOTS_RUNS_DIR, SPEC_FILE, TEST_CASE_DIR
from icm_platform.run_views import summarize_run_task
from icm_platform.worker import RunnerWorker

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


class PromoteDraftRequest(BaseModel):
    case_id: str
    filename: str | None = None


class ValidateDraftRequest(BaseModel):
    yaml: str | None = None
    case_id: str | None = None


class AnalyzeReportRequest(BaseModel):
    force: bool = False


class RunRequest(BaseModel):
    mode: Literal["run-case", "run-batch"]
    case_id: str | None = None


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


@app.get("/api/requirements/{requirement_id}")
def requirement_detail(requirement_id: int) -> dict:
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
    with connect() as conn:
        cur = conn.execute(
            """
            insert into requirements(title, document, status, analysis_summary, risk_summary, case_count, created_at, updated_at)
            values (?, ?, 'analyzed', ?, ?, ?, ?, ?)
            """,
            (
                payload.title,
                payload.document,
                result["analysis_summary"],
                result["risk_summary"],
                result["case_count"],
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


def _save_spec_case_drafts(requirement_id: int, cases: list[dict]) -> list[dict]:
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
    try:
        result = ai_service.generate_test_cases_spec(
            payload.document,
            standard_text,
            get_ai_settings(mask_key=False),
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
            insert into requirements(title, document, status, analysis_summary, risk_summary, case_count, created_at, updated_at)
            values (?, ?, 'analyzed', ?, ?, ?, ?, ?)
            """,
            (
                payload.title,
                payload.document,
                analysis_summary,
                risk_summary,
                len(cases),
                now,
                now,
            ),
        )
        requirement_id = cur.lastrowid
    _save_spec_case_drafts(requirement_id, cases)
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


@app.post("/api/runs")
def create_run(payload: RunRequest) -> dict[str, str | None]:
    try:
        return worker.enqueue(payload.mode, payload.case_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs")
def runs() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("select * from run_tasks order by created_at desc limit 50").fetchall()
    tasks = rows_to_dicts(rows)
    return [{**task, "summary": summarize_run_task(task)} for task in tasks]


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
    log_dicts = rows_to_dicts(logs)
    return {
        "task": task_dict,
        "summary": summarize_run_task(task_dict),
        "logs": log_dicts,
        "children": children,
        "report": report,
        "screenshots": screenshots,
        "analysis": ai_service.analyze_run_report(report, screenshots, [row["line"] for row in log_dicts]) if report else None,
    }


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


@app.get("/api/reports")
def reports() -> list[dict]:
    return list_reports()


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
    analysis = load_cached_report_analysis(run_id, report) or ai_service.analyze_run_report(report, screenshots, [])
    return {"run_id": run_id, "metadata": meta, "markdown": report, "screenshots": screenshots, "analysis": analysis}


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
            [row["line"] for row in rows],
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


def screenshot_payload(case_id: str, path: str) -> dict[str, str]:
    filename = path.replace("\\", "/").rsplit("/", 1)[-1]
    return {
        "case_id": case_id,
        "filename": filename,
        "path": path,
        "url": f"/api/screenshots/latest/{case_id}/{filename}",
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
    with connect() as conn:
        row = conn.execute("select id from requirements where title = ? order by id limit 1", (title,)).fetchone()
        if row:
            return int(row["id"])
        now = utc_now()
        cur = conn.execute(
            """
            insert into requirements(title, document, status, analysis_summary, risk_summary, case_count, created_at, updated_at)
            values (?, ?, 'manual', '', '', 0, ?, ?)
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
            insert into requirements(title, document, status, analysis_summary, risk_summary, case_count, created_at, updated_at)
            values (?, ?, 'draft', '', '', ?, ?, ?)
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
