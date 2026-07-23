from types import SimpleNamespace

from runner.harness_explore import _case_passwords, _expects_navigation, _is_login_page_case


def test_login_page_cases_skip_secure_login_bridge() -> None:
    assert _is_login_page_case({"module": "账号/登录"})
    assert _is_login_page_case({"steps": ["账号输入 test，密码留空", "点击登录"]})
    assert not _is_login_page_case({"module": "首页", "steps": ["打开首页"]})


def test_case_passwords_include_case_data_and_platform_credential() -> None:
    assert _case_passwords(
        {"test_data": "username=test, password=123456"},
        {"credentials": {"password": "platform-secret"}},
    ) == {"123456", "platform-secret"}


def test_navigation_wait_is_limited_to_navigation_actions() -> None:
    assert _expects_navigation(SimpleNamespace(action="goto", reason="open page"))
    assert _expects_navigation(SimpleNamespace(action="click", reason="click login button and navigate to screen wall"))
    assert not _expects_navigation(SimpleNamespace(action="click", reason="open dropdown menu"))
