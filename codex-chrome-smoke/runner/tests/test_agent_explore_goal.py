from runner.agent_explore import allowed_hosts_for_system, build_agent_goal, build_agent_prompt, build_self_heal_goal


def test_allowed_hosts_from_system_urls():
    system = {"base_url": "https://icm.example.test/app", "entry_url": "https://icm.example.test/#/login"}
    assert allowed_hosts_for_system(system) == {"icm.example.test"}


def test_build_goal_includes_case_steps_and_expected_results():
    case = {
        "id": "TC-ICM-999",
        "title": "Open device list",
        "steps": ["Open homepage", "Open device list"],
        "expected_results": ["Device list is visible"],
    }
    goal = build_agent_goal(case)
    assert "TC-ICM-999" in goal
    assert "Open device list" in goal
    assert "Device list is visible" in goal


def test_build_goal_includes_precondition_and_test_data():
    case = {
        "id": "LOGIN_FUN_003",
        "title": "Login persists after refresh",
        "precondition": "Login with username=test and password=123456",
        "test_data": "username=test, password=123456",
        "steps": ["Submit login form", "Refresh page"],
        "expected_results": ["Still logged in as test"],
    }
    goal = build_agent_goal(case)
    assert "Precondition: Login with username=test and password=123456" in goal
    assert "Test data: username=test, password=123456" in goal
    assert "Still logged in as test" in goal


def test_agent_prompt_forbids_default_admin_fallback_when_case_data_exists():
    case = {
        "id": "LOGIN_FUN_003",
        "title": "Login persists after refresh",
        "precondition": "Login with username=test and password=123456",
        "test_data": "username=test, password=123456",
        "steps": ["Submit login form"],
        "expected_results": ["Still logged in as test"],
    }
    prompt = build_agent_prompt(build_agent_goal(case), {"interactives": []}, [], 0, 12)
    assert "Use credentials and other input values from the case goal exactly when they are provided." in prompt
    assert "Do not substitute default admin/test accounts unless the case goal explicitly says so." in prompt
    assert '"value":"test"' in prompt
    assert '"value":"admin"' not in prompt


def test_build_self_heal_goal_includes_failure_hint_and_tail_history():
    case = {
        "id": "LOGIN_FUN_003",
        "title": "Login persists after refresh",
        "test_data": "username=test, password=123456",
        "steps": ["Submit login form", "Refresh page"],
        "expected_results": ["Still logged in as test"],
    }
    goal = build_self_heal_goal(
        case,
        {
            "failure_summary": "unknown ref: empty",
            "healing_hint": "Finish as soon as login success signal is visible.",
            "last_history": [
                {
                    "step": 5,
                    "decision": {"action": "press", "ref": "", "reason": "refresh page"},
                    "execution": {"error": "unknown ref: empty"},
                }
            ],
        },
    )
    assert "username=test, password=123456" in goal
    assert "Previous failure: unknown ref: empty" in goal
    assert "Healing hint: Finish as soon as login success signal is visible." in goal
    assert "Recent failing tail:" in goal
    assert "action=press" in goal
