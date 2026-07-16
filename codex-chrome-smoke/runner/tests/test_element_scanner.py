import asyncio
import json

from runner import element_scanner
from runner.agent_explore import OBSERVE_PAGE_SCRIPT


REQUIRED_FIELDS = {
    "element_id",
    "page_id",
    "state",
    "name",
    "human_zh",
    "human_en",
    "tag",
    "role",
    "type",
    "text",
    "placeholder",
    "selectors",
    "locator_variants",
    "actions",
    "risk_level",
    "confidence",
    "last_seen_url",
}


def fake_scan_results():
    return [
        {
            "page": {"page_id": "login", "name": "登录页", "route": "#/login"},
            "observation": {
                "url": "http://localhost:5173/#/login",
                "title": "ICM Login",
                "visibleText": ["登录"],
                "interactives": [
                    {
                        "ref": "e1",
                        "tag": "input",
                        "role": "",
                        "type": "text",
                        "text": "",
                        "placeholder": "账号",
                        "selector": "input[placeholder='账号']",
                    },
                    {
                        "ref": "e2",
                        "tag": "button",
                        "role": "",
                        "type": "",
                        "text": "登录",
                        "placeholder": "",
                        "selector": "button",
                    },
                ],
            },
        }
    ]


def test_default_scan_targets_cover_core_pages():
    targets = element_scanner.default_scan_targets("http://localhost:5173")
    page_ids = {target["page_id"] for target in targets}

    assert {
        "login",
        "home",
        "project_management",
        "requirement_management",
        "testcase_management",
        "execution_center",
        "report_detail",
        "system_settings",
    } <= page_ids
    assert all(target["url"].startswith("http://localhost:5173") for target in targets)


def test_configured_state_triggers_only_allow_actionable_safe_entries():
    triggers = element_scanner._configured_state_triggers(
        {
            "state_triggers": [
                {"state": "tooltip:logout", "selector": ".top_button > img:first-child", "action": "hover", "label": "退出"},
                {"state": "bad", "selector": "", "action": "hover"},
                {"state": "bad", "selector": ".danger", "action": "submit"},
            ]
        }
    )

    assert triggers == [
        {
            "state": "tooltip:logout",
            "selector": ".top_button > img:first-child",
            "action": "hover",
            "label": "退出",
            "block_mutations": "false",
        }
    ]


def test_build_library_reclassifies_login_redirects_to_login_page():
    library = element_scanner.build_library(
        [
            {
                "page": {"page_id": "home", "name": "首页", "route": "#/index", "url": "http://localhost:5173/#/index"},
                "observation": {
                    "url": "http://localhost:5173/#/login?redirect=%2Findex",
                    "title": "ICM Login",
                    "interactives": [
                        {
                            "ref": "e1",
                            "tag": "input",
                            "type": "text",
                            "placeholder": "账号",
                            "selector": "input[placeholder='账号']",
                        }
                    ],
                },
            }
        ]
    )

    assert library["pages"][0]["page_id"] == "login"
    assert library["pages"][0]["blocked_by_login"] is True
    assert library["pages"][0]["requested_page_ids"] == ["home"]
    assert library["elements"][0]["element_id"].startswith("login.")
    assert library["elements"][0]["page_id"] == "login"
    assert library["elements"][0]["last_seen_url"] == "http://localhost:5173/#/login?redirect=%2Findex"


def test_build_library_generates_required_structure():
    library = element_scanner.build_library(fake_scan_results())

    assert library["version"] == "1.0"
    assert library["generated_at"]
    assert library["pages"][0]["page_id"] == "login"
    assert len(library["elements"]) == 2
    for item in library["elements"]:
        assert REQUIRED_FIELDS <= set(item)
        assert item["page_id"] == "login"
        assert item["state"] == "default"
        assert item["last_seen_url"] == "http://localhost:5173/#/login"

    username = library["elements"][0]
    login_button = library["elements"][1]
    assert "fill" in username["actions"]
    assert "press" in username["actions"]
    assert "click" in login_button["actions"]
    assert "登录按钮" in login_button["human_zh"]


