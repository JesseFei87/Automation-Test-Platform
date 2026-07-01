from runner.agent_stage_router import _is_icm_device_create_case, parse_case_test_data, plan_agent_execution, saved_device_name_value


def test_parse_case_test_data_supports_semicolon_pairs():
    data = parse_case_test_data(
        {
            "test_data": "连接类型=连接器-1；设备类型=标准设备；设备名称=TestDev_01；设备IP=192.168.1.100；设备端口=22"
        }
    )
    assert data["连接类型"] == "连接器-1"
    assert data["设备名称"] == "TestDev_01"


def test_parse_case_test_data_expands_repeated_character_values():
    data_500 = parse_case_test_data({"test_data": "remark=500\u4e2a\u5b57\u7b26'a'"})
    data_501 = parse_case_test_data({"test_data": "remark=501\u4e2a\u5b57\u7b26'a'"})

    assert data_500["remark"] == "a" * 500
    assert data_501["remark"] == "a" * 501


def test_parse_case_test_data_expands_referenced_case(monkeypatch):
    monkeypatch.setattr(
        "runner.browser.load_case",
        lambda case_id: {
            "id": case_id,
            "test_data": "连接类型=连接器-1；设备类型=标准设备；设备IP=192.168.1.100；设备端口=22",
        },
    )
    data = parse_case_test_data(
        {
            "id": "ICMDEV_BND_002",
            "test_data": "设备名称=ABCDEFGHIJKLMNO；其他字段同FUN_001",
        }
    )
    assert data["设备名称"] == "ABCDEFGHIJKLMNO"
    assert data["连接类型"] == "连接器-1"
    assert data["设备IP"] == "192.168.1.100"


def test_saved_device_name_value_matches_icm_maxlength():
    assert saved_device_name_value({"设备名称": "BCDEFGHIJKLMNOPQ"}) == "BCDEFGHIJKLMNOP"
    assert saved_device_name_value({"device_name": "ABCDEFGHIJKLMNO"}) == "ABCDEFGHIJKLMNO"


def test_plan_agent_execution_splits_device_create_case_into_coarse_stages():
    plan = plan_agent_execution(
        {
            "id": "ICMDEV_FUN_001",
            "module": "ICM-设备信息",
            "steps": [
                "1. 访问登录页并使用 admin 登录",
                "2. 在左侧导航栏，点击 ICM 项目，再点击设备信息",
                "3. 点击【新增】按钮，打开添加设备信息弹窗",
                "4. 在弹窗内填写连接类型、设备类型、设备名称、设备IP、设备端口",
                "5. 点击【确定】按钮",
            ],
            "expected_results": ["新增成功并显示在设备列表中"],
        }
    )
    stages = plan["stages"]
    assert [stage["scene_type"] for stage in stages] == ["login", "navigation", "dialog_form", "assertion"]
    assert stages[1]["strategy"] == "route_open"
    assert stages[1]["target_route"] == "#/hubble/device"


def test_plan_agent_execution_adds_login_stage_for_logged_in_precondition():
    plan = plan_agent_execution(
        {
            "id": "ICMDEV_BND_003",
            "module": "ICM-设备信息",
            "precondition": "已使用 admin/Hubble_Service!1088 登录系统",
            "steps": [
                "1. 进入设备信息页面",
                "2. 点击新增按钮",
            ],
            "expected_results": ["成功打开新增弹窗"],
        }
    )
    assert plan["stages"][0]["scene_type"] == "login"
    assert plan["stages"][0]["strategy"] == "login_guard"


def test_plan_agent_execution_uses_expected_field_for_assertion_signals():
    plan = plan_agent_execution(
        {
            "id": "ICMDEV_BND_003",
            "module": "ICM-设备信息",
            "steps": ["1. 打开添加设备信息弹窗", "2. 点击确定"],
            "expected": ["弹窗不关闭", "设备名称最多15个字符"],
        }
    )
    assertion_stage = plan["stages"][-1]
    assert assertion_stage["scene_type"] == "assertion"
    assert "弹窗不关闭" in assertion_stage["success_signals"]


def test_plan_agent_execution_maps_input_step_to_dialog_stage():
    plan = plan_agent_execution(
        {
            "id": "ICMDEV_BND_003",
            "module": "ICM-设备信息",
            "steps": [
                "1. 打开添加设备信息弹窗",
                "2. 在设备名称输入框输入16个字符BCDEFGHIJKLMNOPQ",
                "3. 填写其他必填合法字段",
                "4. 点击【确定】",
            ],
            "expected": ["输入框仅接受前15个字符"],
        }
    )
    dialog_stage = next(stage for stage in plan["stages"] if stage["scene_type"] == "dialog_form")
    assert dialog_stage["source_steps"] == [1, 2, 3, 4]


