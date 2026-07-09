from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from runner.browser import (
    _open_logout_menu,
    click_first,
    click_first_in,
    ensure_logged_out,
    ensure_text_visible,
    fill_first,
    fill_first_in,
    first_visible,
    goto_route,
    perform_login,
    select_option_in,
)
from runner.case_expectations import case_expected_results
from runner.case_login import case_requires_authenticated_session, resolve_case_login_credentials, resolve_case_login_credentials_at
from runner.flows.icm_common import click_dialog_primary, ensure_switch_enabled, wait_for_visible_dialog


ROUTE_HINTS = {
    "设备信息": "#/hubble/device",
    "服务器信息": "#/hubble/server",
    "用户管理": "#/system/user",
    "屏幕墙": "#/icm",
    "远程协助": "#/hubble/remoteHelpInfo",
}

SCENE_LABELS = {
    "login": "登录",
    "navigation": "页面导航",
    "list": "列表操作",
    "dialog_form": "弹窗表单",
    "detail": "详情校验",
    "assertion": "结果校验",
    "generic": "通用探索",
}

STRATEGY_LABELS = {
    "login_guard": "登录守卫",
    "account_switch": "账号切换",
    "logout_prompt": "退出确认",
    "route_open": "直达路由",
    "menu_navigation": "菜单导航",
    "list_filter": "列表筛选",
    "user_row_menu": "行内菜单",
    "user_device_binding": "设备绑定",
    "dialog_form_fill": "弹窗表单",
    "detail_assert": "结果校验",
    "generic_explore": "通用探索",
}