def test_build_library_physically_deduplicates_across_states_and_keeps_coverage():
    scan_results = [
        {
            "page": {"page_id": "users", "name": "Users", "route": "#/users", "state": "default"},
            "observation": {
                "url": "https://example.test/#/users",
                "interactives": [{"ref": "e1", "tag": "button", "text": "Add user", "selector": "button.add"}],
            },
        },
        {
            "page": {"page_id": "users", "name": "Users", "route": "#/users", "state": "dialog:create"},
            "observation": {
                "url": "https://example.test/#/users",
                "interactives": [{"ref": "e8", "tag": "button", "text": "Add user", "selector": "button.add"}],
            },
        },
    ]

    library = element_scanner.build_library(scan_results)

    assert len(library["elements"]) == 1
    element = library["elements"][0]
    assert element["state"] == "default"
    assert element["states"] == ["default", "dialog:create"]
    assert element["coverage"] == 2
    assert element["state_coverage"]["dialog:create"]["source_refs"] == ["e8"]
    assert element["state_coverage"]["dialog:create"]["labels"] == ["Add user"]


def test_build_library_semantically_deduplicates_repeated_table_row_controls():
    scan_results = [
        {
            "page": {"page_id": "users", "name": "Users", "route": "#/users", "state": "default"},
            "observation": {
                "url": "https://example.test/#/users",
                "interactives": [
                    {"ref": "e1", "tag": "button", "text": "Edit", "selector": "tbody > tr:nth-of-type(1) > td:last-child > button"},
                    {"ref": "e2", "tag": "button", "text": "Edit", "selector": "tbody > tr:nth-of-type(2) > td:last-child > button"},
                    {"ref": "e3", "tag": "button", "text": "Edit", "selector": "section > header > button"},
                ],
            },
        }
    ]

    library = element_scanner.build_library(scan_results)

    assert len(library["elements"]) == 2
    row_element = next(element for element in library["elements"] if "tbody" in " ".join(element["selectors"]))
    assert row_element["coverage"] == 2
    assert row_element["state_coverage"]["default"]["source_refs"] == ["e1", "e2"]
    assert len(row_element["selectors"]) == 2


def test_deduplicate_library_elements_consolidates_existing_row_duplicates():
    library = {
        "pages": [{"page_id": "users"}],
        "elements": [
            {"page_id": "users", "name": "edit_button", "actions": ["click"], "tag": "button", "selectors": ["tbody > tr:nth-of-type(1) > td > button"], "state": "default", "states": ["default"], "state_coverage": {"default": {"source_refs": ["e1"], "last_seen_urls": []}}, "coverage": 1},
            {"page_id": "users", "name": "edit_button", "actions": ["click"], "tag": "button", "selectors": ["tbody > tr:nth-of-type(2) > td > button"], "state": "default", "states": ["default"], "state_coverage": {"default": {"source_refs": ["e2"], "last_seen_urls": []}}, "coverage": 1},
        ],
    }

    deduplicated = element_scanner.deduplicate_library_elements(library)

    assert len(deduplicated["elements"]) == 1
    assert deduplicated["elements"][0]["coverage"] == 2


def test_login_button_text_is_normalized_to_clean_semantic_name():
    normalized = element_scanner.normalize_element(
        {
            "tag": "button",
            "type": "button",
            "text": "登录 | 登录 登录",
            "selector": "div:nth-of-type(1) > form > div:nth-of-type(4) > div > button",
        },
        {"page_id": "login", "name": "登录页"},
        index=0,
    )

    assert normalized["element_id"] == "login.login_button"
    assert normalized["name"] == "login_button"
    assert normalized["text"] == "登录"
    assert normalized["human_zh"] == ["登录按钮", "登录", "登录页登录按钮"]
    assert normalized["human_en"] == "login button"
    assert normalized["selectors"][0] == 'button:has-text("登录")'
    assert "div:nth-of-type" in normalized["selectors"][1]
    assert normalized["locator_variants"][-1]["kind"] == "css"
    assert normalized["locator_variants"][-1]["stability"] == "low"


