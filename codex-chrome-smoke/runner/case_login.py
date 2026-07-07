from __future__ import annotations

import re
from typing import Any


_AUTH_PRECONDITION_RE = re.compile(
    r"(已登录|已使用\s*[^\s/]+/[^\s]+?\s*登录|以\s*[^\s/]+/[^\s]+?\s*登录|成功登录)",
    re.IGNORECASE,
)
_LOGIN_PAGE_ONLY_RE = re.compile(r"(登录页|打开登录页|位于登录页)", re.IGNORECASE)
_USERNAME_PASSWORD_RE = re.compile(r"username\s*=\s*([^,;，；\s]+).*?password\s*=\s*([^,;，；\s]+)", re.IGNORECASE)
_SLASH_LOGIN_RE = re.compile(r"(?:已使用|使用|以|输入)\s*([^\s/]+)/([^\s,;，；]+)\s*登录", re.IGNORECASE)


def case_requires_authenticated_session(case: dict[str, Any]) -> bool:
    precondition = str(case.get("precondition") or "").strip()
    if not precondition:
        return False
    if _LOGIN_PAGE_ONLY_RE.search(precondition):
        return False
    return bool(_AUTH_PRECONDITION_RE.search(precondition))


def resolve_case_login_credentials(case: dict[str, Any], system: dict[str, Any]) -> tuple[str, str]:
    username, password = resolve_case_login_credentials_at(case, system, occurrence=1)
    return username, password


def resolve_case_login_credentials_at(case: dict[str, Any], system: dict[str, Any], occurrence: int = 1) -> tuple[str, str]:
    username, password = _extract_credentials_from_case(case, occurrence=occurrence)
    if username and password:
        return username, password
    credentials = system.get("credentials") or {}
    return (
        str(credentials.get("username") or "").strip(),
        str(credentials.get("password") or "").strip(),
    )


def _extract_credentials_from_case(case: dict[str, Any], occurrence: int = 1) -> tuple[str, str]:
    matches: list[tuple[str, str]] = []
    for step in case.get("steps") or []:
        credentials = _extract_credentials_from_text(str(step))
        if all(credentials):
            matches.append(credentials)
    if 0 < occurrence <= len(matches):
        return matches[occurrence - 1]
    if matches:
        return matches[0]

    test_data = case.get("test_data")
    if isinstance(test_data, dict):
        username = str(test_data.get("username") or "").strip()
        password = str(test_data.get("password") or "").strip()
        if username and password:
            return username, password

    return _extract_credentials_from_text(
        "\n".join([str(case.get("precondition") or ""), str(test_data or "")])
    )


def _extract_credentials_from_text(text: str) -> tuple[str, str]:
    match = _USERNAME_PASSWORD_RE.search(text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = _SLASH_LOGIN_RE.search(text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "", ""