def test_is_icm_device_create_case_matches_device_add_dialog_case():
    assert _is_icm_device_create_case(
        {
            "module": "ICM-设备信息",
            "title": "填写全部合法字段新增设备信息成功",
            "steps": ["点击新增按钮", "打开添加设备信息弹窗"],
        }
    )


def test_plan_agent_execution_adds_assertion_stage_for_device_create_without_expected_results():
    plan = plan_agent_execution(
        {
            "id": "ICMDEV_FUN_001",
            "module": "ICM-设备信息",
            "title": "填写全部合法字段新增设备信息成功",
            "steps": [
                "1. 登录系统",
                "2. 进入设备信息",
                "3. 点击新增按钮，打开添加设备信息弹窗",
                "4. 填写全部字段",
                "5. 点击【确定】按钮",
            ],
            "expected_results": [],
        }
    )
    assert [stage["scene_type"] for stage in plan["stages"]] == ["login", "navigation", "dialog_form", "assertion"]
    assert plan["stages"][-1]["fallback"] == "fail"


def test_is_exception_case_matches_exc_id_prefix():
    from runner.agent_stage_router import _is_exception_case

    assert _is_exception_case({"id": "ICMDEV_EXC_008"})
    assert _is_exception_case({"id": "icmdev_exc_001"})
    assert _is_exception_case({"id": "TC_EXC_FOO"})
    assert _is_exception_case({"id": "X", "case_type": "exception"})
    assert _is_exception_case({"id": "X", "type": "exception"})


def test_is_exception_case_rejects_non_exc_cases():
    from runner.agent_stage_router import _is_exception_case

    assert not _is_exception_case({"id": "ICMDEV_FUN_001"})
    assert not _is_exception_case({"id": "ICMDEV_BND_003"})
    assert not _is_exception_case({"id": "ICMDEV_LOGIN_001"})
    assert not _is_exception_case({})
    assert not _is_exception_case({"id": "ICMDEV_001"})


def test_exc_case_assertion_stage_uses_expected_as_success_signal():
    from runner.agent_stage_router import plan_agent_execution

    plan = plan_agent_execution(
        {
            "id": "ICMDEV_EXC_008",
            "module": "ICM-Test",
            "steps": [
                "1. enter device page",
                "2. click add",
                "3. fill invalid port",
                "4. submit",
            ],
            "expected_results": ["please enter correct port number"],
        }
    )
    assertion_stage = plan["stages"][-1]
    assert assertion_stage["scene_type"] == "assertion"
    assert "please enter correct port number" in assertion_stage["success_signals"]


def test_exc_case_assertion_stage_uses_quoted_substring_in_numbered_expected():
    from runner.agent_stage_router import plan_agent_execution

    plan = plan_agent_execution(
        {
            "id": "ICMDEV_EXC_008",
            "module": "ICM-Test",
            "steps": [
                "1. open dialog",
                "2. fill port",
                "3. submit",
            ],
            "expected": [
                "1. dialog opens",
                "2. red hint shows " + chr(34) + "please enter correct port number" + chr(34),
                "3. no other errors",
                "4. dialog stays open",
            ],
        }
    )
    assertion_stage = plan["stages"][-1]
    assert assertion_stage["scene_type"] == "assertion"
    quoted = "please enter correct port number"
    assert quoted in assertion_stage["success_signals"][1]


def test_multi_session_user_management_plan_preserves_business_step_order():
    plan = plan_agent_execution(
        {
            "id": "USRMGT_FUN_001",
            "module": "用户管理/设备配置",
            "steps": [
                "1. 打开ICM登录页，输入admin/Hubble_Service!1088登录",
                "2. 进入系统管理-用户管理页面",
                "3. 鼠标悬停在更多，点击配置服务器和设备",
                "4. 在绑定设备信息区域中依次勾选AU5800、AU5800(2)、DxI(1)、DxI(2)",
                "5. 保存配置",
                "6. 点击右上角头像，选择退出登录",
                "7. 使用test/123456登录",
                "8. 进入屏幕墙页面查看设备列表",
            ],
            "expected": ["屏幕墙上可见绑定的4台设备"],
        }
    )

    stages = plan["stages"]
    assert [stage["source_steps"] for stage in stages[:-1]] == [[1], [2], [3, 4, 5], [6, 7], [8]]
    assert stages[1]["target_route"] == "#/system/user"
    assert stages[2]["strategy"] == "generic_explore"
    assert all(stage["strategy"] != "dialog_form_fill" for stage in stages)