def test_normalize_element_records_ranked_locator_variants():
    normalized = element_scanner.normalize_element(
        {
            "tag": "input",
            "role": "textbox",
            "text": "Account",
            "ariaLabel": "Account",
            "name": "username",
            "placeholder": "Enter account",
            "testId": "login-account",
            "testIdAttribute": "data-testid",
            "selector": "form > input:nth-of-type(1)",
        },
        {"page_id": "login", "name": "Login"},
        index=0,
    )

    assert normalized["locator_variants"][:4] == [
        {"kind": "testid", "value": "login-account", "stability": "high", "selector": 'input[data-testid="login-account"]'},
        {"kind": "role_name", "value": "Account", "stability": "high", "role": "textbox"},
        {"kind": "aria_label", "value": "Account", "stability": "high", "selector": 'input[aria-label="Account"]'},
        {"kind": "name", "value": "username", "stability": "high", "selector": 'input[name="username"]'},
    ]


def test_high_risk_element_is_marked_high():
    raw = {"tag": "button", "text": "删除用户", "selector": "button"}

    assert element_scanner.infer_risk_level(raw) == "high"
    normalized = element_scanner.normalize_element(raw, {"page_id": "users", "name": "用户管理"}, index=0)
    assert normalized["risk_level"] == "high"
    assert normalized["actions"] == ["click", "hover"]


def test_infer_state_trigger_allows_safe_lightweight_states():
    assert element_scanner.infer_state_trigger({"tag": "button", "text": "新增用户", "selector": "button"}) == {
        "state": "dialog:create",
        "action": "click",
    }
    assert element_scanner.infer_state_trigger({"tag": "button", "text": "更多", "selector": "button"}) == {
        "state": "dropdown:more",
        "action": "hover",
    }
    assert element_scanner.infer_state_trigger({"tag": "button", "text": "高级筛选", "selector": "button"}) == {
        "state": "panel:filter",
        "action": "click",
    }
    tab_trigger = element_scanner.infer_state_trigger({"tag": "button", "role": "tab", "text": "基础信息", "selector": "button"})
    assert tab_trigger == {"state": "tab:tab", "action": "click"}


def test_infer_state_trigger_rejects_high_risk_elements():
    assert element_scanner.infer_state_trigger({"tag": "button", "text": "确认删除", "selector": "button"}) is None


def test_infer_state_trigger_allows_delete_only_as_a_controlled_dialog():
    trigger = element_scanner.infer_state_trigger({"tag": "button", "text": "Delete user", "selector": "button.delete"})

    assert trigger == {
        "state": "dialog:delete",
        "action": "click",
        "requires_dialog": "true",
        "block_mutations": "true",
    }


def test_write_library_writes_parseable_json(tmp_path):
    library = element_scanner.build_library(fake_scan_results())
    output = element_scanner.write_library(library, tmp_path / "element-library" / "library.json")

    parsed = json.loads(output.read_text(encoding="utf-8"))
    assert parsed["elements"][0]["element_id"].startswith("login.")
    assert parsed["pages"][0]["states"] == ["default"]


def test_scan_page_with_states_adds_safe_state_observations():
    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def click(self, timeout):
            self.page.actions.append(("click", self.selector, timeout))
            self.page.mode = "create_dialog"

        async def hover(self, timeout):
            self.page.actions.append(("hover", self.selector, timeout))
            self.page.mode = "more_menu"

    class Keyboard:
        def __init__(self, page):
            self.page = page

        async def press(self, key):
            self.page.actions.append(("press", key))
            self.page.mode = "default"

    class FakePage:
        def __init__(self):
            self.mode = "default"
            self.actions = []
            self.keyboard = Keyboard(self)

        async def goto(self, url, wait_until, timeout):
            self.actions.append(("goto", url, wait_until, timeout))

        def locator(self, selector):
            return Locator(self, selector)

        async def wait_for_timeout(self, ms):
            self.actions.append(("wait", ms))

        async def evaluate(self, script):
            if self.mode == "create_dialog":
                return {
                    "url": "http://localhost:5173/#/users",
                    "title": "用户管理",
                    "visibleText": ["新增用户", "账号"],
                    "interactives": [{"tag": "input", "placeholder": "账号", "selector": "input[placeholder='账号']"}],
                }
            if self.mode == "more_menu":
                return {
                    "url": "http://localhost:5173/#/users",
                    "title": "用户管理",
                    "visibleText": ["编辑", "查看"],
                    "interactives": [{"tag": "button", "text": "查看", "selector": "button.view"}],
                }
            return {
                "url": "http://localhost:5173/#/users",
                "title": "用户管理",
                "visibleText": ["用户管理"],
                "interactives": [
                    {"ref": "e1", "tag": "button", "text": "新增用户", "selector": "button.add"},
                    {"ref": "e2", "tag": "button", "text": "更多", "selector": "button.more"},
                    {"ref": "e3", "tag": "button", "text": "删除用户", "selector": "button.delete"},
                ],
            }

    page = FakePage()
    results = asyncio.run(element_scanner.scan_page_with_states(page, {"page_id": "users", "name": "用户管理", "url": "#/users"}))

    states = [result["page"]["state"] for result in results]
    assert states == ["default", "dialog:create", "dropdown:more"]
    assert ("click", "button.add", element_scanner.STATE_ACTION_TIMEOUT_MS) in page.actions
    assert ("hover", "button.more", element_scanner.STATE_ACTION_TIMEOUT_MS) in page.actions
    assert all("button.delete" not in str(action) for action in page.actions)


