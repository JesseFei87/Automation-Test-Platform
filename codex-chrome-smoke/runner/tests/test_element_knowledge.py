import json

from runner import element_knowledge


def write_library(path, elements):
    path.write_text(json.dumps({"version": "test", "elements": elements}, ensure_ascii=False), encoding="utf-8")


def test_format_candidate_elements_returns_empty_for_missing_library(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEMENT_LIBRARY_PATH", str(tmp_path / "missing.json"))
    element_knowledge.clear_library_cache()

    assert element_knowledge.format_candidate_elements("新增用户", "#/system/user") == ""


def test_chinese_business_alias_matches_user_create_button(tmp_path, monkeypatch):
    library_path = tmp_path / "library.json"
    write_library(
        library_path,
        [
            {
                "name": "user_create_button",
                "human_en": "user create button",
                "human_zh": ["新增用户按钮"],
                "context_keys": ["user", "list_page"],
                "selectors": ["button:has-text(新增用户)"],
                "coverage": 1,
            }
        ],
    )
    monkeypatch.setenv("ELEMENT_LIBRARY_PATH", str(library_path))
    element_knowledge.clear_library_cache()

    snippet = element_knowledge.format_candidate_elements("创建账号", "#/system/user")

    assert "user_create_button" in snippet
    assert "新增用户按钮" in snippet


def test_username_alias_matches_input(tmp_path, monkeypatch):
    library_path = tmp_path / "library.json"
    write_library(
        library_path,
        [
            {
                "name": "username_input",
                "human_en": "username input",
                "human_zh": ["账号输入框"],
                "context_keys": ["login"],
                "selectors": ["input[placeholder='账号']"],
                "coverage": 1,
            }
        ],
    )
    monkeypatch.setenv("ELEMENT_LIBRARY_PATH", str(library_path))
    element_knowledge.clear_library_cache()

    assert "username_input" in element_knowledge.format_candidate_elements("输入用户名", "#/login")


def test_format_candidate_elements_includes_feedback_stats(tmp_path, monkeypatch):
    library_path = tmp_path / "library.json"
    write_library(
        library_path,
        [
            {
                "name": "user_create_button",
                "human_en": "user create button",
                "human_zh": ["新增用户按钮"],
                "context_keys": ["user", "list_page"],
                "selectors": ["button.add"],
                "coverage": 1,
                "execution_count": 5,
                "success_rate": 0.8,
                "last_error": "timeout",
            }
        ],
    )
    monkeypatch.setenv("ELEMENT_LIBRARY_PATH", str(library_path))
    element_knowledge.clear_library_cache()

    snippet = element_knowledge.format_candidate_elements("创建用户", "#/system/user")

    assert "feedback:" in snippet
    assert "runs: 5" in snippet
    assert "success: 0.8" in snippet
    assert "last_error: timeout" in snippet


def test_route_context_outranks_placeholder_elements(tmp_path, monkeypatch):
    library_path = tmp_path / "library.json"
    write_library(
        library_path,
        [
            {
                "name": "agent_candidate",
                "human_en": "agent candidate",
                "human_zh": [],
                "context_keys": [],
                "selectors": ["candidate_flow.py"],
                "coverage": 99,
            },
            {
                "name": "user_list_url",
                "human_en": "user list url",
                "human_zh": ["用户列表页面"],
                "context_keys": ["route", "list_page"],
                "selectors": ["#/system/user"],
                "coverage": 1,
            },
        ],
    )
    monkeypatch.setenv("ELEMENT_LIBRARY_PATH", str(library_path))
    element_knowledge.clear_library_cache()

    rows = element_knowledge.rank_for_intent("搜索用户", "#/system/user", top_k=2)

    assert [row["name"] for row in rows] == ["user_list_url"]


def test_validation_report_filters_invalid_elements(tmp_path, monkeypatch):
    library_path = tmp_path / "library.json"
    validation_path = tmp_path / "validation-report.json"
    valid_element = {
        "page_id": "user_management",
        "element_id": "user_management.add_button",
        "name": "add_button",
        "human_en": "add user button",
        "human_zh": ["add user"],
        "context_keys": ["user"],
        "selectors": ["button.add"],
        "coverage": 1,
    }
    invalid_element = {
        "page_id": "user_management",
        "element_id": "user_management.old_add_button",
        "name": "old_add_button",
        "human_en": "old add user button",
        "human_zh": ["old add user"],
        "context_keys": ["user"],
        "selectors": ["button.old-add"],
        "coverage": 50,
    }
    write_library(library_path, [invalid_element, valid_element])
    validation_path.write_text(
        json.dumps(
            {
                "records": [
                    {**invalid_element, "status": "invalid"},
                    {**valid_element, "status": "valid"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ELEMENT_LIBRARY_PATH", str(library_path))
    monkeypatch.setenv("ICM_ELEMENT_VALIDATION_REPORT_PATH", str(validation_path))
    element_knowledge.clear_library_cache()

    rows = element_knowledge.rank_for_intent("add user", "#/system/user", top_k=5)
    snippet = element_knowledge.format_candidate_elements("add user", "#/system/user")

    assert [row["name"] for row in rows] == ["add_button"]
    assert "old_add_button" not in snippet
    assert "validation: valid" in snippet


def test_needs_review_is_excluded_by_default_and_optional(tmp_path, monkeypatch):
    library_path = tmp_path / "library.json"
    validation_path = tmp_path / "validation-report.json"
    needs_review_element = {
        "page_id": "user_management",
        "element_id": "user_management.maybe_add_button",
        "name": "maybe_add_button",
        "human_en": "maybe add user button",
        "human_zh": ["maybe add user"],
        "context_keys": ["user"],
        "selectors": ["button.maybe-add"],
        "coverage": 1,
    }
    write_library(library_path, [needs_review_element])
    validation_path.write_text(
        json.dumps({"records": [{**needs_review_element, "status": "needs_review"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("ELEMENT_LIBRARY_PATH", str(library_path))
    monkeypatch.setenv("ICM_ELEMENT_VALIDATION_REPORT_PATH", str(validation_path))
    element_knowledge.clear_library_cache()

    assert element_knowledge.rank_for_intent("add user", "#/system/user") == []
    rows = element_knowledge.rank_for_intent("add user", "#/system/user", include_needs_review=True)

    assert [row["name"] for row in rows] == ["maybe_add_button"]
