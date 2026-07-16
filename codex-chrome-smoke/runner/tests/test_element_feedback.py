import json

from runner import element_feedback


def test_load_feedback_returns_empty_for_missing_file(tmp_path):
    payload = element_feedback.load_feedback(tmp_path / "missing.json")

    assert payload == {"version": "1.0", "updated_at": "", "records": [], "stats": {}}


def test_record_element_feedback_writes_record_and_stats(tmp_path):
    feedback_path = tmp_path / "feedback.json"

    first = element_feedback.record_element_feedback(
        element_id="users.create_button",
        page_id="users",
        state="default",
        action="click",
        selector="button.add",
        success=True,
        duration_ms=120,
        url="http://localhost/#/users",
        path=feedback_path,
    )
    second = element_feedback.record_element_feedback(
        element_id="users.create_button",
        page_id="users",
        state="default",
        action="click",
        selector="button.add",
        success=False,
        duration_ms=200,
        url="http://localhost/#/users",
        error="element is not visible",
        path=feedback_path,
    )

    assert feedback_path.exists()
    assert len(first["records"]) == 1
    assert len(second["records"]) == 2
    stat = second["stats"]["stable:users|click|button.add"]
    assert stat["total"] == 2
    assert stat["success"] == 1
    assert stat["failed"] == 1
    assert stat["success_rate"] == 0.5
    assert stat["last_success_selector"] == "button.add"
    assert stat["last_error"] == "element is not visible"


def test_feedback_without_element_id_gets_stable_key():
    record = element_feedback.normalize_feedback_record(
        page_id="users",
        state="dialog:create",
        action="fill",
        selector="input.account",
        success=True,
        url="http://localhost/#/users",
    )

    assert record["element_id"] == ""
    assert record["key"] == "stable:users|fill|input.account"
    assert record["stable_key"] == record["key"]


def test_build_feedback_stats_uses_stable_key_when_needed():
    stats = element_feedback.build_feedback_stats(
        [
            {
                "page_id": "users",
                "state": "default",
                "action": "click",
                "selector": "button.add",
                "success": True,
                "created_at": "2026-07-09T00:00:00Z",
            }
        ]
    )

    key = "stable:users|click|button.add"
    assert stats[key]["total"] == 1
    assert stats[key]["success_rate"] == 1.0


def test_merge_feedback_into_library_adds_stats_to_matching_elements():
    library = {
        "version": "1.0",
        "elements": [
            {"element_id": "users.create_button", "page_id": "users", "name": "create_button", "selectors": ["button.add"], "actions": ["click"]},
            {"element_id": "users.delete_button", "page_id": "users", "name": "delete_button", "selectors": ["button.delete"], "actions": ["click"]},
        ],
    }
    feedback = {
        "stats": {
            "stable:users|click|button.add": {
                "total": 3,
                "success": 2,
                "failed": 1,
                "success_rate": 0.6667,
                "last_success_selector": "button.add",
                "last_error": "timeout",
                "last_action": "click",
                "last_seen_at": "2026-07-09T00:00:00Z",
            }
        }
    }

    merged = element_feedback.merge_feedback_into_library(library, feedback)

    create_button = merged["elements"][0]
    delete_button = merged["elements"][1]
    assert create_button["execution_count"] == 3
    assert create_button["success_count"] == 2
    assert create_button["failed_count"] == 1
    assert create_button["success_rate"] == 0.6667
    assert create_button["last_success_selector"] == "button.add"
    assert create_button["last_error"] == "timeout"
    assert "execution_count" not in delete_button


def test_merge_feedback_matches_changed_element_id_by_page_selector_and_action():
    library = {
        "elements": [
            {"element_id": "users.create_button_2", "page_id": "users", "selectors": ["button.add"], "actions": ["click"]},
        ]
    }
    feedback = {
        "records": [
            {"element_id": "users.create_button", "page_id": "users", "state": "default", "action": "click", "selector": "button.add", "success": False, "error": "timeout", "created_at": "2026-07-13T00:00:00Z"},
        ]
    }

    merged = element_feedback.merge_feedback_into_library(library, feedback)

    assert merged["elements"][0]["execution_count"] == 1
    assert merged["elements"][0]["failed_count"] == 1


def test_merge_feedback_files_can_write_to_output_path(tmp_path):
    library_path = tmp_path / "library.json"
    feedback_path = tmp_path / "feedback.json"
    output_path = tmp_path / "merged.json"
    library_path.write_text(
        json.dumps({"version": "1.0", "elements": [{"element_id": "users.create_button"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    feedback_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "records": [],
                "stats": {"users.create_button": {"total": 1, "success": 1, "failed": 0, "success_rate": 1.0}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    written = element_feedback.merge_feedback_files(
        library_path=library_path,
        feedback_path=feedback_path,
        output_path=output_path,
    )

    parsed = json.loads(written.read_text(encoding="utf-8"))
    assert parsed["elements"][0]["execution_count"] == 1