def test_scan_page_with_states_records_and_closes_controlled_delete_dialog():
    class Context:
        pages = []

        async def route(self, *_args):
            return None

        async def unroute(self, *_args):
            return None

    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def click(self, timeout):
            self.page.actions.append(("click", self.selector, timeout))
            self.page.mode = "dialog"

    class Keyboard:
        def __init__(self, page):
            self.page = page

        async def press(self, key):
            self.page.actions.append(("press", key))
            self.page.mode = "default"

    class Page:
        def __init__(self):
            self.context = Context()
            self.keyboard = Keyboard(self)
            self.mode = "default"
            self.actions = []

        def locator(self, selector):
            return Locator(self, selector)

        async def wait_for_timeout(self, _ms):
            return None

        async def evaluate(self, _script):
            if self.mode == "dialog":
                return {"url": "https://example.test/#/users", "dialogs": [{"text": "Delete user"}], "interactives": [{"tag": "button", "text": "Cancel", "selector": "button.cancel"}]}
            return {"url": "https://example.test/#/users", "dialogs": [], "interactives": [{"ref": "e1", "tag": "button", "text": "Delete user", "selector": "button.delete"}]}

    page = Page()
    results = asyncio.run(element_scanner.scan_page_with_states(page, {"page_id": "users", "url": ""}))

    assert [item["page"]["state"] for item in results] == ["default", "dialog:delete"]
    assert ("click", "button.delete", element_scanner.STATE_ACTION_TIMEOUT_MS) in page.actions
    assert ("press", "Escape") in page.actions
    assert all("confirm" not in str(action).lower() for action in page.actions)


def test_scan_page_with_states_records_more_destination_as_separate_page():
    class Context:
        pages = []

        async def route(self, *_args):
            return None

        async def unroute(self, *_args):
            return None

    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def hover(self, timeout):
            self.page.actions.append(("hover", self.selector, timeout))
            self.page.mode = "more"

        async def click(self, timeout):
            self.page.actions.append(("click", self.selector, timeout))
            self.page.mode = "destination"

    class Page:
        def __init__(self):
            self.context = Context()
            self.mode = "default"
            self.url = "https://example.test/#/users"
            self.actions = []

        def locator(self, selector):
            return Locator(self, selector)

        async def goto(self, url, **_kwargs):
            self.url = url
            self.mode = "default"

        async def wait_for_timeout(self, _ms):
            return None

        async def evaluate(self, _script):
            if self.mode == "more":
                return {"url": self.url, "dialogs": [], "interactives": [{"ref": "e2", "tag": "li", "role": "menuitem", "text": "Reset password", "selector": "li.reset-password"}]}
            if self.mode == "destination":
                self.url = "https://example.test/#/users/reset-password"
                return {"url": self.url, "dialogs": [], "interactives": [{"tag": "input", "placeholder": "New password", "selector": "input.password"}]}
            return {"url": self.url, "dialogs": [], "interactives": [{"ref": "e1", "tag": "button", "text": "More", "selector": "button.more"}]}

    results = asyncio.run(element_scanner.scan_page_with_states(Page(), {"page_id": "users", "name": "Users", "url": ""}))

    assert [item["page"]["page_id"] for item in results] == ["users", "users", "users__reset_password"]
    assert results[-1]["observation"]["url"].endswith("#/users/reset-password")


