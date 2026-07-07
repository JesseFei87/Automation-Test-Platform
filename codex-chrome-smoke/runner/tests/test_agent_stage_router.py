import asyncio
import re

from runner.agent_stage_router import (
    _extract_binding_device_names,
    _is_icm_device_create_case,
    _run_account_switch,
    _run_detail_assert,
    _run_user_device_binding,
    parse_case_test_data,
    plan_agent_execution,
    saved_device_name_value,
)


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


def test_extract_binding_device_names_from_test_data():
    names = _extract_binding_device_names(
        {
            "test_data": "登录账号：admin/对应密码；test账号：test/123456；勾选设备：AU5800、AU5800(2)、DxI(1)、DxI(2)"
        }
    )
    assert names == ["AU5800", "AU5800(2)", "DxI(1)", "DxI(2)"]


def test_extract_binding_device_names_does_not_bleed_into_next_step():
    names = _extract_binding_device_names(
        {
            "test_data": "勾选设备：AU5800、AU5800(2)、DxI(1)、DxI(2)",
            "steps": [
                "1. 打开ICM登录页",
                "2. 进入用户管理",
            ],
        }
    )
    assert names == ["AU5800", "AU5800(2)", "DxI(1)", "DxI(2)"]


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
    assert [stage["source_steps"] for stage in stages] == [[1], [2], [3], [4, 5], [6, 7], [8], [8]]
    assert stages[1]["target_route"] == "#/system/user"
    assert stages[2]["strategy"] == "user_row_menu"
    assert stages[3]["strategy"] == "user_device_binding"
    assert stages[4]["strategy"] == "account_switch"
    assert stages[5]["strategy"] == "route_open"
    assert stages[5]["target_route"] == "#/icm"
    assert all(stage["strategy"] != "dialog_form_fill" for stage in stages)
    assert stages[6]["success_signals"] == ["屏幕墙上可见绑定的4台设备"]


def test_run_detail_assert_uses_screen_wall_device_visibility(monkeypatch):
    class FakePage:
        url = "https://example.test/#/icm"

    async def fake_record(_page, decision, execution, _observe_page):
        return {"decision": decision, "execution": execution}

    async def fake_observe_page(_page):
        return {}

    async def fake_ensure_text_visible(_page, text: str):
        if text == "DxI(2)":
            raise RuntimeError("Expected text not visible: DxI(2)")

    monkeypatch.setattr("runner.agent_stage_router._record", fake_record)
    monkeypatch.setattr("runner.agent_stage_router.ensure_text_visible", fake_ensure_text_visible)
    monkeypatch.setattr("runner.agent_explore.observe_page", fake_observe_page)

    history, error = asyncio.run(
        _run_detail_assert(
            FakePage(),
            {
                "id": "USRMGT_FUN_001",
                "test_data": "勾选设备：AU5800、AU5800(2)、DxI(1)、DxI(2)",
            },
            {"success_signals": ["屏幕墙上可见AU5800、AU5800(2)、DxI(1)、DxI(2)共4台设备"]},
        )
    )

    assert history == []
    assert error == "screen wall devices not visible: DxI(2)"


def test_run_detail_assert_passes_when_all_screen_wall_devices_are_visible(monkeypatch):
    class FakePage:
        url = "https://example.test/#/icm"

    async def fake_record(_page, decision, execution, _observe_page):
        return {"decision": decision, "execution": execution}

    async def fake_observe_page(_page):
        return {}

    async def fake_ensure_text_visible(_page, _text: str):
        return None

    monkeypatch.setattr("runner.agent_stage_router._record", fake_record)
    monkeypatch.setattr("runner.agent_stage_router.ensure_text_visible", fake_ensure_text_visible)
    monkeypatch.setattr("runner.agent_explore.observe_page", fake_observe_page)

    history, error = asyncio.run(
        _run_detail_assert(
            FakePage(),
            {
                "id": "USRMGT_FUN_001",
                "test_data": "勾选设备：AU5800、AU5800(2)、DxI(1)、DxI(2)",
            },
            {"success_signals": ["屏幕墙上可见AU5800、AU5800(2)、DxI(1)、DxI(2)共4台设备"]},
        )
    )

    assert error == ""
    assert history[0]["execution"]["result"] == "detail_assert_passed"
    assert history[0]["decision"]["value"] == "AU5800、AU5800(2)、DxI(1)、DxI(2)"


