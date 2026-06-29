import asyncio

from runner.agent_explore import _agent_decision_payload, extract_json_object, run_agent_loop


def test_agent_loop_stops_on_finish():
    async def scenario():
        calls = []

        async def observe():
            return {"url": "http://127.0.0.1", "title": "", "visibleText": ["Done"], "interactives": []}

        async def decide(goal, observation, history, step_index, max_steps):
            calls.append(step_index)
            return {"action": "finish", "reason": "done"}

        async def execute(decision, observation):
            return {"result": "not-called"}

        result = await run_agent_loop(
            goal="finish when done",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"127.0.0.1"},
            max_steps=3,
        )
        assert result["ok"] is True
        assert result["history"][0]["decision"]["action"] == "finish"
        assert calls == [0]

    asyncio.run(scenario())


def test_agent_loop_stops_on_execution_error():
    async def scenario():
        async def observe():
            return {
                "url": "http://127.0.0.1",
                "title": "",
                "visibleText": [],
                "interactives": [{"ref": "e1", "selector": "#go"}],
            }

        async def decide(goal, observation, history, step_index, max_steps):
            return {"action": "click", "ref": "e1", "reason": "click"}

        async def execute(decision, observation):
            return {"result": "error", "error": "click failed"}

        result = await run_agent_loop(
            goal="click once",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"127.0.0.1"},
            max_steps=3,
        )
        assert result["ok"] is False
        assert result["error"] == "click failed"
        assert len(result["history"]) == 1

    asyncio.run(scenario())


def test_agent_loop_does_not_execute_same_action_twice_when_page_is_unchanged():
    async def scenario():
        executed_refs = []

        async def observe():
            return {
                "url": "https://example.test/#/index",
                "title": "ICM",
                "visibleText": ["首页"],
                "interactives": [
                    {"ref": "e1", "selector": "#home", "text": "首页"},
                    {"ref": "e2", "selector": "#device", "text": "设备信息"},
                ],
            }

        async def decide(goal, observation, history, step_index, max_steps):
            if step_index < 2:
                return {"action": "click", "ref": "e1", "reason": "open menu"}
            if step_index == 2:
                assert history[-1]["execution"]["result"] == "duplicate_action_blocked"
                return {"action": "click", "ref": "e2", "reason": "try device menu"}
            return {"action": "finish", "reason": "device page opened"}

        async def execute(decision, observation):
            executed_refs.append(decision.ref)
            return {"result": "clicked", "ref": decision.ref}

        result = await run_agent_loop(
            goal="open device page",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"example.test"},
            max_steps=4,
        )

        assert result["ok"] is True
        assert executed_refs == ["e1", "e2"]

    asyncio.run(scenario())


def test_agent_loop_finishes_when_success_signal_exists_before_empty_ref_error():
    async def scenario():
        responses = [
            {
                "url": "https://example.test/login",
                "title": "",
                "visibleText": ["登录"],
                "interactives": [{"ref": "e1", "selector": "#user"}],
            },
            {
                "url": "https://example.test/#/icm",
                "title": "",
                "visibleText": ["test", "屏幕墙"],
                "interactives": [{"ref": "e1", "selector": "#profile", "text": "test"}],
            },
        ]
        calls = {"count": 0}

        async def observe():
            index = min(calls["count"], len(responses) - 1)
            return responses[index]

        async def decide(goal, observation, history, step_index, max_steps):
            calls["count"] += 1
            if step_index == 0:
                return {"action": "wait", "reason": "login settles"}
            return {"action": "click", "ref": "", "reason": "extra tail action"}

        async def execute(decision, observation):
            return {"result": "waited"}

        result = await run_agent_loop(
            goal="Case ID: LOGIN_FUN_003\nPrecondition: 已通过 test/123456 成功登录\nTest data: username=test, password=123456",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"example.test"},
            max_steps=3,
        )
        assert result["ok"] is True
        assert result["history"][-1]["decision"]["action"] == "finish"

    asyncio.run(scenario())