def test_close_controlled_dialog_uses_the_unique_visible_close_button():
    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def click(self, timeout):
            self.page.clicks.append((self.selector, timeout))
            self.page.open = False

    class Keyboard:
        async def press(self, _key):
            return None

    class Page:
        def __init__(self):
            self.keyboard = Keyboard()
            self.open = True
            self.clicks = []

        def locator(self, selector):
            return Locator(self, selector)

        async def wait_for_timeout(self, _ms):
            return None

        async def evaluate(self, _script):
            return {"dialogs": [{"text": "Edit user"}]} if self.open else {"dialogs": []}

    page = Page()
    asyncio.run(element_scanner._close_controlled_dialog(page))

    assert page.clicks == [(".el-dialog__headerbtn:visible", 2000)]


def test_close_controlled_dialog_waits_for_the_close_transition():
    class Locator:
        def __init__(self, page, _selector):
            self.page = page

        async def click(self, timeout):
            assert timeout == 2000
            self.page.closing = True

    class Keyboard:
        async def press(self, _key):
            raise AssertionError("Escape must not race the explicit dialog close")

    class Page:
        def __init__(self):
            self.keyboard = Keyboard()
            self.closing = False

        def locator(self, selector):
            return Locator(self, selector)

        async def wait_for_function(self, _script, timeout):
            assert timeout == 2000
            assert self.closing

        async def evaluate(self, _script):
            return {"dialogs": [{"text": "Edit dictionary"}]}

    asyncio.run(element_scanner._close_controlled_dialog(Page()))


def test_infer_state_trigger_skips_disabled_toolbar_actions():
    assert element_scanner.infer_state_trigger(
        {"text": "修改", "tag": "button", "type": "button", "disabled": True}
    ) is None
    assert element_scanner.infer_state_trigger(
        {"text": "修改", "tag": "button", "type": "button", "disabled": False}
    ) == {
        "state": "dialog:edit",
        "action": "click",
        "requires_dialog": "true",
        "block_mutations": "false",
    }


def test_infer_state_trigger_ignores_navigation_menu_as_more_dropdown():
    assert element_scanner.infer_state_trigger(
        {"text": "系统管理 用户管理 更多", "tag": "li", "role": "menuitem"}
    ) is None
    assert element_scanner.infer_state_trigger(
        {"text": "更多", "tag": "button", "role": "button"}
    ) == {"state": "dropdown:more", "action": "hover"}


def test_state_scan_bounds_failed_candidates_and_reports_progress():
    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def click(self, timeout):
            self.page.calls.append((self.selector, timeout))
            raise RuntimeError("not actionable")

    class Page:
        def __init__(self):
            self.calls = []

        def locator(self, selector):
            return Locator(self, selector)

        async def wait_for_timeout(self, _ms):
            return None

        async def evaluate(self, _script):
            return {
                "url": "https://example.test/#/users",
                "dialogs": [],
                "interactives": [
                    {"text": "修改", "tag": "button", "type": "button", "selector": f"button.edit-{index}"}
                    for index in range(6)
                ],
            }

    page = Page()
    events = []
    results = asyncio.run(
        element_scanner.scan_page_with_states(
            page,
            {"page_id": "users", "url": ""},
            progress_callback=events.append,
        )
    )

    assert len(results) == 1
    assert page.calls == [
        (f"button.edit-{index}", element_scanner.STATE_ACTION_TIMEOUT_MS)
        for index in range(3)
    ]
    assert [event["stage"] for event in events].count("scanning_page_state") == 3
    assert [event["stage"] for event in events].count("page_state_skipped") == 3


