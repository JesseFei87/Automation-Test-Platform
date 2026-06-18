import ast

from runner.agent_codegen import generate_candidate_flow


def test_generate_candidate_flow_uses_existing_helpers():
    trace = {
        "case_id": "TC-ICM-999",
        "history": [
            {"decision": {"action": "goto", "url": "https://icm.example.test/#/index"}},
            {
                "decision": {"action": "fill", "ref": "e1", "value": "admin"},
                "execution": {"selector": 'input[name="username"]'},
            },
            {
                "decision": {"action": "click", "ref": "e2"},
                "execution": {"selector": 'button[type="submit"]'},
            },
            {"decision": {"action": "assert_text", "value": "Home"}},
        ],
    }

    code = generate_candidate_flow(trace)

    assert "from runner.browser import click_first, ensure_text_visible, fill_first, goto_route" in code
    assert "async def run(page, system, case) -> None" in code
    assert 'page.goto(\'https://icm.example.test/#/index\', wait_until=\'domcontentloaded\')' in code
    assert 'fill_first(page, [\'input[name="username"]\'], \'admin\')' in code
    assert 'click_first(page, [\'button[type="submit"]\'])' in code
    assert "ensure_text_visible(page, 'Home')" in code
    ast.parse(code)


def test_generate_candidate_flow_raises_when_trace_has_no_executable_actions():
    code = generate_candidate_flow({"history": [{"decision": {"action": "finish"}}]})

    assert "raise RuntimeError('Agent trace did not contain executable actions')" in code
    ast.parse(code)


def test_generate_candidate_flow_keeps_press_wait_and_scroll_steps():
    trace = {
        "history": [
            {
                "decision": {"action": "press", "ref": "e1", "key": "Enter"},
                "execution": {"selector": 'input[name="q"]', "key": "Enter"},
            },
            {"decision": {"action": "wait"}},
            {"decision": {"action": "scroll", "value": "900"}},
        ],
    }

    code = generate_candidate_flow(trace)

    assert 'page.locator(\'input[name="q"]\').first.press(\'Enter\')' in code
    assert "page.wait_for_timeout(1200)" in code
    assert "page.mouse.wheel(0, 900)" in code
    ast.parse(code)
