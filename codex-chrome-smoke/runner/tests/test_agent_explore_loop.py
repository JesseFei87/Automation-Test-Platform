import asyncio

from runner.agent_explore import run_agent_loop


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
