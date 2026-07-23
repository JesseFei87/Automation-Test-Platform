from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from runner.agent_explore import OBSERVE_PAGE_SCRIPT, _load_case_arg, _write_trace_artifacts, _write_trace_snapshot, allowed_hosts_for_system, build_agent_goal, decide_next_action, run_agent_loop
from runner.browser import load_system
from runner.evidence_recorder import EvidenceRecorder


ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "reports" / "agent-explore"
HARNESS_WINDOW_SIZE = "1600,1100"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _chrome_path() -> str:
    configured = os.environ.get("BROWSER_HARNESS_CHROME", "").strip()
    candidates = [configured]
    try:
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        try:
            candidates.append(playwright.chromium.executable_path)
        finally:
            await playwright.stop()
    except Exception:
        pass
    candidates.extend([shutil.which("chrome"), shutil.which("chrome.exe"), r"C:\Program Files\Google\Chrome\Application\chrome.exe"])
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("Chrome not found; set BROWSER_HARNESS_CHROME")


async def _wait_for_cdp(url: str) -> None:
    for _ in range(20):
        try:
            await asyncio.to_thread(urllib.request.urlopen, f"{url}/json/version", timeout=0.5)
            return
        except OSError:
            await asyncio.sleep(0.25)
    raise RuntimeError(f"Isolated Chrome CDP is unavailable at {url}")


def _redact_password(value: Any, password: str) -> Any:
    if not password:
        return value
    if isinstance(value, dict):
        return {key: _redact_password(item, password) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_password(item, password) for item in value]
    return value.replace(password, "<redacted>") if isinstance(value, str) else value


def _redact_trace(trace: dict[str, Any], password: str) -> dict[str, Any]:
    trace = _redact_password(trace, password)
    for item in trace.get("history") or []:
        observation = item.get("observation") or {}
        passwords = {str(node.get("ref")) for node in observation.get("interactives") or [] if node.get("type") == "password"}
        decision = item.get("decision") or {}
        if decision.get("action") == "fill" and decision.get("ref") in passwords:
            decision["value"] = "<redacted>"
        for node in observation.get("interactives") or []:
            if node.get("type") == "password":
                node["text"] = "<redacted>"
    return trace


def _case_passwords(case: dict[str, Any], system: dict[str, Any]) -> set[str]:
    passwords = {str((system.get("credentials") or {}).get("password") or "").strip()}
    test_data = case.get("test_data")
    if isinstance(test_data, dict):
        passwords.add(str(test_data.get("password") or "").strip())
    else:
        match = __import__("re").search(r"(?:password|密码)\s*[=:：]\s*([^,，;；\s]+)", str(test_data or ""), __import__("re").IGNORECASE)
        if match:
            passwords.add(match.group(1).strip())
    return {value for value in passwords if value}


def _element_knowledge_summary(entry_url: str) -> dict[str, Any]:
    path = ROOT / "reports" / "element-library" / "library.json"
    if not path.exists():
        return {"path": str(path.relative_to(ROOT)), "exists": False}
    library = json.loads(path.read_text(encoding="utf-8"))
    page = next((item for item in library.get("pages") or [] if str(item.get("url_pattern") or "") in entry_url), {})
    return {"path": str(path.relative_to(ROOT)), "exists": True, "page_id": page.get("page_id", ""), "element_count": len(library.get("elements") or [])}


def _is_login_page_case(case: dict[str, Any]) -> bool:
    module = str(case.get("module") or "")
    steps = "\n".join(str(item) for item in case.get("steps") or [])
    return "登录" in module or ("登录" in steps and "密码" in steps)


def _expects_navigation(decision: Any) -> bool:
    if decision.action == "goto":
        return True
    reason = str(decision.reason or "").lower()
    return decision.action in {"click", "press"} and any(
        marker in reason for marker in ("navigate", "redirect", "login", "登录", "跳转", "进入", "打开页面")
    )


async def _wait_for_stable_page(page: Page, previous_url: str, require_url_change: bool) -> None:
    deadline = asyncio.get_running_loop().time() + 8
    previous_state: tuple[str, str, int] | None = None
    stable_count = 0
    while asyncio.get_running_loop().time() < deadline:
        try:
            ready, text_length = await page.evaluate("() => [document.readyState, document.body?.innerText?.length || 0]")
            state = (page.url, str(ready), int(text_length))
            changed = not require_url_change or page.url != previous_url
            stable_count = stable_count + 1 if changed and ready == "complete" and state == previous_state else 0
            if stable_count >= 1:
                return
            previous_state = state
        except Exception:
            previous_state = None
            stable_count = 0
        await asyncio.sleep(0.25)


