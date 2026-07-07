from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import yaml

from runner.operation_knowledge import (
    attach_trusted_knowledge_to_plan,
    build_trusted_catalog,
    load_passed_formal_case_ids,
    load_trusted_plan,
    retrieve_stage_knowledge,
    write_pending_agent_asset,
)


def _write_case(case_dir: Path, case_id: str, route: str) -> None:
    payload = {
        "id": case_id,
        "system": "icm-internal",
        "title": f"{case_id} device case",
        "automation_asset": {
            "operation_steps": [f"Open {route}", "Click add device"],
            "selectors": {"device_route": [route], "add_button": ["role=button[name='新增']"]},
            "input_values": {"device_name": "TestDev_01"},
            "assertions": ["The device row is visible"],
        },
    }
    (case_dir / f"{case_id}.yaml").write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")


def test_catalog_only_accepts_passed_cases_with_formal_flows(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases"
    flow_dir = tmp_path / "flows"
    case_dir.mkdir()
    flow_dir.mkdir()
    _write_case(case_dir, "TC-ICM-001", "#/hubble/device")
    _write_case(case_dir, "TC-ICM-002", "#/hubble/device")
    (flow_dir / "icm_case_001.py").write_text("async def run(): pass\n", encoding="utf-8")

    catalog = build_trusted_catalog(case_dir, flow_dir, {"TC-ICM-001", "TC-ICM-002"})

    assert [item["case_id"] for item in catalog] == ["TC-ICM-001"]
    assert catalog[0]["trust"] == "formal_passed"


def test_retrieval_requires_same_system_and_exact_route(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases"
    flow_dir = tmp_path / "flows"
    case_dir.mkdir()
    flow_dir.mkdir()
    _write_case(case_dir, "TC-ICM-003", "#/hubble/device")
    (flow_dir / "icm_case_003.py").write_text("async def run(): pass\n", encoding="utf-8")
    catalog = build_trusted_catalog(case_dir, flow_dir, {"TC-ICM-003"})

    matched = retrieve_stage_knowledge(catalog, system="icm-internal", target_route="#/hubble/device")
    unmatched = retrieve_stage_knowledge(catalog, system="icm-internal", target_route="#/hubble/server")

    assert matched[0]["selectors"]["add_button"] == ["role=button[name='新增']"]
    assert unmatched == []


def test_passed_formal_ids_exclude_agent_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "platform.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("create table run_tasks(id text, mode text, case_id text, status text)")
        conn.executemany(
            "insert into run_tasks values (?, ?, ?, ?)",
            [
                ("r1", "run-case", "TC-ICM-001", "passed"),
                ("r2", "agent-explore", "TC-ICM-002", "passed"),
                ("r3", "run-case", "TC-ICM-003", "failed"),
                ("r4", "run-draft", "TC-ICM-004", "passed"),
            ],
        )

    assert load_passed_formal_case_ids(db_path) == {"TC-ICM-001"}


def test_successful_agent_asset_is_written_only_to_pending_review(tmp_path: Path) -> None:
    trace = {
        "ok": True,
        "status": "passed",
        "final_url": "https://icm/#/hubble/device",
        "history": [{"decision": {"action": "click", "reason": "点击新增按钮"}}],
    }

    path = write_pending_agent_asset(tmp_path, "ui-123", {"id": "ICMDEV_FUN_001"}, trace)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.parent.name == "pending"
    assert payload["review_status"] == "pending"
    assert payload["enabled"] is False
    assert not (tmp_path / "trusted" / "ui-123.json").exists()


def test_plan_receives_only_exact_route_knowledge() -> None:
    catalog = [
        {
            "case_id": "TC-ICM-003",
            "system": "icm-internal",
            "routes": ["#/hubble/device"],
            "selectors": {"add_button": ["role=button[name='新增']"]},
            "operation_steps": ["Open device page", "Click add"],
            "assertions": [],
            "flow_path": "runner/flows/icm_case_003.py",
            "trust": "formal_passed",
        }
    ]
    plan = {
        "stages": [
            {"stage_id": "navigation", "target_route": "#/hubble/device"},
            {"stage_id": "assertion", "target_route": "#/hubble/server"},
        ]
    }

    enriched = attach_trusted_knowledge_to_plan(plan, catalog, system="icm-internal")

    assert enriched["stages"][0]["trusted_knowledge"][0]["case_id"] == "TC-ICM-003"
    assert enriched["stages"][1]["trusted_knowledge"] == []


def test_runtime_plan_loads_only_database_verified_formal_assets(tmp_path: Path) -> None:
    case_dir = tmp_path / "cases"
    flow_dir = tmp_path / "flows"
    case_dir.mkdir()
    flow_dir.mkdir()
    _write_case(case_dir, "TC-ICM-004", "#/hubble/device")
    (flow_dir / "icm_case_004.py").write_text("async def run(): pass\n", encoding="utf-8")
    db_path = tmp_path / "platform.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("create table run_tasks(id text, mode text, case_id text, status text)")
        conn.execute("insert into run_tasks values ('r1', 'run-case', 'TC-ICM-004', 'passed')")

    plan = load_trusted_plan(
        {"system": "icm-internal"},
        {"stages": [{"target_route": "#/hubble/device"}]},
        db_path=db_path,
        case_dir=case_dir,
        flow_dir=flow_dir,
    )

    assert plan["stages"][0]["trusted_knowledge"][0]["case_id"] == "TC-ICM-004"