def test_scan_page_retries_then_rejects_low_coverage():
    class Page:
        async def goto(self, *_args, **_kwargs):
            return None

        async def wait_for_timeout(self, _ms):
            return None

        async def evaluate(self, _script):
            return {
                "url": "http://example.test/#/devices",
                "interactives": [{"tag": "button", "text": "matrix"}] * 4,
            }

    try:
        asyncio.run(
            element_scanner.scan_page(
                Page(),
                {"page_id": "device_list", "url": "#/devices", "minimum_interactive_count": 30},
            )
        )
    except RuntimeError as exc:
        assert "low coverage: device_list observed 4 interactive elements; minimum is 30" == str(exc)
    else:
        raise AssertionError("expected low coverage scan to fail")


def test_scan_page_waits_for_configured_page_ready_selector():
    class ReadyLocator:
        @property
        def first(self):
            return self

        async def wait_for(self, *, state, timeout):
            assert state == "visible"
            assert timeout == element_scanner.SCAN_NAVIGATION_TIMEOUT_MS

    class Page:
        async def goto(self, *_args, **_kwargs):
            return None

        def locator(self, selector):
            assert selector == ".app-main button:has-text('新增')"
            return ReadyLocator()

        async def wait_for_timeout(self, _ms):
            return None

        async def evaluate(self, _script, *_args):
            return {"url": "http://example.test/#/users", "interactives": [{"tag": "button", "text": "新增"}] * 4}

    result = asyncio.run(
        element_scanner.scan_page(
            Page(),
            {"page_id": "users", "url": "#/users", "ready_selector": ".app-main button:has-text('新增')"},
        )
    )

    assert result["page"]["page_id"] == "users"