async def run_harness_explore(run_id: str, case_arg: str) -> dict[str, Any]:
    """Start an isolated CDP browser and leave an auditable Harness bootstrap trace.

    The existing Agent loop remains the sole LLM owner. This bootstrap deliberately
    does not pass credentials or model keys to Browser Harness.
    """
    case = _load_case_arg(case_arg)
    system = load_system(case["system"], case)
    allowed_hosts = sorted(allowed_hosts_for_system(system))
    out_dir = REPORT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir = ROOT / "screenshots" / "runs" / run_id
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    profile_dir = Path(tempfile.mkdtemp(prefix=f"icm-harness-{run_id}-"))
    manifest = {
        "backend": "harness",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cdp_url": f"http://127.0.0.1:{port}",
        "profile_dir": str(profile_dir),
        "allowed_hosts": allowed_hosts,
        "model_credentials_passed": False,
        "window_size": HARNESS_WINDOW_SIZE,
    }
    process: subprocess.Popen[str] | None = None
    playwright: Playwright | None = None
    traced_browser: Browser | None = None
    traced_context: BrowserContext | None = None
    evidence: EvidenceRecorder | None = None
    trace: dict[str, Any] = {
        "ok": False,
        "status": "failed",
        "run_id": run_id,
        "case_id": str(case.get("id") or case_arg),
        "case_arg": case_arg,
        "backend": "harness",
        "evidence_bundle_version": 1,
        "allowed_hosts": allowed_hosts,
        "history": [],
    }
    passwords = _case_passwords(case, system)

    def publish(history: list[dict[str, Any]]) -> None:
        snapshot = {**trace, "status": "running", "history": history, "screenshots": [str(path.relative_to(ROOT)) for path in sorted(screenshot_dir.glob("*.png"))]}
        snapshot = json.loads(json.dumps(snapshot))
        for password in passwords:
            snapshot = _redact_trace(snapshot, password)
        _write_trace_snapshot(run_id, snapshot)

    publish([])
    try:
        if not allowed_hosts:
            raise RuntimeError("No allowed hosts configured for Harness exploration")
        chrome = await _chrome_path()
        manifest["browser_executable"] = chrome
        process = subprocess.Popen(
            [chrome, "--headless=new", f"--window-size={HARNESS_WINDOW_SIZE}", "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check", "about:blank"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        print("[harness] launching isolated Chrome", flush=True)
        try:
            await _wait_for_cdp(str(manifest["cdp_url"]))
        except RuntimeError as exc:
            if process.poll() is not None and process.stderr:
                detail = process.stderr.read().strip()
                if detail:
                    raise RuntimeError(f"{exc}: {detail}") from exc
            raise
        print("[harness] isolated Chrome is ready", flush=True)
        harness = os.environ.get("BROWSER_HARNESS_COMMAND", "").strip() or shutil.which("browser-harness") or str(Path(sys.executable).parent / "Scripts" / "browser-harness.exe")
        if not Path(harness).exists() and not shutil.which(harness):
            raise RuntimeError("browser-harness is not installed; install it with Python 3.11+ before selecting this backend")
        harness_home = Path(os.environ.get("BROWSER_HARNESS_HOME") or ROOT / "platform-data" / "browser-harness")
        harness_home.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "BU_CDP_URL": manifest["cdp_url"], "BU_NAME": f"icm-{run_id}", "BROWSER_HARNESS_HOME": str(harness_home)}
        manifest["harness_home"] = str(harness_home)
        check = await asyncio.to_thread(subprocess.run, [harness, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, env=env)
        if check.returncode != 0:
            raise RuntimeError((check.stderr or "browser-harness startup failed").strip())
        manifest["browser_harness_version"] = (check.stdout or "unknown").strip()
        client = HarnessClient(harness, env)
        entry_url = str(system.get("entry_url") or system.get("base_url") or "").strip()
        if not entry_url:
            raise RuntimeError("No entry URL configured for Harness exploration")
        login_page_case = _is_login_page_case(case)
        playwright = await async_playwright().start()
        traced_browser = await playwright.chromium.connect_over_cdp(str(manifest["cdp_url"]))
        traced_context = traced_browser.contexts[0]
        trace_page = traced_context.pages[0]
        evidence = EvidenceRecorder(run_id, str(case.get("id") or case_arg))
        await evidence.start(trace_page)
        traced_context.on("page", evidence.attach)
        manifest["playwright_trace"] = str(evidence.trace_path.relative_to(ROOT))
        manifest["element_knowledge"] = _element_knowledge_summary(entry_url)
        await traced_context.tracing.group("打开登录页")
        try:
            await client.goto(entry_url)
            await asyncio.sleep(0.1)
            trace_page = traced_context.pages[-1]
            await _wait_for_stable_page(trace_page, "about:blank", require_url_change=True)
            if login_page_case:
                await trace_page.screenshot(path=screenshot_dir / "step-01-goto.png")
        finally:
            await traced_context.tracing.group_end()
        trace["entry_url"] = entry_url
        manifest["secure_login_bridge"] = not login_page_case
        entry_history: list[dict[str, Any]] = []
        screenshot_index = 0
        if login_page_case:
            screenshot_index = 1
            screenshot_name = "step-01-goto.png"
            entry_history.append(
                {
                    "step": 1,
                    "decision": {"action": "goto", "ref": "", "url": entry_url, "value": "", "key": "", "reason": "open login page"},
                    "observation": await client.observe(),
                    "execution": {"result": "navigated", "screenshot_name": screenshot_name},
                }
            )
            publish(entry_history)
            print(f"[harness] step=1 action=goto result=navigated screenshot={screenshot_name}", flush=True)
        if not login_page_case:
            await _secure_login(client, system)
        login_note = "Stay on the login page and follow the case data exactly." if login_page_case else "Login was completed by the secure platform bridge. Do not enter credentials."
        goal = build_agent_goal(case) + f"\nElement knowledge target: {manifest['element_knowledge'].get('page_id') or 'live DOM'}. {login_note}"

        async def execute_with_screenshot(decision: Any, observation: dict[str, Any]) -> dict[str, Any]:
            nonlocal screenshot_index
            assert traced_context is not None
            previous_url = str(observation.get("url") or "")
            await traced_context.tracing.group(str(decision.reason or decision.action))
            try:
                try:
                    result = await client.execute(decision, observation)
                except Exception as exc:
                    result = {"result": "error", "error": str(exc)}
                await asyncio.sleep(0.1)
                trace_page = traced_context.pages[-1]
                if _expects_navigation(decision):
                    await _wait_for_stable_page(trace_page, previous_url, require_url_change=True)
                post_observation = await client.observe()
                screenshot_index += 1
                screenshot_name = f"step-{screenshot_index:02d}-{decision.action}.png"
                try:
                    await trace_page.screenshot(path=screenshot_dir / screenshot_name)
                    result["screenshot_name"] = screenshot_name
                    result["post_observation"] = post_observation
                except Exception as exc:
                    result["screenshot_error"] = str(exc)
            finally:
                await traced_context.tracing.group_end()
            print(
                f"[harness] action={decision.action} result={result.get('result', 'unknown')} screenshot={result.get('screenshot_name', 'missing')}",
                flush=True,
            )
            return result

        def publish_agent_history(history: list[dict[str, Any]]) -> None:
            shifted = [{**item, "step": int(item.get("step") or 0) + len(entry_history)} for item in history]
            publish(entry_history + shifted)

        result = await run_agent_loop(
            goal,
            client.observe,
            decide_next_action,
            execute_with_screenshot,
            set(allowed_hosts),
            max_steps=12,
            on_history=publish_agent_history,
        )
        if entry_history:
            result["history"] = entry_history + [
                {**item, "step": int(item.get("step") or 0) + 1}
                for item in result.get("history") or []
            ]
        trace.update(result)
        trace["final_url"] = (await client.observe()).get("url", "")
        trace["screenshots"] = [str(path.relative_to(ROOT)) for path in sorted(screenshot_dir.glob("*.png"))]
    except Exception as exc:
        detail = ""
        if process and process.poll() is not None and process.stderr:
            detail = process.stderr.read().strip()
        trace["error"] = f"{exc}: {detail}" if detail else str(exc)
    finally:
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        if evidence and traced_context:
            await evidence.stop(traced_context.pages[-1])
            manifest["playwright_trace_exists"] = evidence.trace_path.exists()
            if not evidence.trace_path.exists():
                trace.update({"ok": False, "status": "failed", "error": "Playwright trace.zip was not generated"})
        if playwright:
            await playwright.stop()
        (out_dir / "harness-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    for password in passwords:
        trace = _redact_trace(trace, password)
    trace["manifest_path"] = str((out_dir / "harness-manifest.json").relative_to(ROOT))
    paths = _write_trace_artifacts(run_id, trace, case)
    return {**trace, **paths}


async def run_harness_observation(run_id: str, case_arg: str) -> dict[str, Any]:
    """Manually triggered, read-only re-observation for a failed Harness run."""
    case = _load_case_arg(case_arg)
    system = load_system(case["system"], case)
    allowed_hosts = sorted(allowed_hosts_for_system(system))
    root = ROOT / "reports" / "agent-diagnosis" / run_id
    root.mkdir(parents=True, exist_ok=True)
    screenshot = ROOT / "screenshots" / "runs" / run_id / "diagnosis-observation.png"
    port = _free_port()
    profile_dir = Path(tempfile.mkdtemp(prefix=f"icm-harness-diagnosis-{run_id}-"))
    manifest: dict[str, Any] = {
        "backend": "harness",
        "purpose": "manual_read_only_diagnosis",
        "read_only": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cdp_url": f"http://127.0.0.1:{port}",
        "profile_dir": str(profile_dir),
        "allowed_hosts": allowed_hosts,
        "window_size": HARNESS_WINDOW_SIZE,
    }
    process: subprocess.Popen[str] | None = None
    try:
        if not allowed_hosts:
            raise RuntimeError("No allowed hosts configured for Harness diagnosis")
        chrome = await _chrome_path()
        manifest["browser_executable"] = chrome
        process = subprocess.Popen(
            [chrome, "--headless=new", f"--window-size={HARNESS_WINDOW_SIZE}", "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        await _wait_for_cdp(str(manifest["cdp_url"]))
        harness = os.environ.get("BROWSER_HARNESS_COMMAND", "").strip() or shutil.which("browser-harness") or str(Path(sys.executable).parent / "Scripts" / "browser-harness.exe")
        if not Path(harness).exists() and not shutil.which(harness):
            raise RuntimeError("browser-harness is not installed")
        env = {**os.environ, "BU_CDP_URL": manifest["cdp_url"], "BU_NAME": f"icm-diagnosis-{run_id}", "BROWSER_HARNESS_HOME": str(ROOT / "platform-data" / "browser-harness")}
        client = HarnessClient(harness, env)
        entry_url = str(system.get("entry_url") or system.get("base_url") or "").strip()
        if not entry_url:
            raise RuntimeError("No entry URL configured for Harness diagnosis")
        await client.goto(entry_url)
        logged_in = await _secure_login(client, system)
        observation = await client.observe()
        await client.screenshot(screenshot)
        manifest.update({"finished_at": datetime.now(timezone.utc).isoformat(), "secure_login": logged_in, "screenshot": str(screenshot.relative_to(ROOT))})
        return {"ok": True, "read_only": True, "secure_login": logged_in, "observation": observation, "screenshot": str(screenshot.relative_to(ROOT)), "manifest": manifest}
    except Exception as exc:
        manifest.update({"finished_at": datetime.now(timezone.utc).isoformat(), "error": str(exc)})
        return {"ok": False, "read_only": True, "error": str(exc), "manifest": manifest}
    finally:
        (root / "harness-observation-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


async def _secure_login(client: "HarnessClient", system: dict[str, Any]) -> bool:
    credentials = system.get("credentials") or {}
    username, password = str(credentials.get("username") or ""), str(credentials.get("password") or "")
    observation = await client.observe()
    fields = observation.get("interactives") or []
    password_field = next((item for item in fields if item.get("type") == "password"), None)
    username_field = next((item for item in fields if item.get("type") in {"text", "email"}), None)
    login_button = next((item for item in fields if item.get("tag") == "button"), None)
    if not (username and password and password_field and username_field and login_button):
        return False
    await client.fill_selector(str(username_field["selector"]), username)
    await client.fill_selector(str(password_field["selector"]), password)
    await client.click_selector(str(login_button["selector"]))
    await asyncio.sleep(1.2)
    return True


class HarnessClient:
    """Small, fixed action adapter. LLM output never becomes executable Python."""

    def __init__(self, command: str, env: dict[str, str]) -> None:
        self.command = command
        self.env = env

    async def _call(self, code: str) -> Any:
        marker = "__ICM_HARNESS_RESULT__"
        wrapped = f"import json\nresult = ({code})\nprint('{marker}' + json.dumps(result, ensure_ascii=False))\n"
        completed = await asyncio.to_thread(
            subprocess.run,
            [self.command],
            input=wrapped,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=75,
            env=self.env,
        )
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout or "Browser Harness action failed").strip())
        for line in reversed(completed.stdout.splitlines()):
            if line.startswith(marker):
                return json.loads(line[len(marker) :])
        raise RuntimeError("Browser Harness returned no action result")

    async def observe(self) -> dict[str, Any]:
        result = await self._call(f"js({f'({OBSERVE_PAGE_SCRIPT})()'!r})")
        if not isinstance(result, dict):
            raise RuntimeError("Browser Harness observation is invalid")
        return result

    async def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        script = "__import__('pathlib').Path(%r).write_bytes(__import__('base64').b64decode(cdp('Page.captureScreenshot', format='png')['data']))" % str(path)
        await self._call(script)

    async def goto(self, url: str) -> None:
        await self._call(f"new_tab({url!r}) or page_info()")

    async def fill_selector(self, selector: str, value: str) -> None:
        script = """(() => { const el = document.querySelector(%s); if (!el) throw new Error('target missing'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, %s); el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); return true; })()""" % (json.dumps(selector), json.dumps(value))
        await self._call(f"js({script!r})")

    async def click_selector(self, selector: str) -> None:
        box_script = "(() => { const el = document.querySelector(%s); if (!el) throw new Error('target missing'); const r = el.getBoundingClientRect(); return {x:r.left+r.width/2,y:r.top+r.height/2}; })()" % json.dumps(selector)
        box = await self._call(f"js({box_script!r})")
        await self._call(f"click_at_xy({float(box['x'])}, {float(box['y'])})")

    @staticmethod
    def _target(observation: dict[str, Any], ref: str) -> dict[str, Any]:
        target = next((item for item in observation.get("interactives") or [] if item.get("ref") == ref), None)
        if not target or not target.get("selector"):
            raise RuntimeError(f"Agent selected unknown ref: {ref}")
        return target

    async def execute(self, decision: Any, observation: dict[str, Any]) -> dict[str, Any]:
        action = decision.action
        if action == "goto":
            await self.goto(decision.url)
            return {"result": "navigated", "url": decision.url}
        if action == "wait":
            await asyncio.sleep(1.2)
            return {"result": "waited"}
        if action == "scroll":
            await self._call(f"scroll(0, 0, {int(decision.value or 650)})")
            return {"result": "scrolled"}
        if action == "assert_text":
            text = await self._call("js('document.body.innerText')")
            if decision.value not in str(text):
                raise RuntimeError(f"assertion failed: {decision.value}")
            return {"result": "asserted", "value": decision.value}
        target = self._target(observation, decision.ref)
        selector = str(target["selector"])
        if action == "fill":
            script = """(() => { const el = document.querySelector(%s); if (!el) throw new Error('target missing'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, %s); el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); return true; })()""" % (json.dumps(selector), json.dumps(decision.value))
            await self._call(f"js({script!r})")
            return {"result": "filled", "ref": decision.ref, "selector": selector}
        if action in {"click", "press"}:
            box_script = "(() => { const el = document.querySelector(%s); if (!el) throw new Error('target missing'); const r = el.getBoundingClientRect(); return {x:r.left+r.width/2,y:r.top+r.height/2}; })()" % json.dumps(selector)
            box = await self._call(f"js({box_script!r})")
            await self._call(f"click_at_xy({float(box['x'])}, {float(box['y'])})")
            if action == "press":
                await self._call(f"press_key({(decision.key or 'Enter')!r})")
            return {"result": "clicked" if action == "click" else "pressed", "ref": decision.ref, "selector": selector}
        raise RuntimeError(f"unsupported Harness action: {action}")
