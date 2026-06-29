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


def test_build_goal_falls_back_to_expected_field():
    case = {
        "id": "ICMDEV_BND_003",
        "title": "Boundary validation",
        "steps": ["Submit dialog"],
        "expected": ["Validation error is visible"],
    }
    goal = build_agent_goal(case)
    assert "Validation error is visible" in goal


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


def test_build_self_heal_goal_includes_diagnosis_recovery_and_stop_sections():
    case = {
        "id": "ICMDEV_EXC_008",
        "title": "port 65536 triggers validation",
        "steps": ["open dialog", "fill port", "submit"],
        "expected_results": ["red hint shows"],
    }
    goal = build_self_heal_goal(
        case,
        {
            "failure_summary": "no assertion signal matched",
            "healing_hint": "look for red text under port input",
            "diagnosis": {
                "category": "locator_drift",
                "evidence": "expected_results text not found on page",
            },
            "attempt_index": 2,
            "max_attempts": 3,
        },
    )
    assert "失败诊断：" in goal
    assert "- Category: locator_drift" in goal
    assert "- 证据: expected_results text not found on page" in goal
    assert "- 重试次数: 2/3" in goal
    assert "恢复策略（按 Category 选一条）：" in goal
    assert "locator_drift（定位漂移）：重新观察页面" in goal
    assert "timing（时序问题）：等待 1-3 秒" in goal
    assert "logic_understanding（业务理解偏差）：重读用例步骤" in goal
    assert "unrecoverable（不可恢复）：不要重试" in goal
    assert "停止条件（任一命中立刻 finish）：" in goal
    assert "已是第 3 次重试。" in goal
    assert "visibleText 已包含任意一条 Expected results。" in goal
    assert "失败信号与上一轮 Category 相同。" in goal


def test_build_self_heal_goal_falls_back_to_unknown_category_when_diagnosis_missing():
    case = {
        "id": "LOGIN_FUN_003",
        "title": "login persists",
        "steps": ["login"],
        "expected_results": ["logged in"],
    }
    goal = build_self_heal_goal(case, {"failure_summary": "click failed"})
    assert "- Category: unknown" in goal
    assert "- 证据: click failed" in goal
    assert "- 重试次数: 1/3" in goal


def test_build_self_heal_goal_handles_empty_healing_context():
    case = {
        "id": "TC-ICM-001",
        "title": "smoke",
        "steps": ["open"],
        "expected_results": ["page opens"],
    }
    goal = build_self_heal_goal(case, {})
    assert "- Category: unknown" in goal
    assert "- 证据: (no diagnosis provided)" in goal
    assert "- 重试次数: 1/3" in goal
    assert "停止条件" in goal