def test_run_user_device_binding_prefers_checkbox_and_verifies_checked(monkeypatch):
    class FakeCheckboxInput:
        def __init__(self) -> None:
            self.checked = False

        async def count(self) -> int:
            return 1

        async def get_attribute(self, name: str) -> str:
            if name == "class":
                return "el-checkbox__input is-checked" if self.checked else "el-checkbox__input"
            if name == "aria-checked":
                return "true" if self.checked else "false"
            return ""

    class FakeCheckboxInner:
        def __init__(self, checkbox_input: FakeCheckboxInput) -> None:
            self.checkbox_input = checkbox_input
            self.clicked = 0

        async def count(self) -> int:
            return 1

        async def click(self, force: bool = False) -> None:
            self.clicked += 1
            self.checkbox_input.checked = True

    class FakeCheckboxNative:
        def __init__(self, checkbox_input: FakeCheckboxInput) -> None:
            self.checkbox_input = checkbox_input
            self.checked_calls = 0

        async def count(self) -> int:
            return 1

        async def check(self, force: bool = False) -> None:
            self.checked_calls += 1
            self.checkbox_input.checked = True

        async def is_checked(self) -> bool:
            return self.checkbox_input.checked

    class FakeCheckboxLabel:
        def __init__(self, checkbox_input: FakeCheckboxInput) -> None:
            self.checkbox_input = checkbox_input
            self.clicked = 0
            self.scrolled = 0

        async def count(self) -> int:
            return 1

        async def scroll_into_view_if_needed(self) -> None:
            self.scrolled += 1

        async def evaluate(self, _script: str) -> None:
            self.clicked += 1
            self.checkbox_input.checked = True

    class FakeMissingLocator:
        async def count(self) -> int:
            return 0

        def first(self):
            return self

        def nth(self, _index: int):
            return self

        def locator(self, _selector: str):
            return self

    class FakeRow:
        def __init__(self, device_name: str) -> None:
            self.device_name = device_name
            self.checkbox_input = FakeCheckboxInput()
            self.checkbox_inner = FakeCheckboxInner(self.checkbox_input)
            self.checkbox_label = FakeCheckboxLabel(self.checkbox_input)
            self.native_checkbox = FakeCheckboxNative(self.checkbox_input)
            self.switch = FakeMissingLocator()

        async def inner_text(self) -> str:
            return self.device_name

        def locator(self, selector: str):
            if selector == ".el-checkbox__input":
                return _wrap_first(self.checkbox_input)
            if selector == ".el-checkbox__inner":
                return _wrap_first(self.checkbox_inner)
            if selector == "label.el-checkbox":
                return _wrap_first(self.checkbox_label)
            if selector == ".el-switch":
                return _wrap_first(self.switch)
            if selector == "input.el-checkbox__original, input[type='checkbox']":
                return _wrap_first(self.native_checkbox)
            if selector == "input[type='checkbox']":
                return _wrap_first(self.native_checkbox)
            return _wrap_first(FakeMissingLocator())

    class FakeRows:
        def __init__(self, rows) -> None:
            self.rows = rows

        async def count(self) -> int:
            return len(self.rows)

        def nth(self, index: int):
            return self.rows[index]

    class FakeDeviceTable:
        def __init__(self, rows) -> None:
            self.rows = rows

        @property
        def last(self):
            return self

        def locator(self, selector: str):
            if selector == "tr":
                return FakeRows(self.rows)
            return FakeMissingLocator()

        async def count(self) -> int:
            return 1

    class FakeHeading:
        async def count(self) -> int:
            return 1

        @property
        def first(self):
            return self

    class FakePagers(FakeMissingLocator):
        @property
        def last(self):
            return self

    class FakePage:
        def __init__(self, row: FakeRow) -> None:
            self.url = "https://example.test/system/user-auth/server/203"
            self._row = row

        def get_by_text(self, _text: str, exact: bool = False):
            return FakeHeading()

        def locator(self, selector: str):
            if selector == ".el-table__body-wrapper tbody":
                return FakeDeviceTable([self._row])
            if selector == ".el-pagination .el-pager":
                return FakePagers()
            return FakeMissingLocator()

    def _wrap_first(node):
        class _Wrapper:
            def __init__(self, inner):
                self.inner = inner

            @property
            def first(self):
                return self.inner

            def nth(self, _index: int):
                return self.inner

            def locator(self, selector: str):
                return self.inner.locator(selector)

            async def count(self) -> int:
                return await self.inner.count()

        return _Wrapper(node)

    records: list[dict] = []
    row = FakeRow("AU5800")
    page = FakePage(row)

    async def fake_record(_page, decision, execution, _observe_page):
        payload = {"decision": decision, "execution": execution}
        records.append(payload)
        return payload

    async def fake_first_visible(_page, _selectors):
        return None

    async def fake_settle(_page, _ms=0):
        return None

    async def fake_observe_page(_page):
        return {}

    async def fail_switch(*_args, **_kwargs):
        raise AssertionError("should not toggle switch when checkbox exists")

    monkeypatch.setattr("runner.agent_stage_router._record", fake_record)
    monkeypatch.setattr("runner.agent_stage_router.first_visible", fake_first_visible)
    monkeypatch.setattr("runner.agent_explore.observe_page", fake_observe_page)
    monkeypatch.setattr("runner.flows.icm_common.settle", fake_settle)
    monkeypatch.setattr("runner.flows.icm_common.ensure_switch_enabled", fail_switch)

    history, error = asyncio.run(
        _run_user_device_binding(
            page,
            {
                "id": "USRMGT_FUN_001",
                "test_data": "勾选设备：AU5800",
            },
        )
    )

    assert error == ""
    assert len(history) == 1
    assert row.checkbox_inner.clicked == 0
    assert row.checkbox_label.scrolled == 0
    assert row.native_checkbox.checked_calls == 1
    assert row.checkbox_input.checked is True
    assert records[0]["execution"]["result"] == "user_device_bound"


