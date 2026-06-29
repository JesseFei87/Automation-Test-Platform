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


def test_generate_candidate_flow_uses_full_device_create_template_when_case_matches():
    trace = {
        "history": [{"decision": {"action": "goto", "url": "#/hubble/device"}}],
        "stage_runs": [
            {"name": "登录系统", "status": "completed"},
            {"name": "进入目标业务页", "status": "completed"},
            {"name": "弹窗表单处理", "status": "completed"},
            {"name": "结果校验", "status": "completed"},
        ],
        "goal": "使用admin/Hubble_Service!1088 登录",
    }
    case = {
        "id": "ICMDEV_FUN_001",
        "module": "ICM-设备信息",
        "title": "填写全部合法字段新增设备信息成功",
        "steps": ["登录系统", "进入设备信息", "点击新增", "填写表单", "点击确定"],
        "precondition": "已使用 admin/Hubble_Service!1088 登录系统",
        "test_data": "连接类型=连接器-1；设备类型=标准设备；设备名称=TestDev_01；设备IP=192.168.1.100；设备端口=22；VNC密码=Vnc@1234；是否允许控制=是；设备状态=在线；备注=自动化测试新增",
    }

    code = generate_candidate_flow(trace, case)

    assert "ensure_fresh_login" in code
    assert "goto_route(page, system, '#/hubble/device')" in code
    assert "page.get_by_role('button', name='新增').first.click(force=True)" in code
    assert "await _choose_dropdown(page, inputs.nth(0), '连接器-1')" in code
    assert "await inputs.nth(2).fill('TestDev_01')" in code
    assert "await click_dialog_primary(page)" in code
    assert "await ensure_text_visible(page, 'TestDev_01')" in code
    ast.parse(code)


def test_generate_candidate_flow_uses_saved_device_name_for_truncated_input():
    trace = {"history": [], "goal": "使用admin/Hubble_Service!1088 登录"}
    case = {
        "id": "ICMDEV_BND_003",
        "module": "ICM-设备信息",
        "title": "设备名称输入16个字符触发自动截断",
        "steps": ["打开添加设备信息弹窗", "填写设备名称", "点击确定"],
        "test_data": "设备名称=BCDEFGHIJKLMNOPQ；设备IP=192.168.1.100；设备端口=22",
    }

    code = generate_candidate_flow(trace, case)

    assert "await inputs.nth(2).fill('BCDEFGHIJKLMNOPQ')" in code
    assert "search_by_keyword" in code
    assert "'BCDEFGHIJKLMNOP'" in code
    assert "ensure_text_visible(page, 'BCDEFGHIJKLMNOP')" in code
    ast.parse(code)
