from runner.agent_actions import AgentDecision, normalize_decision, validate_decision


def test_normalize_rejects_unknown_action():
    decision = normalize_decision({"action": "delete", "reason": "bad"})
    assert decision.action == "fail"
    assert "unsupported" in decision.reason


def test_click_requires_observed_ref():
    decision = AgentDecision(action="click", ref="e99", reason="click missing")
    errors = validate_decision(decision, observed_refs={"e1", "e2"}, allowed_hosts={"127.0.0.1"})
    assert "unknown ref" in errors[0]


def test_fill_requires_observed_ref_and_press_can_use_global_key():
    fill = AgentDecision(action="fill", ref="missing", value="admin")
    press = AgentDecision(action="press", ref="", key="F5")

    assert "unknown ref" in validate_decision(fill, observed_refs={"e1"}, allowed_hosts={"127.0.0.1"})[0]
    assert validate_decision(press, observed_refs={"e1"}, allowed_hosts={"127.0.0.1"}) == []


def test_goto_rejects_host_outside_whitelist():
    decision = AgentDecision(action="goto", url="https://example.com", reason="external")
    errors = validate_decision(decision, observed_refs=set(), allowed_hosts={"127.0.0.1"})
    assert "host not allowed" in errors[0]


def test_hover_is_supported_and_requires_observed_ref():
    decision = normalize_decision({"action": "hover", "ref": "e7", "reason": "reveal menu"})

    assert decision.action == "hover"
    assert validate_decision(decision, observed_refs={"e7"}, allowed_hosts=set()) == []
    assert "unknown ref" in validate_decision(decision, observed_refs={"e1"}, allowed_hosts=set())[0]