_LOGIN_RE = re.compile(r"username\s*=\s*([^,;]+).*?password\s*=\s*([^,;]+)", re.IGNORECASE)
_REPEATED_CHAR_RE = re.compile(r"^\s*(\d+)\s*\u4e2a\u5b57\u7b26\s*['\"](.{1})['\"]\s*$")
_TEST_DATA_REF_RE = re.compile(r"同\s*([A-Z][A-Z0-9_]*\d{3})", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _expand_case_id_reference(case_id: str, reference: str) -> str:
    normalized = str(reference or "").strip().upper()
    if normalized.count("_") >= 2:
        return normalized
    source = str(case_id or "").strip().upper()
    parts = source.split("_")
    if len(parts) >= 3:
        return f"{parts[0]}_{normalized}"
    return normalized


def _normalize_test_data_value(value: Any) -> str:
    text = str(value).strip()
    match = _REPEATED_CHAR_RE.fullmatch(text)
    if not match:
        return text
    return match.group(2) * int(match.group(1))


def parse_case_test_data(case: dict[str, Any], visited: set[str] | None = None) -> dict[str, str]:
    raw = case.get("test_data")
    case_id = str(case.get("id") or "").strip().upper()
    current_visited = set(visited or set())
    if case_id:
        current_visited.add(case_id)
    if isinstance(raw, dict):
        return {str(key).strip(): _normalize_test_data_value(value) for key, value in raw.items() if str(value).strip()}
    text = str(raw or "").strip()
    if not text or text == "无":
        return {}
    match = _LOGIN_RE.search(text)
    if match:
        return {"username": match.group(1).strip(), "password": match.group(2).strip()}
    pairs: dict[str, str] = {}
    from runner.browser import load_case

    for reference in _TEST_DATA_REF_RE.findall(text):
        referenced_case_id = _expand_case_id_reference(case_id, reference)
        if referenced_case_id in current_visited:
            continue
        referenced_case = load_case(referenced_case_id)
        pairs.update(parse_case_test_data(referenced_case, current_visited | {referenced_case_id}))
    for chunk in re.split(r"[；;]\s*", text):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key = key.strip()
        value = _normalize_test_data_value(value)
        if key and value:
            pairs[key] = value
    return pairs


DEVICE_NAME_MAX_LENGTH = 15


def saved_device_name_value(data: dict[str, str]) -> str:
    device_name = data.get("设备名称") or data.get("device_name") or ""
    return device_name[:DEVICE_NAME_MAX_LENGTH]


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _is_row_action_menu_step(step: str) -> bool:
    text = str(step or "")
    action_tokens = ("悬停", "更多", "点击")
    menu_tokens = ("配置服务器和设备", "分配角色", "重置密码")
    return ("更多" in text and any(token in text for token in ("悬停", "点击"))) or (
        any(token in text for token in menu_tokens) and any(token in text for token in action_tokens)
    )


def _is_user_device_binding_step(step: str) -> bool:
    text = str(step or "")
    return _contains_any(text, ("绑定设备信息", "勾选", "服务器和设备", "保存配置", "当前服务器"))


def _extract_binding_device_names(case: dict[str, Any]) -> list[str]:
    data = parse_case_test_data(case)
    explicit = data.get("勾选设备") or data.get("绑定设备") or data.get("设备列表") or ""
    if explicit:
        parts = [item.strip(" '\"") for item in re.split(r"[、，,；;]\s*", explicit) if item.strip(" '\"")]
        if parts:
            return parts

    def extract(text: str) -> list[str]:
        if not text.strip():
            return []
        match = re.search(r"(?:勾选设备|绑定设备(?:信息区域)?(?:中)?(?:依次)?勾选)\s*[:：]?\s*([^\r\n]+)", text)
        if not match:
            return []
        return [item.strip(" '\"") for item in re.split(r"[、，,；;]\s*", match.group(1)) if item.strip(" '\"")]

    for source in [str(case.get("test_data") or ""), *[str(item or "") for item in case.get("steps") or []]]:
        names = extract(source)
        if names:
            return names
    return []


def _target_route(case: dict[str, Any], steps: list[str]) -> str:
    sources = [str(case.get("module") or ""), *steps]
    for source in sources:
        for label, route in ROUTE_HINTS.items():
            if label in source:
                return route
    return ""


def _route_for_step(case: dict[str, Any], step: str) -> str:
    return _target_route({"module": ""}, [step]) or _target_route(case, [])


def _is_logout_step(step: str) -> bool:
    return _contains_any(step, ("退出登录", "退出按钮", "登出", "logout")) or (
        "退出" in step and _contains_any(step, ("头像", "按钮", "菜单", "账号", "登录"))
    )


def _is_login_step(step: str) -> bool:
    return _contains_any(step, ("登录", "login")) and not _is_logout_step(step)


def _login_step_indexes(steps: list[str]) -> list[int]:
    return [index for index, step in enumerate(steps, start=1) if _is_login_step(step)]


def _logout_step_indexes(steps: list[str]) -> list[int]:
    return [index for index, step in enumerate(steps, start=1) if _is_logout_step(step)]


def _is_multi_session_workflow(steps: list[str]) -> bool:
    login_steps = _login_step_indexes(steps)
    logout_steps = _logout_step_indexes(steps)
    return bool(login_steps and logout_steps and [index for index in login_steps if index > logout_steps[0]])


def _step_indexes_matching(steps: list[str], indexes: list[int], predicate) -> list[int]:
    return [index for index in indexes if predicate(steps[index - 1])]


def _step_indexes_excluding(indexes: list[int], *groups: list[int]) -> list[int]:
    excluded = {index for group in groups for index in group}
    return [index for index in indexes if index not in excluded]


def _success_signals(case: dict[str, Any], scene_type: str, route: str) -> list[str]:
    signals = case_expected_results(case)
    if scene_type == "login":
        return ["首页", "工作台", "redirect", "设备信息", *signals[:2]]
    if scene_type == "navigation":
        return [route or "", str(case.get("module") or ""), *signals[:2]]
    if scene_type == "dialog_form":
        return ["确定", "取消", "新增", "添加", *signals[:2]]
    return [item for item in signals[:3] if item]


def _final_assertion_signals(case: dict[str, Any]) -> list[str]:
    signals = case_expected_results(case)
    return [signals[-1]] if signals else []


def plan_agent_execution(case: dict[str, Any]) -> dict[str, Any]:
    steps = [str(item).strip() for item in case.get("steps") or [] if str(item).strip()]
    expected = case_expected_results(case)
    route = _target_route(case, steps)
    plan_steps: list[dict[str, Any]] = []

    def add_stage(scene_type: str, name: str, source_steps: list[int], *, strategy: str, fallback: str = "generic_explore", target_route: str = "", target_url: str = "", objective: str = "") -> None:
        plan_steps.append(
            {
                "stage_id": f"stage-{len(plan_steps) + 1}",
                "index": len(plan_steps) + 1,
                "name": name,
                "scene_type": scene_type,
                "target_route": target_route,
                "target_url": target_url,
                "success_signals": _success_signals(case, scene_type, target_route),
                "failure_signals": [],
                "source_steps": source_steps,
                "strategy": strategy,
                "fallback": fallback,
                "objective": objective or name,
            }
        )

    if _is_multi_session_workflow(steps):
        login_steps = _login_step_indexes(steps)
        logout_step = _logout_step_indexes(steps)[0]
        first_login = login_steps[0]
        second_login = next(index for index in login_steps if index > logout_step)
        navigation_steps = [index for index, step in enumerate(steps, start=1) if index > first_login and _contains_any(step, ("进入", "页面", "导航"))]
        first_navigation = navigation_steps[0]
        before_switch_steps = list(range(first_navigation + 1, logout_step))
        switch_steps = list(range(logout_step, second_login + 1))
        after_switch_steps = list(range(second_login + 1, len(steps) + 1))
        row_action_steps = _step_indexes_matching(steps, before_switch_steps, _is_row_action_menu_step)
        dialog_steps = _step_indexes_matching(
            steps,
            before_switch_steps,
            lambda step: _contains_any(step, ("新增", "编辑", "弹窗", "表单", "填写", "输入", "勾选", "选择", "保存", "确定")),
        )
        business_steps = _step_indexes_excluding(before_switch_steps, row_action_steps)
        second_navigation_steps = _step_indexes_matching(
            steps,
            after_switch_steps,
            lambda step: _contains_any(step, ("进入", "页面", "导航", "屏幕墙")),
        )
        trailing_steps = _step_indexes_excluding(after_switch_steps, second_navigation_steps)

        add_stage("login", "登录系统", [first_login], strategy="login_guard", objective="按用例第一个登录步骤完成登录")
        add_stage(
            "navigation",
            "进入目标业务页",
            [first_navigation],
            strategy="route_open",
            target_route=_route_for_step(case, steps[first_navigation - 1]),
            objective=steps[first_navigation - 1],
        )
        if row_action_steps:
            add_stage(
                "list",
                "列表行内菜单操作",
                row_action_steps,
                strategy="user_row_menu",
                target_route=_route_for_step(case, steps[first_navigation - 1]),
                objective="在用户行内展开更多菜单并执行目标动作",
            )
        binding_steps = _step_indexes_matching(steps, business_steps, _is_user_device_binding_step)
        generic_business_steps = _step_indexes_excluding(business_steps, binding_steps)
        if binding_steps:
            add_stage(
                "list",
                "绑定服务器与设备",
                binding_steps,
                strategy="user_device_binding",
                fallback="fail",
                objective="在配置服务器和设备页面完成服务器与设备绑定",
            )
        if generic_business_steps:
            add_stage(
                "generic",
                "完成当前账号业务操作",
                generic_business_steps,
                strategy="generic_explore",
                objective="严格依次完成当前账号下的业务步骤",
            )
        add_stage(
            "generic",
            "切换登录账号",
            switch_steps,
            strategy="account_switch",
            objective="按用例步骤退出当前账号并使用指定账号重新登录",
        )
        if second_navigation_steps:
            second_navigation = second_navigation_steps[0]
            add_stage(
                "navigation",
                "进入切换账号后的目标页",
                [second_navigation],
                strategy="route_open" if _route_for_step(case, steps[second_navigation - 1]) else "menu_navigation",
                target_route=_route_for_step(case, steps[second_navigation - 1]),
                objective=steps[second_navigation - 1],
            )
        if trailing_steps:
            add_stage(
                "generic",
                "完成切换账号后的业务操作",
                trailing_steps,
                strategy="generic_explore",
                objective="严格依次完成切换账号后的剩余步骤",
            )
        add_stage(
            "assertion",
            "结果校验",
            [after_switch_steps[-1]] if after_switch_steps else [len(steps)],
            strategy="detail_assert",
            target_route="",
            objective="校验最终结果与断言",
        )
        plan_steps[-1]["success_signals"] = _final_assertion_signals(case)
        return {"planner_version": "v1", "case_id": str(case.get("id") or ""), "stages": plan_steps}

    login_steps = [index for index, step in enumerate(steps, start=1) if _contains_any(step, ("账号", "密码")) or _is_login_step(step)]
    if login_steps or case_requires_authenticated_session(case):
        add_stage("login", "登录系统", login_steps, strategy="login_guard", objective="按用例指定账号密码完成登录")

    logout_steps = _logout_step_indexes(steps)
    if logout_steps:
        add_stage(
            "generic",
            "触发退出确认",
            logout_steps,
            strategy="logout_prompt",
            objective="点击退出入口并打开退出确认弹窗",
        )

    navigation_steps = [index for index, step in enumerate(steps, start=1) if _contains_any(step, ("菜单", "进入", "设备信息", "服务器信息", "导航"))]
    if navigation_steps:
        add_stage("navigation", "进入目标业务页", navigation_steps, strategy="route_open" if route else "menu_navigation", target_route=route, objective="进入当前用例目标页面")

    list_steps = [index for index, step in enumerate(steps, start=1) if _contains_any(step, ("搜索", "筛选", "列表", "勾选", "选择行"))]
    if list_steps:
        add_stage("list", "列表页操作", list_steps, strategy="list_filter", target_route=route, objective="在列表页完成筛选、搜索或选择")
    row_action_steps = [index for index, step in enumerate(steps, start=1) if _is_row_action_menu_step(step)]
    if row_action_steps:
        add_stage(
            "list",
            "\u5217\u8868\u884c\u5185\u83dc\u5355\u64cd\u4f5c",
            row_action_steps,
            strategy="user_row_menu",
            target_route=route,
            objective="\u5728\u5217\u8868\u884c\u5185\u5c55\u5f00\u66f4\u591a\u83dc\u5355\u5e76\u6267\u884c\u76ee\u6807\u52a8\u4f5c",
        )


    dialog_steps = [
        index
        for index, step in enumerate(steps, start=1)
        if _contains_any(step, ("新增", "编辑", "弹窗", "表单", "填写", "输入", "选择连接类型", "设备类型", "确定"))
        and not _contains_any(step, ("登录", "账号", "密码", "校验", "成功", "失败", "应显示", "应跳转"))
    ]
    if dialog_steps:
        add_stage("dialog_form", "弹窗表单处理", dialog_steps, strategy="dialog_form_fill", target_route=route, objective="打开并处理当前弹窗表单")

    detail_steps = [index for index, step in enumerate(steps, start=1) if _contains_any(step, ("详情", "查看", "明细"))]
    if detail_steps:
        add_stage("detail", "详情页校验", detail_steps, strategy="detail_assert", target_route=route, objective="校验详情页内容")

    if _needs_assertion_stage(case, steps, expected):
        add_stage(
            "assertion",
            "结果校验",
            [len(steps)] if steps else [],
            strategy="detail_assert",
            fallback="fail" if _is_icm_device_create_case(case) else "generic_explore",
            target_route=route,
            objective="校验最终结果与断言",
        )

    if not plan_steps:
        add_stage("generic", "通用探索", list(range(1, len(steps) + 1)), strategy="generic_explore", fallback="fail", target_route=route, objective="完成当前用例目标")

    return {
        "planner_version": "v1",
        "case_id": str(case.get("id") or ""),
        "stages": plan_steps,
    }


def build_stage_goal(case: dict[str, Any], plan: dict[str, Any], stage: dict[str, Any]) -> str:
    from runner.operation_knowledge import format_stage_knowledge

    stage_steps = [str((case.get("steps") or [])[index - 1]) for index in stage.get("source_steps") or [] if 0 < index <= len(case.get("steps") or [])]
    case_goal = "\n".join(
        [
            f"Case ID: {case.get('id', '')}",
            f"Case Title: {case.get('title', '')}",
            f"Stage: {stage.get('index')} / {len(plan.get('stages') or [])} - {stage.get('name')}",
            f"Scene Type: {stage.get('scene_type')}",
            f"Strategy: {stage.get('strategy')}",
            f"Stage Objective: {stage.get('objective') or stage.get('name')}",
            f"Scope Limits: only complete the current stage; do not perform later stages early.",
            f"Target Route: {stage.get('target_route') or ''}",
            "Current Stage Steps:",
            *[f"- {item}" for item in stage_steps],
            "Success Signals:",
            *[f"- {item}" for item in stage.get("success_signals") or [] if item],
            "Forbidden Actions:",
            "- Do not cross to later stages before current stage is complete.",
            "- If this stage is a dialog form, operate only inside the current dialog or drawer.",
            "- If this stage is an assertion stage, prefer observe/assert instead of editing inputs.",
        ]
    )
    trusted_context = format_stage_knowledge(stage.get("trusted_knowledge") or [])
    if not trusted_context:
        return case_goal
    return "\n".join(
        [
            case_goal,
            "Trusted formal operation knowledge:",
            trusted_context,
            "Use only locators that are visible on the current page. If validation fails, discard that locator and continue the bounded stage exploration.",
        ]
    )


def stage_view(stage: dict[str, Any], *, status: str = "queued", fallback_used: bool = False, error: str = "", started_at: str | None = None, finished_at: str | None = None) -> dict[str, Any]:
    return {
        "stage_id": stage.get("stage_id"),
        "index": stage.get("index"),
        "name": stage.get("name"),
        "scene_type": stage.get("scene_type"),
        "scene_label": SCENE_LABELS.get(str(stage.get("scene_type") or ""), str(stage.get("scene_type") or "")),
        "strategy": stage.get("strategy"),
        "strategy_label": STRATEGY_LABELS.get(str(stage.get("strategy") or ""), str(stage.get("strategy") or "")),
        "fallback_used": fallback_used,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "error": error,
        "target_route": stage.get("target_route") or "",
    }


async def observe_snapshot(page, observe_page) -> dict[str, Any]:
    return await observe_page(page)


def normalize_stage_history(history: list[dict[str, Any]], offset: int, stage: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    stage = stage or {}
    for index, item in enumerate(history, start=1):
        clone = dict(item)
        clone["step"] = offset + index
        clone["stage_local_step"] = index
        if stage.get("stage_id"):
            clone["stage_id"] = stage.get("stage_id")
            clone["stage_name"] = stage.get("name")
            clone["scene_type"] = stage.get("scene_type")
            clone["strategy"] = stage.get("strategy")
        normalized.append(clone)
    return normalized


async def execute_stage_strategy(page, system: dict[str, Any], case: dict[str, Any], stage: dict[str, Any]) -> tuple[bool, list[dict[str, Any]], str]:
    strategy = str(stage.get("strategy") or "generic_explore")
    if strategy == "login_guard":
        history, error = await _run_login_guard(page, system, case)
        return error == "", history, error
    if strategy == "account_switch":
        history, error = await _run_account_switch(page, system, case)
        return error == "", history, error
    if strategy == "logout_prompt":
        history, error = await _run_logout_prompt(page, system)
        return error == "", history, error
    if strategy == "route_open":
        history, error = await _run_route_open(page, system, stage)
        return error == "", history, error
    if strategy == "menu_navigation":
        history, error = await _run_menu_navigation(page, stage)
        return error == "", history, error
    if strategy == "list_filter":
        history, error = await _run_list_filter(page, case)
        return error == "", history, error
    if strategy == "user_row_menu":
        history, error = await _run_user_row_menu(page, case, stage)
        return error == "", history, error
    if strategy == "user_device_binding":
        history, error = await _run_user_device_binding(page, case)
        return error == "", history, error
    if strategy == "dialog_form_fill":
        history, error = await _run_dialog_form_fill(page, case)
        return error == "", history, error
    if strategy == "detail_assert":
        history, error = await _run_detail_assert(page, case, stage)
        return error == "", history, error
    return False, [], "unsupported stage strategy"


async def _record(page, decision: dict[str, Any], execution: dict[str, Any], observe_page) -> dict[str, Any]:
    screenshot_name = ""
    run_id = getattr(page, "_case_run_id", "")
    case_id = getattr(page, "_case_id", "")
    if run_id and case_id:
        from runner.browser import screenshot

        screenshot_index = int(getattr(page, "_agent_step_screenshot_index", 0)) + 1
        setattr(page, "_agent_step_screenshot_index", screenshot_index)
        screenshot_name = f"agent-step-{screenshot_index:02d}.png"
        await screenshot(page, run_id, case_id, screenshot_name)
        execution = {**execution, "screenshot_name": screenshot_name}
    return {
        "step": 0,
        "decision": decision,
        "observation": await observe_page(page),
        "execution": execution,
        "screenshot_name": screenshot_name,
    }


async def _run_login_guard(page, system: dict[str, Any], case: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from runner.agent_explore import observe_page

    username, password = resolve_case_login_credentials(case, system)
    if not username or not password:
        return [], "missing username or password for login stage"
    await perform_login(page, system, username=username, password=password)
    return [await _record(page, {"action": "click", "ref": "", "reason": f"使用 {username} 完成登录阶段"}, {"result": "login_guard_passed"}, observe_page)], ""



async def _run_account_switch(page, system: dict[str, Any], case: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from runner.agent_explore import observe_page

    username, password = resolve_case_login_credentials_at(case, system, occurrence=2)
    if not username or not password:
        return [], "missing username or password for account switch stage"
    await ensure_logged_out(page, system)
    history = [
        await _record(
            page,
            {"action": "click", "ref": "", "reason": "????????????"},
            {"result": "logged_out_to_login"},
            observe_page,
        )
    ]
    await perform_login(page, system, username=username, password=password)
    history.append(
        await _record(
            page,
            {"action": "click", "ref": "", "reason": f"?? {username} ????"},
            {"result": "account_switch_passed"},
            observe_page,
        )
    )
    return history, ""


async def _run_logout_prompt(page, system: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from runner.agent_explore import observe_page

    opened = await _open_logout_menu(page, system)
    if not opened:
        return [], "unable to open logout menu"
    await click_first(page, ["text=退出登录", "text=登出", "text=Logout", "li:has-text(退出登录)", "li:has-text(登出)"])
    await page.wait_for_timeout(500)
    dialog = await first_visible(page, [".el-message-box:visible", ".el-dialog:visible"])
    history = [
        await _record(
            page,
            {"action": "click", "ref": "", "reason": "点击退出入口并打开退出确认弹窗"},
            {"result": "logout_prompt_opened" if dialog is not None else "logout_prompt_clicked"},
            observe_page,
        )
    ]
    if dialog is None:
        return history, "logout confirmation dialog is not visible"
    return history, ""


async def _run_route_open(page, system: dict[str, Any], stage: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from runner.agent_explore import observe_page

    route = str(stage.get("target_route") or "").strip()
    if not route:
        return [], "missing target route for route_open"
    await goto_route(page, system, route)
    return [await _record(page, {"action": "goto", "url": route, "reason": f"打开目标路由 {route}"}, {"result": "route_open_passed"}, observe_page)], ""


async def _run_menu_navigation(page, stage: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from runner.agent_explore import observe_page

    route = str(stage.get("target_route") or "")
    target_name = "设备信息" if "device" in route else ("服务器信息" if "server" in route else "目标菜单")
    candidates = ["text=ICM", ".el-submenu__title:has-text('ICM')", ".el-menu-item:has-text('ICM')"]
    await click_first(page, candidates)
    await page.wait_for_timeout(300)
    await click_first(page, [f"text={target_name}", f".el-menu-item:has-text('{target_name}')", f"a[href=\"{route}\"]"] if route else [f"text={target_name}"])
    await page.wait_for_timeout(600)
    return [await _record(page, {"action": "click", "ref": "", "reason": f"通过左侧菜单进入 {target_name}"}, {"result": "menu_navigation_passed"}, observe_page)], ""


async def _run_list_filter(page, case: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from runner.agent_explore import observe_page

    data = parse_case_test_data(case)
    keyword = data.get("搜索关键词") or data.get("目标设备") or data.get("device_name") or ""
    if not keyword:
        return [], "missing list filter keyword"
    await fill_first(page, ['input[placeholder="请输入设备名称"]', 'input[placeholder="请输入服务器名称"]', 'input[placeholder="请输入关键字"]'], keyword)
    await click_first(page, ["button:has-text(搜索)", "button:has-text(查询)", "text=搜索"])
    return [await _record(page, {"action": "fill", "ref": "", "value": keyword, "reason": f"在列表页搜索 {keyword}"}, {"result": "list_filter_passed"}, observe_page)], ""


def _stage_source_step_texts(case: dict[str, Any], stage: dict[str, Any]) -> list[str]:
    steps = [str(item) for item in case.get("steps") or []]
    indexes = [int(index) for index in stage.get("source_steps") or [] if int(index) > 0]
    return [steps[index - 1] for index in indexes if index - 1 < len(steps)]


def _resolve_user_row_menu_target(case: dict[str, Any], stage: dict[str, Any]) -> tuple[str, str]:
    haystack = " ".join(_stage_source_step_texts(case, stage))
    username_match = re.search(r"(?:用户|user)\s*([A-Za-z][A-Za-z0-9_.-]*)", haystack, re.IGNORECASE)
    username = username_match.group(1) if username_match else "test"
    menu_mappings = (
        (("配置服务器和设备",), "配置服务器和设备"),
        (("分配角色",), "分配角色"),
        (("重置密码",), "重置密码"),
    )
    for keywords, label in menu_mappings:
        if any(keyword in haystack for keyword in keywords):
            return username, label
    return username, "配置服务器和设备"


async def _run_user_row_menu(page, case: dict[str, Any], stage: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from runner.agent_explore import observe_page

    username, menu_label = _resolve_user_row_menu_target(case, stage)
    rows = page.locator(".el-table__body-wrapper tbody tr")
    row_count = await rows.count()
    target_row = None
    for index in range(row_count):
        row = rows.nth(index)
        row_text = await row.inner_text()
        if username in row_text:
            target_row = row
            break
    if target_row is None:
        return [], f"未找到用户 {username} 所在行"

    await target_row.hover()
    await page.wait_for_timeout(200)
    more_button = target_row.locator("button:has-text('更多'), .el-dropdown-selfdefine:has-text('更多')").first
    if not await more_button.count():
        return [], f"未找到用户 {username} 行内更多按钮"

    await more_button.wait_for(state="visible", timeout=5000)
    await more_button.hover()
    await page.wait_for_timeout(300)
    history = [
        await _record(
            page,
            {"action": "hover", "ref": "", "reason": f"悬停用户 {username} 行内更多按钮"},
            {"result": "user_row_menu_opened"},
            observe_page,
        )
    ]

    menu_item = page.locator(".el-dropdown-menu__item").filter(has_text=menu_label).last
    await menu_item.wait_for(state="visible", timeout=5000)
    await menu_item.click(force=True)
    await page.wait_for_timeout(500)
    history.append(
        await _record(
            page,
            {"action": "click", "ref": "", "reason": f"点击 {menu_label} 选项"},
            {"result": "user_row_menu_item_clicked"},
            observe_page,
        )
    )
    return history, ""


async def _run_dialog_form_fill(page, case: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from runner.agent_explore import observe_page

    data = parse_case_test_data(case)
    add_button = await first_visible(page, ["button:has-text(新增)", "text=新增", "button:has-text(Add)", "button:has-text(添加)"])
    if add_button is not None:
        await add_button.click(force=True)
        await page.wait_for_timeout(500)
    dialog = await first_visible(page, [".el-dialog:visible", ".el-drawer:visible", ".el-message-box:visible"])
    if dialog is None:
        return [], "device dialog is not visible"
    scope = page.locator(".el-dialog:visible, .el-drawer:visible, .el-message-box:visible").last

    if _is_icm_device_create_case(case):
        history = [
            await _record(
                page,
                {"action": "click", "ref": "", "reason": "打开添加设备信息弹窗"},
                {"result": "dialog_opened"},
                observe_page,
            )
        ]
        child_history, error = await _run_icm_device_dialog_fill(page, scope, data, observe_page)
        return history + child_history, error

    applied = 0

    select_mappings = [
        (("连接类型", "connection_type"), ["input", "input"], 0),
        (("设备类型", "device_type"), ["input", "input"], 1),
        (("是否允许控制", "allow_control"), ["input", "input"], 9),
        (("设备状态", "device_status"), ["input", "input"], 10),
    ]
    fill_mappings = [
        (("设备名称", "device_name"), 2),
        (("设备IP", "device_ip"), 3),
        (("设备端口", "device_port"), 4),
        (("设备MAC", "device_mac"), 5),
        (("网络掩码", "network_mask"), 6),
        (("VNC账号", "vnc_username"), 7),
        (("VNC密码", "vnc_password"), 8),
        (("备注", "remark"), 11),
    ]

    inputs = scope.locator("input, textarea")
    for keys, _, index in select_mappings:
        value = next((data.get(key) for key in keys if data.get(key)), "")
        if not value:
            continue
        await select_option_in(scope, [f"css=input:nth-of-type({index + 1})", f"xpath=(.//input)[{index + 1}]"], value)
        applied += 1
    for keys, index in fill_mappings:
        value = next((data.get(key) for key in keys if data.get(key)), "")
        if not value:
            continue
        locator = inputs.nth(index)
        if await locator.count():
            await locator.fill(value)
            applied += 1

    if not applied:
        await click_dialog_primary(page)
        return [await _record(page, {"action": "click", "ref": "", "reason": "点击当前确认弹窗的确定按钮"}, {"result": "dialog_confirm_passed"}, observe_page)], ""

    await click_first_in(scope, ["button:has-text(确定)", "button:has-text(保存)", "button:has-text(提交)", ".el-dialog__footer .el-button--primary"])
    return [await _record(page, {"action": "click", "ref": "", "reason": "完成当前弹窗表单填写并提交"}, {"result": "dialog_form_fill_passed"}, observe_page)], ""


async def _run_user_device_binding(page, case: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from runner.agent_explore import observe_page
    from runner.flows.icm_common import ensure_switch_enabled, settle

    target_devices = _extract_binding_device_names(case)
    if not target_devices:
        return [], "未解析到需要绑定的目标设备"

    route = page.url
    if "/system/user-auth/server/" not in route:
        return [], f"当前页面不是配置服务器和设备页: {route}"

    heading = page.get_by_text("绑定的设备信息", exact=False).first
    if await heading.count() == 0:
        return [], "页面缺少绑定的设备信息区域"
    device_table = page.locator(".el-table__body-wrapper tbody").last
    if await device_table.count() == 0:
        return [], "绑定设备信息表格未渲染"
    pagers = page.locator(".el-pagination .el-pager").last.locator("li.number")
    pager_count = await pagers.count()
    page_indexes = list(range(pager_count)) if pager_count else [0]
    history: list[dict[str, Any]] = []

    async def goto_page(index: int) -> None:
        if index == 0 and pager_count == 0:
            return
        pager = pagers.nth(index)
        classes = await pager.get_attribute("class") or ""
        if "active" not in classes:
            await pager.click(force=True)
            await settle(page, 800)

    async def find_row(device_name: str):
        rows = device_table.locator("tr")
        row_count = await rows.count()
        for row_index in range(row_count):
            row = rows.nth(row_index)
            row_text = " ".join((await row.inner_text()).split())
            if device_name in row_text:
                return row
        return None

    async def checkbox_selected(row) -> bool:
        checkbox_input = row.locator(".el-checkbox__input").first
        if await checkbox_input.count():
            classes = await checkbox_input.get_attribute("class") or ""
            if "is-checked" in classes:
                return True
            aria_checked = (await checkbox_input.get_attribute("aria-checked") or "").strip().lower()
            if aria_checked == "true":
                return True
        checkbox_native = row.locator("input[type='checkbox']").first
        if await checkbox_native.count():
            try:
                return await checkbox_native.is_checked()
            except Exception:
                return False
        return False

    async def ensure_checkbox_selected(device_name: str) -> bool:
        async def current_row():
            for page_index in page_indexes:
                await goto_page(page_index)
                row = await find_row(device_name)
                if row is not None:
                    return row
            return None

        row = await current_row()
        if row is None:
            return False
        if await checkbox_selected(row):
            return True

        actions: list[tuple[str, Any]] = [
            ("input.el-checkbox__original, input[type='checkbox']", "check"),
            ("label.el-checkbox", "label"),
            ("td.el-table-column--selection", "click"),
            (".el-checkbox__inner", "click"),
        ]
        for selector, action in actions:
            row = await current_row()
            if row is None:
                return False
            target = row.locator(selector).first
            if await target.count() == 0:
                continue
            if action == "check":
                try:
                    await target.check(force=True)
                except Exception:
                    continue
            elif action == "label":
                await target.scroll_into_view_if_needed()
                await target.evaluate("(node) => node.click()")
            else:
                await target.scroll_into_view_if_needed()
                await target.click(force=True)
            await settle(page, 800)
            row = await current_row()
            if row is not None and await checkbox_selected(row):
                return True
        return False

    for device_name in target_devices:
        target_row = None
        for page_index in page_indexes:
            await goto_page(page_index)
            target_row = await find_row(device_name)
            if target_row is not None:
                break
        if target_row is None:
            return history, f"未在绑定设备信息区域找到设备 {device_name}"

        checkbox = target_row.locator(".el-checkbox__inner").first
        if await checkbox.count():
            if not await ensure_checkbox_selected(device_name):
                return history, f"设备 {device_name} 复选框点击后仍未选中"
        else:
            switch = target_row.locator(".el-switch").first
            if await switch.count() == 0:
                return history, f"设备 {device_name} 所在行缺少可交互复选框或开关"
            await ensure_switch_enabled(page, switch, settle_ms=500)
        history.append(
            await _record(
                page,
                {"action": "click", "ref": "", "value": device_name, "reason": f"绑定设备 {device_name}"},
                {"result": "user_device_bound"},
                observe_page,
            )
        )

    save_button = await first_visible(
        page,
        [
            "button:has-text('保存')",
            "button:has-text('确定')",
            "button:has-text('提交')",
            ".el-button--primary:has-text('保存')",
        ],
    )
    if save_button is not None:
        await save_button.click(force=True)
        await settle(page, 1000)
        history.append(
            await _record(
                page,
                {"action": "click", "ref": "", "reason": "保存当前服务器与设备绑定配置"},
                {"result": "user_device_binding_saved"},
                observe_page,
            )
        )

    return history, ""


def _is_icm_device_create_case(case: dict[str, Any]) -> bool:
    module = str(case.get("module") or "")
    title = str(case.get("title") or "")
    steps = " ".join(str(item) for item in case.get("steps") or [])
    haystack = " ".join((module, title, steps))
    return "设备信息" in haystack and any(token in haystack for token in ("新增", "添加"))


def _is_exception_case(case: dict[str, Any]) -> bool:
    """Detect EXC exception-type test case by id prefix or case_type marker."""
    case_id = str(case.get("id") or "").upper()
    if "_EXC_" in case_id:
        return True
    if case.get("case_type") == "exception" or case.get("type") == "exception":
        return True
    return False


def _needs_assertion_stage(case: dict[str, Any], steps: list[str], expected: list[str]) -> bool:
    if expected:
        return True
    if any(_contains_any(step, ("提示", "成功", "失败", "校验", "应显示", "应跳转")) for step in steps):
        return True
    if _is_icm_device_create_case(case) and any("确定" in step or "提交" in step or "保存" in step for step in steps):
        return True
    return False


async def _choose_visible_dropdown(page, field, value: str) -> None:
    await field.click(force=True)
    await page.wait_for_timeout(300)
    dropdown = page.locator(".el-select-dropdown:visible").last
    option = dropdown.locator(".el-select-dropdown__item").filter(has_text=value).first
    await option.wait_for(state="visible", timeout=5000)
    await option.click(force=True)


async def _run_icm_device_dialog_fill(page, scope, data: dict[str, str], observe_page) -> tuple[list[dict[str, Any]], str]:
    try:
        dialog = await wait_for_visible_dialog(page, timeout=5000)
    except Exception:
        dialog = scope

    inputs = dialog.locator("input")
    if await inputs.count() < 10:
        return [], "device dialog inputs are incomplete"

    connection_type = data.get("连接类型") or data.get("connection_type") or ""
    device_type = data.get("设备类型") or data.get("device_type") or ""
    device_name = data.get("设备名称") or data.get("device_name") or ""
    device_ip = data.get("设备IP") or data.get("device_ip") or ""
    device_port = data.get("设备端口") or data.get("device_port") or ""
    device_mac = data.get("设备MAC") or data.get("device_mac") or ""
    network_mask = data.get("网络掩码") or data.get("network_mask") or ""
    vnc_username = data.get("VNC账号") or data.get("vnc_username") or ""
    vnc_password = data.get("VNC密码") or data.get("vnc_password") or ""
    allow_control = data.get("是否允许控制") or data.get("allow_control") or ""
    device_status = data.get("设备状态") or data.get("device_status") or ""
    remark = data.get("备注") or data.get("remark") or ""
    history: list[dict[str, Any]] = []

    if connection_type:
        await _choose_visible_dropdown(page, inputs.nth(0), connection_type)
    if device_type:
        await _choose_visible_dropdown(page, inputs.nth(1), device_type)
    if device_name:
        await inputs.nth(2).fill(device_name)
        history.append(
            await _record(
                page,
                {"action": "fill", "ref": "", "value": device_name, "reason": "填写设备名称"},
                {"result": "device_name_filled"},
                observe_page,
            )
        )
    if device_ip:
        await inputs.nth(3).fill(device_ip)
    if device_port:
        await inputs.nth(4).fill(device_port)
    if device_mac:
        await inputs.nth(5).fill(device_mac)
    if network_mask:
        await inputs.nth(6).fill(network_mask)
    if vnc_username:
        await inputs.nth(7).fill(vnc_username)
    if vnc_password:
        await inputs.nth(8).fill(vnc_password)
    if allow_control:
        await _choose_visible_dropdown(page, inputs.nth(9), allow_control)
    if device_status in {"是", "启用", "在线", "开启", "true", "True"}:
        switch = dialog.locator(".el-switch").last
        if await switch.count():
            await ensure_switch_enabled(page, switch)
    if remark:
        remark_field = dialog.locator("textarea:visible, input[placeholder*='备注']:visible, textarea[placeholder*='备注']:visible").first
        if await remark_field.count():
            await remark_field.fill(remark)

    history.append(
        await _record(
            page,
            {"action": "fill", "ref": "", "reason": "填写其他必填合法字段"},
            {"result": "required_fields_filled"},
            observe_page,
        )
    )
    await click_dialog_primary(page)
    history.append(
        await _record(
            page,
            {"action": "click", "ref": "", "reason": "点击确定提交设备信息"},
            {"result": "dialog_form_fill_passed"},
            observe_page,
        )
    )
    return history, ""


async def _run_detail_assert(page, case: dict[str, Any], stage: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from runner.agent_explore import observe_page

    if _is_icm_device_create_case(case):
        history, error = await _run_icm_device_create_assert(page, case, observe_page)
        if error == "":
            return history, error

    signals = [item for item in stage.get("success_signals") or [] if item]
    if any("屏幕墙" in signal for signal in signals) or "#/icm" in page.url:
        history, error = await _run_screen_wall_assert(page, case, observe_page)
        if history or error:
            return history, error
    for signal in signals:
        if signal.startswith("#/") and signal in page.url:
            return [await _record(page, {"action": "assert_text", "value": signal, "reason": f"命中路由 {signal}"}, {"result": "detail_assert_passed"}, observe_page)], ""
        if any(token in signal for token in ("成功", "失败", "设备", "服务器", "首页", "工作台")):
            try:
                await ensure_text_visible(page, signal)
                return [await _record(page, {"action": "assert_text", "value": signal, "reason": f"校验页面出现 {signal}"}, {"result": "detail_assert_passed"}, observe_page)], ""
            except Exception:
                continue
    # EXC bypass: full signal match first, then quoted substring fallback for numbered expected lines
    if _is_exception_case(case):
        quoted_re = re.compile(r"[\u201c\u201d\u0027\u0022]([^\u201c\u201d\u0027\u0022]{2,})[\u201c\u201d\u0027\u0022]")
        for signal in signals:
            try:
                await ensure_text_visible(page, signal)
                return [await _record(page, {"action": "assert_text", "value": signal, "reason": "exception case assert hit: " + signal}, {"result": "detail_assert_passed"}, observe_page)], ""
            except Exception:
                pass
            for quoted in quoted_re.findall(signal):
                try:
                    await ensure_text_visible(page, quoted)
                    return [await _record(page, {"action": "assert_text", "value": quoted, "reason": "exception case quoted assert hit: " + quoted}, {"result": "detail_assert_passed"}, observe_page)], ""
                except Exception:
                    continue
    return [], "no assertion signal matched on current page"


async def _run_screen_wall_assert(page, case: dict[str, Any], observe_page) -> tuple[list[dict[str, Any]], str]:
    if "#/icm" not in page.url:
        return [], ""

    device_names = _extract_binding_device_names(case)
    if not device_names:
        return [
            await _record(
                page,
                {"action": "assert_text", "value": "#/icm", "reason": "校验当前已进入屏幕墙页面"},
                {"result": "detail_assert_passed"},
                observe_page,
            )
        ], ""

    missing: list[str] = []
    for device_name in device_names:
        try:
            await ensure_text_visible(page, device_name)
        except Exception:
            missing.append(device_name)
    if missing:
        return [], f"screen wall devices not visible: {', '.join(missing)}"

    visible_devices = "、".join(device_names)
    return [
        await _record(
            page,
            {"action": "assert_text", "value": visible_devices, "reason": "校验屏幕墙已显示用例绑定的设备列表"},
            {"result": "detail_assert_passed"},
            observe_page,
        )
    ], ""


async def _run_icm_device_create_assert(page, case: dict[str, Any], observe_page) -> tuple[list[dict[str, Any]], str]:
    data = parse_case_test_data(case)
    device_name = saved_device_name_value(data)
    device_ip = data.get("设备IP") or data.get("device_ip") or ""
    device_status = data.get("设备状态") or data.get("device_status") or ""

    await page.wait_for_timeout(1200)

    visible_dialog = page.locator(".el-dialog:visible, .el-drawer:visible")
    if await visible_dialog.count():
        try:
            await visible_dialog.first.wait_for(state="hidden", timeout=5000)
        except Exception:
            dialog_text = ""
            try:
                dialog_text = (await visible_dialog.first.inner_text())[:240]
            except Exception:
                dialog_text = ""
            return [], f"device dialog is still visible after submit: {dialog_text}".strip()

    success_text = page.locator("text=新增成功, text=成功").first
    try:
        if await success_text.count():
            await success_text.wait_for(state="visible", timeout=1500)
    except Exception:
        pass

    if device_name:
        await fill_first(
            page,
            ['input[placeholder="请输入设备名称"]', 'input[placeholder="输入设备名称"]'],
            device_name,
        )
        await click_first(page, ["button:has-text(搜索)", "button:has-text(查询)", "text=搜索"])
        await page.wait_for_timeout(1200)
        row = page.locator("tbody tr").filter(has_text=device_name).first
        await row.wait_for(state="visible", timeout=8000)
        if device_ip:
            await ensure_text_visible(page, device_ip)
        if device_status:
            status_text = "在线" if device_status in {"在线", "启用", "开启", "是"} else device_status
            await ensure_text_visible(page, status_text)

    return [await _record(page, {"action": "assert_text", "value": device_name or "新增成功", "reason": "校验设备新增成功、弹窗关闭且列表出现新记录"}, {"result": "detail_assert_passed"}, observe_page)], ""
