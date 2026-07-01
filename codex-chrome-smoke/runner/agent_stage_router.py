from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from runner.browser import (
    click_first,
    click_first_in,
    ensure_text_visible,
    fill_first,
    fill_first_in,
    first_visible,
    goto_route,
    perform_login,
    select_option_in,
)
from runner.case_expectations import case_expected_results
from runner.case_login import case_requires_authenticated_session, resolve_case_login_credentials
from runner.flows.icm_common import click_dialog_primary, ensure_switch_enabled, wait_for_visible_dialog


ROUTE_HINTS = {
    "设备信息": "#/hubble/device",
    "服务器信息": "#/hubble/server",
    "用户管理": "#/system/user",
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
    "route_open": "直达路由",
    "menu_navigation": "菜单导航",
    "list_filter": "列表筛选",
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


def _target_route(case: dict[str, Any], steps: list[str]) -> str:
    sources = [str(case.get("module") or ""), *steps]
    for source in sources:
        for label, route in ROUTE_HINTS.items():
            if label in source:
                return route
    return ""


def _route_for_step(case: dict[str, Any], step: str) -> str:
    return _target_route({"module": ""}, [step]) or _target_route(case, [])


def _is_multi_session_workflow(steps: list[str]) -> bool:
    login_steps = [step for step in steps if _contains_any(step, ("登录", "login"))]
    return len(login_steps) > 1 and any(_contains_any(step, ("退出登录", "登出", "logout")) for step in steps)


def _success_signals(case: dict[str, Any], scene_type: str, route: str) -> list[str]:
    signals = case_expected_results(case)
    if scene_type == "login":
        return ["首页", "工作台", "redirect", "设备信息", *signals[:2]]
    if scene_type == "navigation":
        return [route or "", str(case.get("module") or ""), *signals[:2]]
    if scene_type == "dialog_form":
        return ["确定", "取消", "新增", "添加", *signals[:2]]
    return [item for item in signals[:3] if item]


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
        login_steps = [index for index, step in enumerate(steps, start=1) if _contains_any(step, ("登录", "login"))]
        logout_step = next(index for index, step in enumerate(steps, start=1) if _contains_any(step, ("退出登录", "登出", "logout")))
        first_login = login_steps[0]
        second_login = next(index for index in login_steps if index > logout_step)
        navigation_steps = [index for index, step in enumerate(steps, start=1) if index > first_login and _contains_any(step, ("进入", "页面", "导航"))]
        first_navigation = navigation_steps[0]
        final_steps = list(range(second_login + 1, len(steps) + 1))

        add_stage("login", "登录系统", [first_login], strategy="login_guard", objective="按用例第一个登录步骤完成登录")
        add_stage(
            "navigation",
            "进入目标业务页",
            [first_navigation],
            strategy="route_open",
            target_route=_route_for_step(case, steps[first_navigation - 1]),
            objective=steps[first_navigation - 1],
        )
        add_stage(
            "generic",
            "完成当前账号业务操作",
            list(range(first_navigation + 1, logout_step)),
            strategy="generic_explore",
            objective="严格依次完成当前账号下的业务步骤",
        )
        add_stage(
            "generic",
            "切换登录账号",
            list(range(logout_step, second_login + 1)),
            strategy="generic_explore",
            objective="按用例步骤退出当前账号并使用指定账号重新登录",
        )
        add_stage(
            "generic",
            "完成切换账号后的业务操作",
            final_steps,
            strategy="generic_explore",
            objective="严格依次完成切换账号后的剩余步骤",
        )
        add_stage(
            "assertion",
            "结果校验",
            [len(steps)],
            strategy="detail_assert",
            target_route="",
            objective="校验最终结果与断言",
        )
        return {"planner_version": "v1", "case_id": str(case.get("id") or ""), "stages": plan_steps}

    login_steps = [index for index, step in enumerate(steps, start=1) if _contains_any(step, ("登录", "账号", "密码", "login"))]
    if login_steps or case_requires_authenticated_session(case):
        add_stage("login", "登录系统", login_steps, strategy="login_guard", objective="按用例指定账号密码完成登录")

    navigation_steps = [index for index, step in enumerate(steps, start=1) if _contains_any(step, ("菜单", "进入", "设备信息", "服务器信息", "导航"))]
    if navigation_steps:
        add_stage("navigation", "进入目标业务页", navigation_steps, strategy="route_open" if route else "menu_navigation", target_route=route, objective="进入当前用例目标页面")

    list_steps = [index for index, step in enumerate(steps, start=1) if _contains_any(step, ("搜索", "筛选", "列表", "勾选", "选择行"))]
    if list_steps:
        add_stage("list", "列表页操作", list_steps, strategy="list_filter", target_route=route, objective="在列表页完成筛选、搜索或选择")

    dialog_steps = [index for index, step in enumerate(steps, start=1) if _contains_any(step, ("新增", "编辑", "弹窗", "表单", "填写", "输入", "选择连接类型", "设备类型", "确定"))]
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
    return case_goal


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
    if strategy == "route_open":
        history, error = await _run_route_open(page, system, stage)
        return error == "", history, error
    if strategy == "menu_navigation":
        history, error = await _run_menu_navigation(page, stage)
        return error == "", history, error
    if strategy == "list_filter":
        history, error = await _run_list_filter(page, case)
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


async def _run_dialog_form_fill(page, case: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    from runner.agent_explore import observe_page

    data = parse_case_test_data(case)
    add_button = await first_visible(page, ["button:has-text(新增)", "text=新增", "button:has-text(Add)", "button:has-text(添加)"])
    if add_button is not None:
        await add_button.click(force=True)
        await page.wait_for_timeout(500)
    dialog = await first_visible(page, [".el-dialog:visible", ".el-drawer:visible"])
    if dialog is None:
        return [], "device dialog is not visible"
    scope = page.locator(".el-dialog:visible, .el-drawer:visible").last

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
        return [], "no dialog form values were applied"

    await click_first_in(scope, ["button:has-text(确定)", "button:has-text(保存)", "button:has-text(提交)", ".el-dialog__footer .el-button--primary"])
    return [await _record(page, {"action": "click", "ref": "", "reason": "完成当前弹窗表单填写并提交"}, {"result": "dialog_form_fill_passed"}, observe_page)], ""


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
