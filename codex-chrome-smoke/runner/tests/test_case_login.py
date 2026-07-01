from runner.case_login import resolve_case_login_credentials


def test_login_credentials_follow_first_explicit_login_step() -> None:
    case = {
        "precondition": "test/123456 账号存在",
        "test_data": "登录账号：admin/对应密码；test账号：test/123456",
        "steps": [
            "1. 打开 ICM 登录页，输入 admin/Hubble_Service!1088 登录",
            "6. 退出登录",
            "7. 使用 test/123456 登录",
        ],
    }
    system = {"credentials": {"username": "platform-admin", "password": "platform-password"}}

    assert resolve_case_login_credentials(case, system) == ("admin", "Hubble_Service!1088")


def test_login_credentials_fall_back_to_structured_test_data() -> None:
    case = {"test_data": {"username": "case-user", "password": "case-password"}, "steps": []}
    system = {"credentials": {"username": "platform-admin", "password": "platform-password"}}

    assert resolve_case_login_credentials(case, system) == ("case-user", "case-password")
