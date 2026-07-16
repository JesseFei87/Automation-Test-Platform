import json

from runner import element_self_healing


def test_classify_error_known_categories():
    assert element_self_healing.classify_error("Agent selected unknown ref: e9") == "unknown_ref"
    assert element_self_healing.classify_error("Agent target is not visible: ['#go']") == "target_not_visible"
    assert element_self_healing.classify_error("subtree intercepts pointer events") == "covered_by_overlay"
    assert element_self_healing.classify_error("strict mode violation: resolved to 2 elements") == "selector_unstable"
    assert element_self_healing.classify_error("operation timeout 8000ms") == "timeout"


def test_build_healing_suggestions_groups_failures_by_element_id():
    records = [
        {
            "key": "users.create_button",
            "element_id": "users.create_button",
            "action": "click",
            "selector": "button.add",
            "success": False,
            "error": "Agent target is not visible: ['button.add']",
            "created_at": "2026-07-09T00:00:00Z",
        },
        {
            "key": "users.create_button",
            "element_id": "users.create_button",
            "action": "click",
            "selector": "button.add",
            "success": True,
            "error": None,
            "created_at": "2026-07-09T00:00:01Z",
        },
        {
            "key": "users.create_button",
            "element_id": "users.create_button",
            "action": "click",
            "selector": "button.add",
            "success": False,
            "error": "element is not visible",
            "created_at": "2026-07-09T00:00:02Z",
        },
    ]

    suggestions = element_self_healing.build_healing_suggestions(records, min_failures=2)

    item = suggestions["users.create_button"]
    assert item["primary_issue"] == "target_not_visible"
    assert item["failure_count"] == 2
    assert item["issue_counts"] == {"target_not_visible": 2}
    assert item["success_rate"] == 0.3333
    assert "Scroll" in item["suggestion"]


def test_build_healing_suggestions_respects_min_failures():
    records = [
        {
            "key": "users.create_button",
            "element_id": "users.create_button",
            "success": False,
            "error": "timeout",
        }
    ]

    assert element_self_healing.build_healing_suggestions(records, min_failures=2) == {}


def test_merge_healing_into_library_adds_advisory_fields():
    library = {
        "elements": [
            {"element_id": "users.create_button", "name": "create_button"},
            {"element_id": "users.delete_button", "name": "delete_button"},
        ]
    }
    healing = {
        "users.create_button": {
            "primary_issue": "covered_by_overlay",
            "suggestion": "Dismiss stale overlays before retrying.",
            "failure_count": 2,
        }
    }

    merged = element_self_healing.merge_healing_into_library(library, healing)

    assert merged["elements"][0]["healing_issue"] == "covered_by_overlay"
    assert "Dismiss" in merged["elements"][0]["healing_suggestion"]
    assert "self_healing" in merged["elements"][0]
    assert "healing_issue" not in merged["elements"][1]


def test_merge_healing_files_writes_output(tmp_path):
    library_path = tmp_path / "library.json"
    feedback_path = tmp_path / "feedback.json"
    output_path = tmp_path / "healed-library.json"
    library_path.write_text(
        json.dumps({"elements": [{"element_id": "users.create_button", "name": "create_button"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    feedback_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "key": "users.create_button",
                        "element_id": "users.create_button",
                        "success": False,
                        "action": "click",
                        "selector": "button.add",
                        "error": "subtree intercepts pointer events",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    written = element_self_healing.merge_healing_files(
        library_path=library_path,
        feedback_path=feedback_path,
        output_path=output_path,
    )

    parsed = json.loads(written.read_text(encoding="utf-8"))
    assert parsed["elements"][0]["healing_issue"] == "covered_by_overlay"


def test_format_healing_hint_from_flat_or_nested_fields():
    assert "target_not_visible" in element_self_healing.format_healing_hint(
        {"healing_issue": "target_not_visible", "healing_suggestion": "Scroll first."}
    )
    assert "timeout" in element_self_healing.format_healing_hint(
        {"self_healing": {"primary_issue": "timeout", "suggestion": "Wait first."}}
    )
    assert element_self_healing.format_healing_hint({}) == ""