def test_run_user_device_binding_falls_back_to_selection_cell_for_later_rows(monkeypatch):
    class FakeCheckboxInput:
        def __init__(self) -> None:
            self.checked = False

        async def count(self) -> int:
            return 1

        async def get_attribute(self, name: str) -> str:
            if name == "class":
                return "el-checkbox__input is-checked" if self.checked else "el-checkbox__input"
            if name == "aria-checked":
                return "true" if self.checked else "false"
            return ""

    class FakeMissingLocator:
        async def count(self) -> int:
            return 0

        async def click(self, force: bool = False) -> None:
            return None

        async def scroll_into_view_if_needed(self) -> None:
            return None

        async def evaluate(self, _script: str) -> None:
            return None

        async def check(self, force: bool = False) -> None:
            return None

        def first(self):
            return self

        def nth(self, _index: int):
            return self

        def locator(self, _selector: str):
            return self

    class FakeCheckboxInner:
        def __init__(self, checkbox_input: FakeCheckboxInput, toggles: bool) -> None:
            self.checkbox_input = checkbox_input
            self.toggles = toggles

        async def count(self) -> int:
            return 1

        async def click(self, force: bool = False) -> None:
            if self.toggles:
                self.checkbox_input.checked = True

        async def scroll_into_view_if_needed(self) -> None:
            return None

    class FakeCheckboxNative:
        def __init__(self, checkbox_input: FakeCheckboxInput, toggles: bool) -> None:
            self.checkbox_input = checkbox_input
            self.toggles = toggles
            self.checked_calls = 0

        async def count(self) -> int:
            return 1

        async def check(self, force: bool = False) -> None:
            self.checked_calls += 1
            if self.toggles:
                self.checkbox_input.checked = True

        async def is_checked(self) -> bool:
            return self.checkbox_input.checked

    class FakeCheckboxLabel:
        def __init__(self, checkbox_input: FakeCheckboxInput, toggles: bool) -> None:
            self.checkbox_input = checkbox_input
            self.toggles = toggles
            self.clicked = 0

        async def count(self) -> int:
            return 1

        async def scroll_into_view_if_needed(self) -> None:
            return None

        async def evaluate(self, _script: str) -> None:
            self.clicked += 1
            if self.toggles:
                self.checkbox_input.checked = True

    class FakeSelectionCell:
        def __init__(self, checkbox_input: FakeCheckboxInput, toggles: bool) -> None:
            self.checkbox_input = checkbox_input
            self.toggles = toggles
            self.clicked = 0

        async def count(self) -> int:
            return 1

        async def scroll_into_view_if_needed(self) -> None:
            return None

        async def click(self, force: bool = False) -> None:
            self.clicked += 1
            if self.toggles:
                self.checkbox_input.checked = True

    class FakeRow:
        def __init__(self, device_name: str, *, use_cell_fallback: bool = False) -> None:
            self.device_name = device_name
            self.checkbox_input = FakeCheckboxInput()
            self.checkbox_inner = FakeCheckboxInner(self.checkbox_input, toggles=not use_cell_fallback)
            self.checkbox_label = FakeCheckboxLabel(self.checkbox_input, toggles=not use_cell_fallback)
            self.native_checkbox = FakeCheckboxNative(self.checkbox_input, toggles=not use_cell_fallback)
            self.selection_cell = FakeSelectionCell(self.checkbox_input, toggles=use_cell_fallback)
            self.switch = FakeMissingLocator()

        async def inner_text(self) -> str:
            return self.device_name

        def locator(self, selector: str):
            if selector == ".el-checkbox__input":
                return _wrap_first(self.checkbox_input)
            if selector == ".el-checkbox__inner":
                return _wrap_first(self.checkbox_inner)
            if selector == "label.el-checkbox":
                return _wrap_first(self.checkbox_label)
            if selector == "td.el-table-column--selection":
                return _wrap_first(self.selection_cell)
            if selector == ".el-switch":
                return _wrap_first(self.switch)
            if selector == "input.el-checkbox__original, input[type='checkbox']":
                return _wrap_first(self.native_checkbox)
            if selector == "input[type='checkbox']":
                return _wrap_first(self.native_checkbox)
            return _wrap_first(FakeMissingLocator())

    class FakeRows:
        def __init__(self, rows) -> None:
            self.rows = rows

        async def count(self) -> int:
            return len(self.rows)

        def nth(self, index: int):
            return self.rows[index]

    class FakeDeviceTable:
        def __init__(self, rows) -> None:
            self.rows = rows

        @property
        def last(self):
            return self

        def locator(self, selector: str):
            if selector == "tr":
                return FakeRows(self.rows)
            return FakeMissingLocator()

        async def count(self) -> int:
            return 1

    class FakeHeading:
        async def count(self) -> int:
            return 1

        @property
        def first(self):
            return self

    class FakePagers(FakeMissingLocator):
        @property
        def last(self):
            return self

    class FakePage:
        def __init__(self, rows) -> None:
            self.url = "https://example.test/system/user-auth/server/203"
            self.rows = rows

        def get_by_text(self, _text: str, exact: bool = False):
            return FakeHeading()

        def locator(self, selector: str):
            if selector == ".el-table__body-wrapper tbody":
                return FakeDeviceTable(self.rows)
            if selector == ".el-pagination .el-pager":
                return FakePagers()
            return FakeMissingLocator()

    def _wrap_first(node):
        class _Wrapper:
            def __init__(self, inner):
                self.inner = inner

            @property
            def first(self):
                return self.inner

            def nth(self, _index: int):
                return self.inner

            def locator(self, selector: str):
                return self.inner.locator(selector)

            async def count(self) -> int:
                return await self.inner.count()

        return _Wrapper(node)

    records: list[dict] = []
    rows = [FakeRow("AU5800"), FakeRow("DxI(1)", use_cell_fallback=True)]
    page = FakePage(rows)

    async def fake_record(_page, decision, execution, _observe_page):
        payload = {"decision": decision, "execution": execution}
        records.append(payload)
        return payload

    async def fake_first_visible(_page, _selectors):
        return None

    async def fake_settle(_page, _ms=0):
        return None

    async def fake_observe_page(_page):
        return {}

    async def fail_switch(*_args, **_kwargs):
        raise AssertionError("should not toggle switch when checkbox exists")

    monkeypatch.setattr("runner.agent_stage_router._record", fake_record)
    monkeypatch.setattr("runner.agent_stage_router.first_visible", fake_first_visible)
    monkeypatch.setattr("runner.agent_explore.observe_page", fake_observe_page)
    monkeypatch.setattr("runner.flows.icm_common.settle", fake_settle)
    monkeypatch.setattr("runner.flows.icm_common.ensure_switch_enabled", fail_switch)

    history, error = asyncio.run(
        _run_user_device_binding(
            page,
            {
                "id": "USRMGT_FUN_001",
                "test_data": "勾选设备：AU5800、DxI(1)",
            },
        )
    )

    assert error == ""
    assert len(history) == 2
    assert rows[0].checkbox_input.checked is True
    assert rows[1].checkbox_input.checked is True
    assert rows[1].selection_cell.clicked == 1
    assert rows[1].native_checkbox.checked_calls == 1
    assert records[-1]["decision"]["value"] == "DxI(1)"


