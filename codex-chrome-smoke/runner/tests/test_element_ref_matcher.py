import json

from runner import element_knowledge
from runner.element_ref_matcher import bind_candidate_refs, build_agent_ref_evidence, format_agent_ref_guidance, format_bound_candidate_elements, match_element_to_interactive, resolve_recovery_ref


def write_library(path, elements):
    path.write_text(json.dumps({"version": "test", "elements": elements}, ensure_ascii=False), encoding="utf-8")


def test_match_element_to_interactive_prefers_exact_selector_and_text():
    element = {
        "name": "user_create_button",
        "human_zh": ["新增用户按钮"],
        "selectors": ["button.add"],
        "tag": "button",
        "text": "新增用户",
    }
    interactive = {"ref": "e3", "selector": "button.add", "tag": "button", "text": "新增用户"}

    assert match_element_to_interactive(element, interactive) >= 40


def test_match_element_to_interactive_prefers_high_stability_testid_over_dynamic_css():
    element = {
        "locator_variants": [
            {"kind": "testid", "value": "create-user", "stability": "high"},
            {"kind": "css", "value": "tbody > tr:nth-of-type(1) > button", "stability": "low"},
        ],
        "tag": "button",
    }

    stable = {"ref": "e1", "testId": "create-user", "selector": "button:nth-of-type(4)", "tag": "button"}
    dynamic = {"ref": "e2", "selector": "tbody > tr:nth-of-type(1) > button", "tag": "button"}

    assert match_element_to_interactive(element, stable) > match_element_to_interactive(element, dynamic)


def test_match_element_to_interactive_uses_legacy_selectors_when_variants_are_absent():
    element = {"selectors": ["button.add"], "tag": "button", "text": "Add"}
    interactive = {"ref": "e3", "selector": "button.add", "tag": "button", "text": "Add"}

    assert match_element_to_interactive(element, interactive) >= 20


def test_bind_candidate_refs_attaches_best_current_ref():
    candidates = [
        {
            "name": "user_create_button",
            "human_zh": ["新增用户按钮"],
            "selectors": ["button.add"],
            "tag": "button",
            "text": "新增用户",
        }
    ]
    observation = {
        "interactives": [
            {"ref": "e1", "selector": "button.cancel", "tag": "button", "text": "取消"},
            {"ref": "e3", "selector": "button.add", "tag": "button", "text": "新增用户"},
        ]
    }

    bound = bind_candidate_refs(candidates, observation)

    assert bound[0]["matched_ref"] == "e3"
    assert bound[0]["matched_ref_selector"] == "button.add"
    assert bound[0]["matched_ref_score"] >= 40


def test_bind_candidate_refs_omits_low_confidence_matches():
    candidates = [{"name": "user_create_button", "human_zh": ["新增用户按钮"], "selectors": ["button.add"]}]
    observation = {"interactives": [{"ref": "e1", "selector": "input.search", "tag": "input", "placeholder": "搜索"}]}

    bound = bind_candidate_refs(candidates, observation)

    assert "matched_ref" not in bound[0]


def test_agent_ref_evidence_records_match_and_adoption_without_selectors(monkeypatch):
    element = {
        "element_id": "user_create_button",
        "name": "user_create_button",
        "selectors": ["button.add"],
        "tag": "button",
        "text": "新增用户",
        "validation_status": "valid",
    }
    monkeypatch.setattr("runner.element_ref_matcher.rank_for_intent", lambda *args, **kwargs: [element])
    observation = {
        "interactives": [{"ref": "e3", "selector": "button.add", "tag": "button", "text": "新增用户"}]
    }

    evidence = build_agent_ref_evidence("新增用户", "https://example.test/#/users", observation, "e3")

    assert evidence["matched"] is True
    assert evidence["adopted"] is True
    assert evidence["adopted_element_id"] == "user_create_button"
    assert evidence["adoption_reason"] == "selected_ref_matches_candidate"
    assert evidence["candidates"][0]["recommended_ref"] == "e3"
    assert "selectors" not in evidence["candidates"][0]


def test_resolve_recovery_ref_requires_action_compatible_enabled_ref(monkeypatch):
    element = {"name": "account_input", "selectors": ["input.account"], "tag": "input", "placeholder": "账号"}
    monkeypatch.setattr("runner.element_ref_matcher.rank_for_intent", lambda *args, **kwargs: [element])
    observation = {
        "interactives": [
            {"ref": "e1", "selector": "button.account", "tag": "button", "text": "账号"},
            {"ref": "e2", "selector": "input.account", "tag": "input", "placeholder": "账号", "disabled": True},
            {"ref": "e3", "selector": "input.account", "tag": "input", "placeholder": "账号"},
        ]
    }

    result = resolve_recovery_ref("输入账号", "https://example.test/#/login", observation, "fill")

    assert result["status"] == "resolved"
    assert result["ref"] == "e3"


def test_resolve_recovery_ref_rejects_ambiguous_matches(monkeypatch):
    element = {"name": "create", "selectors": ["button.add"], "tag": "button", "text": "新增"}
    monkeypatch.setattr("runner.element_ref_matcher.rank_for_intent", lambda *args, **kwargs: [element])
    observation = {
        "interactives": [
            {"ref": "e1", "selector": "button.add", "tag": "button", "text": "新增"},
            {"ref": "e2", "selector": "button.add", "tag": "button", "text": "新增"},
        ]
    }

    assert resolve_recovery_ref("新增", "https://example.test/#/users", observation, "click")["status"] == "ambiguous"


def test_format_bound_candidate_elements_includes_healing_hint(tmp_path, monkeypatch):
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
                "tag": "button",
                "text": "新增用户",
                "coverage": 1,
                "healing_issue": "target_not_visible",
                "healing_suggestion": "Scroll the element into view before retrying.",
            }
        ],
    )
    monkeypatch.setenv("ELEMENT_LIBRARY_PATH", str(library_path))
    element_knowledge.clear_library_cache()
    observation = {
        "url": "https://example.test/#/system/user",
        "interactives": [{"ref": "e3", "selector": "button.add", "tag": "button", "text": "新增用户"}],
    }

    snippet = format_bound_candidate_elements("创建用户", "https://example.test/#/system/user", observation)

    assert "healing: target_not_visible" in snippet
    assert "Scroll the element into view" in snippet


def test_format_bound_candidate_elements_includes_recommended_ref(tmp_path, monkeypatch):
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
                "tag": "button",
                "text": "新增用户",
                "coverage": 1,
                "execution_count": 4,
                "success_rate": 1.0,
            }
        ],
    )
    monkeypatch.setenv("ELEMENT_LIBRARY_PATH", str(library_path))
    element_knowledge.clear_library_cache()
    observation = {
        "url": "https://example.test/#/system/user",
        "interactives": [{"ref": "e3", "selector": "button.add", "tag": "button", "text": "新增用户"}],
    }

    snippet = format_bound_candidate_elements("创建用户", "https://example.test/#/system/user", observation)

    assert "recommended current ref: `e3`" in snippet
    assert "Use recommended refs only if they appear in current observation.interactives" in snippet
    assert "feedback: runs: 4, success: 1.0" in snippet

    guidance = format_agent_ref_guidance("创建用户", "https://example.test/#/system/user", observation)
    assert "recommended current ref: `e3`" in guidance
    assert "button.add" not in guidance