def test_scan_page_rejects_navigation_only_observation_when_content_coverage_is_low():
    class Page:
        async def goto(self, *_args, **_kwargs):
            return None

        async def wait_for_timeout(self, _ms):
            return None

        async def evaluate(self, script, *args):
            if script == element_scanner._CONTENT_INTERACTIVE_COUNT_SCRIPT:
                assert args == (".app-main",)
                return 4
            return {"url": "http://example.test/#/users", "interactives": [{"tag": "a", "text": "navigation"}] * 47}

    try:
        asyncio.run(
            element_scanner.scan_page(
                Page(),
                {
                    "page_id": "users",
                    "url": "#/users",
                    "content_selector": ".app-main",
                    "minimum_content_interactive_count": 15,
                },
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "low content coverage: users observed 4 interactive elements in .app-main; minimum is 15"
    else:
        raise AssertionError("expected low content coverage scan to fail")


def test_scan_page_with_states_keeps_two_safe_triggers_of_the_same_kind():
    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def hover(self, timeout):
            self.page.actions.append(("hover", self.selector, timeout))
            self.page.mode = self.selector

    class Keyboard:
        def __init__(self, page):
            self.page = page

        async def press(self, _key):
            self.page.mode = "default"

    class FakePage:
        def __init__(self):
            self.mode = "default"
            self.actions = []
            self.keyboard = Keyboard(self)

        def locator(self, selector):
            return Locator(self, selector)

        async def wait_for_timeout(self, _ms):
            return None

        async def evaluate(self, _script):
            if self.mode != "default":
                return {"url": "http://example.test/#/users", "interactives": [{"tag": "button", "text": self.mode, "selector": self.mode}]}
            return {
                "url": "http://example.test/#/users",
                "interactives": [
                    {"ref": "e1", "tag": "button", "text": "more primary", "selector": "button.more-primary"},
                    {"ref": "e2", "tag": "button", "text": "more secondary", "selector": "button.more-secondary"},
                ],
            }

    results = asyncio.run(
        element_scanner.scan_page_with_states(
            FakePage(),
            {"page_id": "users", "name": "Users", "url": ""},
            max_states=4,
            max_per_state_kind=2,
        )
    )

    assert [result["page"]["state"] for result in results] == ["default", "dropdown:more", "dropdown:more:more_secondary"]


def test_scan_targets_emits_progress_events():
    class FakePage:
        async def goto(self, url, wait_until, timeout):
            pass

        async def evaluate(self, script):
            return {
                "url": "http://localhost:5173/#/users",
                "title": "用户管理",
                "visibleText": ["用户管理"],
                "interactives": [
                    {"tag": "button", "text": "新增用户", "selector": "button.add"},
                    {"tag": "button", "text": "删除用户", "selector": "button.delete"},
                ],
            }

    events = []
    library = asyncio.run(
        element_scanner.scan_targets(
            FakePage(),
            [{"page_id": "users", "name": "用户管理", "url": "#/users"}],
            progress_callback=events.append,
        )
    )

    assert [event["stage"] for event in events] == ["scanning_page", "page_scanned", "library_built"]
    assert events[1]["current_page"] == "users"
    assert events[1]["element_count"] == 2
    assert events[1]["high_risk_count"] == 1
    assert events[-1]["library_element_count"] == len(library["elements"])


def test_scan_targets_rejects_protected_page_redirected_to_login():
    class FakePage:
        async def goto(self, url, wait_until, timeout):
            pass

        async def evaluate(self, script):
            return {
                "url": "https://example.test/#/login?redirect=%2Fdashboard",
                "title": "Login",
                "visibleText": ["Login"],
                "interactives": [{"tag": "button", "text": "Login", "selector": "button.login"}],
            }

    events = []
    try:
        asyncio.run(
            element_scanner.scan_targets(
                FakePage(),
                [{"page_id": "dashboard", "name": "Dashboard", "url": "#/dashboard"}],
                progress_callback=events.append,
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "authenticated scan required: dashboard redirected to login"
    else:
        raise AssertionError("expected protected target redirected to login to fail")

    assert [event["stage"] for event in events] == ["scanning_page", "page_failed"]


def test_scan_targets_include_states_builds_stateful_library():
    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def click(self, timeout):
            self.page.mode = "create_dialog"

        async def hover(self, timeout):
            self.page.mode = "more_menu"

    class Keyboard:
        def __init__(self, page):
            self.page = page

        async def press(self, key):
            self.page.mode = "default"

    class FakePage:
        def __init__(self):
            self.mode = "default"
            self.keyboard = Keyboard(self)

        async def goto(self, url, wait_until, timeout):
            pass

        def locator(self, selector):
            return Locator(self, selector)

        async def wait_for_timeout(self, ms):
            pass

        async def evaluate(self, script):
            if self.mode == "create_dialog":
                return {"url": "http://localhost:5173/#/users", "title": "用户管理", "visibleText": ["账号"], "interactives": [{"tag": "input", "placeholder": "账号", "selector": "input.account"}]}
            return {"url": "http://localhost:5173/#/users", "title": "用户管理", "visibleText": ["用户管理"], "interactives": [{"tag": "button", "text": "新增用户", "selector": "button.add"}]}

    library = asyncio.run(
        element_scanner.scan_targets(
            FakePage(),
            [{"page_id": "users", "name": "用户管理", "url": "#/users"}],
            include_states=True,
        )
    )

    states = {element["state"] for element in library["elements"]}
    assert {"default", "dialog:create"} <= states
    assert "dialog:create" in library["pages"][0]["states"]


def test_scan_and_write_uses_default_targets_and_writes_json(tmp_path):
    class FakePage:
        def __init__(self):
            self.gotos = []

        async def goto(self, url, wait_until, timeout):
            self.gotos.append(url)

        async def evaluate(self, script):
            return {
                "url": "http://localhost:5173/#/login",
                "title": "ICM Login",
                "visibleText": ["登录"],
                "interactives": [{"tag": "button", "text": "登录", "selector": "button"}],
            }

    page = FakePage()
    output = asyncio.run(
        element_scanner.scan_and_write(
            page,
            targets=[{"page_id": "login", "name": "登录页", "url": "#/login"}],
            output_path=tmp_path / "library.json",
        )
    )

    parsed = json.loads(output.read_text(encoding="utf-8"))
    assert page.gotos == ["#/login"]
    assert parsed["elements"][0]["name"] == "login_button"


def test_scan_page_reuses_observe_page_script():
    class FakePage:
        def __init__(self):
            self.gotos = []
            self.scripts = []

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))

        async def evaluate(self, script):
            self.scripts.append(script)
            return {
                "url": "http://localhost:5173/#/login",
                "title": "ICM Login",
                "visibleText": ["登录"],
                "interactives": [],
            }

    page = FakePage()
    result = asyncio.run(element_scanner.scan_page(page, {"page_id": "login", "name": "登录页", "url": "#/login"}))

    assert page.gotos == [("#/login", "domcontentloaded", element_scanner.SCAN_NAVIGATION_TIMEOUT_MS)]
    assert page.scripts == [OBSERVE_PAGE_SCRIPT, element_scanner._UNSCANNABLE_REGIONS_SCRIPT]
    assert result["page"]["state"] == "default"
    assert result["observation"]["title"] == "ICM Login"


def test_scan_page_retries_when_first_observation_has_no_interactives():
    class FakePage:
        def __init__(self):
            self.gotos = []
            self.scripts = []
            self.waits = []

        async def goto(self, url, wait_until, timeout):
            self.gotos.append((url, wait_until, timeout))

        async def wait_for_timeout(self, ms):
            self.waits.append(ms)

        async def evaluate(self, script):
            self.scripts.append(script)
            if len(self.scripts) == 1:
                return {
                    "url": "http://localhost:5173/#/login",
                    "title": "ICM Login",
                    "visibleText": ["登录"],
                    "interactives": [],
                }
            return {
                "url": "http://localhost:5173/#/login",
                "title": "ICM Login",
                "visibleText": ["登录"],
                "interactives": [{"tag": "button", "text": "登录", "selector": "button.login"}],
            }

    page = FakePage()
    result = asyncio.run(element_scanner.scan_page(page, {"page_id": "login", "name": "登录页", "url": "#/login"}))

    assert page.gotos == [("#/login", "domcontentloaded", element_scanner.SCAN_NAVIGATION_TIMEOUT_MS)]
    assert page.waits == [500]
    assert page.scripts == [OBSERVE_PAGE_SCRIPT, OBSERVE_PAGE_SCRIPT, element_scanner._UNSCANNABLE_REGIONS_SCRIPT]
    assert result["observation"]["interactives"][0]["text"] == "登录"


def test_scan_page_records_visible_iframe_and_canvas_regions():
    class FakePage:
        async def goto(self, *_args, **_kwargs):
            return None

        async def evaluate(self, script):
            if script == element_scanner._UNSCANNABLE_REGIONS_SCRIPT:
                return [
                    {"kind": "iframe", "reason": "cross_origin_or_unavailable_iframe", "selector": "iframe:nth-of-type(1)", "label": "remote", "src": "https://remote.example"},
                    {"kind": "canvas", "reason": "canvas_visual_surface_not_dom_scanned", "selector": "canvas:nth-of-type(1)", "label": "mine-canvas", "src": ""},
                ]
            return {"url": "https://example.test/#/icm", "interactives": []}

    result = asyncio.run(element_scanner.scan_page(FakePage(), {"page_id": "screen_wall", "url": "#/icm"}))

    assert result["observation"]["unscannable_regions"] == [
        {"kind": "iframe", "reason": "cross_origin_or_unavailable_iframe", "selector": "iframe:nth-of-type(1)", "label": "remote", "src": "https://remote.example"},
        {"kind": "canvas", "reason": "canvas_visual_surface_not_dom_scanned", "selector": "canvas:nth-of-type(1)", "label": "mine-canvas", "src": ""},
    ]


def test_configured_surface_hints_only_add_visible_controls():
    class Locator:
        async def count(self):
            return 2

        def nth(self, index):
            return Candidate(index)

    class Candidate:
        def __init__(self, index):
            self.index = index

        async def is_visible(self):
            return self.index == 0

        async def inner_text(self):
            return "Screen mode"

    class FakePage:
        def locator(self, _selector):
            return Locator()

    observation = asyncio.run(
        element_scanner._append_configured_surface_hints(
            FakePage(),
            {"surface_hints": [{"selector": ".screen-mode", "label": "Screen mode", "max_matches": 2}]},
            {"interactives": []},
        )
    )

    assert observation["interactives"] == [
        {
            "ref": "configured-surface-1-1",
            "tag": "div",
            "role": "button",
            "text": "Screen mode",
            "ariaLabel": "Screen mode",
            "selector": ".screen-mode >> nth=0",
            "disabled": False,
        }
    ]