def _iter_string_literals(source: str) -> list[tuple[int, str]]:
    """Yield (line_no, literal) for every Python string literal in source."""
    import ast

    results: list[tuple[int, str]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return results
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            results.append((node.lineno, node.value))
    return results


def test_agent_stage_router_source_has_no_mojibake():
    """Regression: every Chinese string in agent_stage_router.py must be valid UTF-8 (P0).

    Detects mojibake caused by pasting GBK-encoded Chinese into UTF-8 source files,
    which surfaces as garbled text in step-details "AI 执行详情".
    """
    from pathlib import Path

    source_path = Path(__file__).resolve().parents[1] / "agent_stage_router.py"
    source = source_path.read_text(encoding="utf-8")

    # Private Use Area + uncommon CJK Unified Ideographs blocks indicate garbled bytes.
    bad_code_point_pattern = re.compile(r"[-豈-﫿]")
    private_use_pattern = re.compile(r"[-]")
    pua_chars = {
        f"U+{ord(c):04X}"
        for c in private_use_pattern.findall(source)
    }
    assert not pua_chars, (
        f"agent_stage_router.py contains Private Use Area characters (mojibake indicators): "
        f"{sorted(pua_chars)}"
    )

    # No raw GBK-decoded-as-Latin1 indicators (such as 浣/鐧/璁/寮 etc.)
    gb_mojibake_indicators = [
        "浣跨敤", "鐧诲綍", "璁块棶", "寮圭獥", "鎵撳紑",
        "鍒楄〃", "杈撳叆", "鐐瑰嚮", "瀵嗙爜", "璐﹀彿",
        "鍛戒腑", "鏍￠獙", "娣诲姞", "纭", "鏂板",
        "閫€鍑哄綋鍓", "閫氳繃宸︿晶",
    ]
    found_indicators = [
        marker for marker in gb_mojibake_indicators if marker in source
    ]
    assert not found_indicators, (
        f"agent_stage_router.py contains GBK mojibake fragments: {found_indicators}"
    )

    # Ensure string literals are valid UTF-8 roundtrip.
    for line_no, literal in _iter_string_literals(source):
        if "\u4e00" <= literal <= "\u9fff" or any("\u4e00" <= c <= "\u9fff" for c in literal):
            # CJK-bearing string: must be valid UTF-8 roundtrip and not contain PUA
            encoded = literal.encode("utf-8")
            decoded = encoded.decode("utf-8")
            assert decoded == literal, (
                f"agent_stage_router.py:{line_no} literal is not valid UTF-8 roundtrip"
            )
            assert not private_use_pattern.search(literal), (
                f"agent_stage_router.py:{line_no} contains PUA chars"
            )


def test_run_account_switch_emits_logout_and_login_records(monkeypatch):
    recorded: list[dict] = []

    async def fake_record(_page, decision, execution, _observe_page):
        payload = {"decision": decision, "execution": execution}
        recorded.append(payload)
        return payload

    async def fake_ensure_logged_out(_page, _system):
        return None

    async def fake_perform_login(_page, _system, username=None, password=None):
        assert username == "test"
        assert password == "123456"
        return None

    monkeypatch.setattr("runner.agent_stage_router._record", fake_record)
    monkeypatch.setattr("runner.agent_stage_router.ensure_logged_out", fake_ensure_logged_out)
    monkeypatch.setattr("runner.agent_stage_router.perform_login", fake_perform_login)
    monkeypatch.setattr("runner.agent_stage_router.resolve_case_login_credentials_at", lambda _case, _system, occurrence=2: ("test", "123456"))

    class FakePage:
        pass

    history, error = asyncio.run(
        _run_account_switch(
            FakePage(),
            {},
            {"test_data": "?????admin/?????test???test/123456"},
        )
    )

    assert error == ""
    assert [item["execution"]["result"] for item in history] == ["logged_out_to_login", "account_switch_passed"]
    assert history[0]["decision"]["reason"] == "????????????"
    assert history[1]["decision"]["reason"] == "?? test ????"



def test_agent_stage_router_user_visible_strings_are_chinese():
    """Verify the user-visible reason strings used by stage strategies are Chinese, not mojibake."""
    from runner import agent_stage_router

    captured: list[tuple[str, str]] = []

    async def stubbed_record(_page, decision, execution, _observe_page):
        captured.append(("any", decision.get("reason", "")))
        return {"step": 0, "decision": decision, "execution": execution}

    class _StubPage:
        _case_run_id = ""
        _case_id = ""
        _agent_step_screenshot_index = 0

        async def wait_for_timeout(self, _ms):
            return None

    original_record = agent_stage_router._record
    agent_stage_router._record = stubbed_record
    try:
        async def observe(_page):
            return {}

        async def noop_login(*_args, **_kwargs):
            return None

        # Patch perform_login / ensure_logged_out / goto_route so the call path runs without a real browser.
        import runner.agent_stage_router as router_module

        router_module.perform_login = noop_login
        router_module.ensure_logged_out = noop_login
        router_module.goto_route = noop_login
        router_module.observe_page = observe

        async def _drive() -> None:
            await agent_stage_router._run_login_guard(
                _StubPage(),
                {},
                {"id": "X", "test_data": "username=u;password=p"},
            )

        import asyncio

        asyncio.run(_drive())
    finally:
        agent_stage_router._record = original_record

    assert captured, "login_guard should have been invoked"
    _label, reason = captured[-1]
    assert "浣跨敤" not in reason, f"login_guard reason still has mojibake: {reason!r}"
    assert "登录" in reason, f"login_guard reason should contain 登录: {reason!r}"
    assert "完成" in reason, f"login_guard reason should contain 完成: {reason!r}"