def test_extract_json_object_rejects_unterminated_string():
    try:
        extract_json_object('{"action":"click","reason":"broken')
    except ValueError as exc:
        assert "Unterminated string" in str(exc)
    else:
        raise AssertionError("unterminated JSON should be rejected")


def test_extract_json_object_strips_think_and_fence():
    parsed = extract_json_object('<think>plan</think>\n```json\n{"action":"wait","reason":"settle"}\n```')
    assert parsed == {"action": "wait", "reason": "settle"}


def test_agent_decision_payload_uses_minimax_completion_tokens():
    payload = _agent_decision_payload("MiniMax-M3", "minimax-m3", "do it")
    assert payload["stream"] is False
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_completion_tokens"] == 1200
    assert "max_tokens" not in payload


def test_agent_loop_preserves_history_when_decision_raises():
    async def scenario():
        calls = {"count": 0}

        async def observe():
            return {
                "url": "http://127.0.0.1",
                "title": "",
                "visibleText": ["Ready"],
                "interactives": [{"ref": "e1", "selector": "#go"}],
            }

        async def decide(goal, observation, history, step_index, max_steps):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"action": "wait", "reason": "settle"}
            raise ValueError("AI response JSON parse failed: empty content after cleanup")

        async def execute(decision, observation):
            return {"result": "waited"}

        result = await run_agent_loop(
            goal="click once",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"127.0.0.1"},
            max_steps=3,
        )
        assert result["ok"] is False
        assert len(result["history"]) == 2
        assert result["history"][0]["decision"]["action"] == "wait"
        assert result["history"][1]["decision"]["action"] == "fail"

    asyncio.run(scenario())


def test_agent_loop_continues_when_login_precondition_already_satisfied():
    async def scenario():
        calls = {"count": 0}

        async def observe():
            return {
                "url": "https://example.test/#/index",
                "title": "ICM",
                "visibleText": ["首页"],
                "interactives": [{"ref": "e1", "selector": "#menu", "text": "设备信息"}],
            }

        async def decide(goal, observation, history, step_index, max_steps):
            calls["count"] += 1
            if calls["count"] == 1:
                return {
                    "action": "fail",
                    "reason": "Already on home page (index). The login form is not visible because of pre-existing session.",
                }
            return {"action": "finish", "reason": "continued after login precondition"}

        async def execute(decision, observation):
            return {"result": "not-called"}

        result = await run_agent_loop(
            goal="Case ID: ICMDEV_FUN_001\nSteps:\n- 1. login\n- 2. open device page",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"example.test"},
            max_steps=3,
        )
        assert result["ok"] is True
        assert result["history"][0]["execution"]["result"] == "login_precondition_satisfied"
        assert result["history"][1]["decision"]["action"] == "finish"

    asyncio.run(scenario())


def test_agent_loop_ignores_finish_when_only_login_is_satisfied():
    async def scenario():
        calls = {"count": 0}

        async def observe():
            return {
                "url": "https://example.test/#/index",
                "title": "ICM",
                "visibleText": ["首页"],
                "interactives": [{"ref": "e1", "selector": "#menu", "text": "设备信息"}],
            }

        async def decide(goal, observation, history, step_index, max_steps):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"action": "finish", "reason": "Login already completed on home page"}
            return {"action": "finish", "reason": "business steps complete"}

        async def execute(decision, observation):
            return {"result": "not-called"}

        result = await run_agent_loop(
            goal="Case ID: ICMDEV_FUN_001\nSteps:\n- 1. login\n- 2. open device page\n- 3. click add",
            observe=observe,
            decide=decide,
            execute=execute,
            allowed_hosts={"example.test"},
            max_steps=3,
        )
        assert result["ok"] is True
        assert result["history"][0]["execution"]["result"] == "login_precondition_satisfied"
        assert result["history"][1]["decision"]["reason"] == "business steps complete"

    asyncio.run(scenario())
