import asyncio
import json

from runner import element_knowledge_refresh


def fake_scan_results():
    return [
        {
            "page": {"page_id": "users", "name": "用户管理", "route": "#/users"},
            "observation": {
                "url": "http://localhost:5173/#/users",
                "title": "用户管理",
                "visibleText": ["新增用户"],
                "interactives": [
                    {
                        "ref": "e1",
                        "tag": "button",
                        "text": "新增用户",
                        "selector": "button.add",
                    }
                ],
            },
        }
    ]


def write_feedback(path):
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "records": [
                    {
                        "key": "users.add_user_button",
                        "element_id": "users.add_user_button",
                        "page_id": "users",
                        "state": "default",
                        "action": "click",
                        "selector": "button.add",
                        "success": False,
                        "error": "Agent target is not visible: ['button.add']",
                        "created_at": "2026-07-09T00:00:00Z",
                    }
                ],
                "stats": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_refresh_library_from_scan_results_writes_enriched_library_and_summary(tmp_path):
    feedback_path = tmp_path / "feedback.json"
    output_path = tmp_path / "library.json"
    summary_path = tmp_path / "summary.json"
    write_feedback(feedback_path)

    summary = element_knowledge_refresh.refresh_library_from_scan_results(
        fake_scan_results(),
        feedback_path=feedback_path,
        output_path=output_path,
        summary_path=summary_path,
    )

    library = json.loads(output_path.read_text(encoding="utf-8"))
    written_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["element_count"] == 1
    assert written_summary["feedback_record_count"] == 1
    assert library["elements"][0]["execution_count"] == 1
    assert library["elements"][0]["healing_issue"] == "target_not_visible"
    assert library["refresh_source"] == "scan_results"
    assert summary["markdown_report_path"] == str(tmp_path / "refresh-report.md")
    assert summary["html_report_path"] == str(tmp_path / "refresh-report.html")
    assert (tmp_path / "refresh-report.md").exists()
    assert (tmp_path / "refresh-report.html").exists()


def test_refresh_library_file_no_scan_enriches_existing_library(tmp_path):
    library_path = tmp_path / "library.json"
    feedback_path = tmp_path / "feedback.json"
    output_path = tmp_path / "refreshed.json"
    summary_path = tmp_path / "summary.json"
    library_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "pages": [{"page_id": "users"}],
                "elements": [{"element_id": "users.add_user_button", "name": "add_user_button"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    write_feedback(feedback_path)

    summary = element_knowledge_refresh.refresh_library_file(
        library_path=library_path,
        feedback_path=feedback_path,
        output_path=output_path,
        summary_path=summary_path,
    )

    refreshed = json.loads(output_path.read_text(encoding="utf-8"))
    assert summary["source"] == str(library_path)
    assert summary["page_count"] == 1
    assert refreshed["elements"][0]["success_rate"] == 0.0
    assert refreshed["elements"][0]["healing_issue"] == "target_not_visible"


def test_refresh_element_knowledge_requires_page_when_scan_enabled():
    try:
        asyncio.run(element_knowledge_refresh.refresh_element_knowledge(scan=True, page=None))
    except ValueError as exc:
        assert "page is required" in str(exc)
    else:
        raise AssertionError("expected missing page error")


def test_quality_gate_uses_unique_default_state_baseline(tmp_path):
    library_path = tmp_path / "library.json"
    default_elements = [
        {
            "page_id": "device_list",
            "state": "default",
            "selectors": [f"button.device-{index}"],
            "actions": ["click"],
        }
        for index in range(45)
    ]
    state_duplicates = [
        {
            "page_id": "device_list",
            "state": "dialog:create",
            "selectors": [f"button.device-{index % 45}"],
            "actions": ["click"],
        }
        for index in range(135)
    ]
    library_path.write_text(json.dumps({"elements": default_elements + state_duplicates}), encoding="utf-8")

    counts = element_knowledge_refresh._previous_page_counts(library_path)
    targets = element_knowledge_refresh._targets_with_quality_gate(
        [{"page_id": "device_list", "minimum_interactive_count": 30}],
        counts,
    )

    assert counts == {"device_list": 45}
    assert targets[0]["minimum_interactive_count"] == 30


def test_refresh_element_knowledge_no_scan_uses_existing_library(tmp_path):
    library_path = tmp_path / "library.json"
    feedback_path = tmp_path / "feedback.json"
    output_path = tmp_path / "out.json"
    library_path.write_text(
        json.dumps({"version": "1.0", "pages": [], "elements": [{"element_id": "users.add_user_button"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    write_feedback(feedback_path)

    summary = asyncio.run(
        element_knowledge_refresh.refresh_element_knowledge(
            scan=False,
            library_path=library_path,
            feedback_path=feedback_path,
            output_path=output_path,
        )
    )

    assert summary["element_count"] == 1
    assert output_path.exists()


def test_refresh_element_knowledge_preserves_unscanned_pages_for_explicit_target(tmp_path, monkeypatch):
    library_path = tmp_path / "library.json"
    library_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "pages": [{"page_id": "users", "name": "Users"}, {"page_id": "login", "name": "Old login"}],
                "elements": [
                    {"element_id": "users.add", "page_id": "users"},
                    {"element_id": "login.old", "page_id": "login"},
                ],
            }
        ),
        encoding="utf-8",
    )

    async def fake_scan_targets(*_args, **_kwargs):
        return {
            "version": "1.0",
            "pages": [{"page_id": "login", "name": "Login"}],
            "elements": [{"element_id": "login.submit", "page_id": "login"}],
        }

    monkeypatch.setattr(element_knowledge_refresh, "scan_targets", fake_scan_targets)
    summary = asyncio.run(
        element_knowledge_refresh.refresh_element_knowledge(
            page=object(),
            targets=[{"page_id": "login", "url": "https://example.test/#/login"}],
            library_path=library_path,
            preserve_unscanned_pages=True,
        )
    )

    merged = json.loads(library_path.read_text(encoding="utf-8"))
    assert summary["page_count"] == 2
    assert {page["page_id"] for page in merged["pages"]} == {"users", "login"}
    assert {element["element_id"] for element in merged["elements"]} == {"users.add", "login.submit"}
