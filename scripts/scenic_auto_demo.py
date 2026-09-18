"""Drive the whole scenic story through the real UI and capture evidence.

This is the rewritten auto demo for the M4 Agent trunk. It drives the same pages a
person uses, and it exercises the two things that changed when the trunk landed:

1. advice is generated asynchronously, so the demo waits for the "analysis" state to
   become a ready advice card instead of assuming a synchronous answer;
2. the flow gate now blocks dispatch until a duty manager adopts or ignores the
   advice, so the demo asserts that gate instead of clicking straight through it.

The human-operated demo remains `scripts/scenic_demo_launcher.py`; this script is for
rehearsal, regression and screenshot evidence.

Usage::

    $env:SCENIC_DEMO_PASSWORD = "<password>"
    uv run --with playwright python scripts/scenic_auto_demo.py --headless
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = PROJECT_ROOT / "artifacts" / "scenic-e2e" / "auto-demo"
PHOTO = PROJECT_ROOT / "artifacts" / "scenic-e2e" / "synthetic-wheel-inspection.png"
ADVICE_TIMEOUT_SECONDS = 240


class StepFailure(RuntimeError):
    pass


def password() -> str:
    for name in ("SCENIC_DEMO_PASSWORD", "SCENIC_ACCOUNT_PASSWORD", "SCENIC_E2E_PASSWORD"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise SystemExit("Set SCENIC_DEMO_PASSWORD before running")


class Session:
    """One logged-in browser session (run preparation / workspace / field staff)."""

    def __init__(self, browser, base_url: str, user: str, path: str, ready: str, secret: str,
                 username_selector: str = "#login-username",
                 password_selector: str = "#login-password") -> None:
        self.page = browser.new_page(viewport={"width": 1440, "height": 900})
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.secret = secret
        self.page.goto(f"{self.base_url}{path}", wait_until="domcontentloaded", timeout=30_000)
        self.page.fill(username_selector, user)
        self.page.fill(password_selector, secret)
        self.page.click("button[type=submit]")
        self.page.wait_for_selector(ready, state="visible", timeout=30_000)

    def guidance(self):
        return self.page.locator("#scenic-next-action")

    def wait_guidance(self, text: str, *, timeout: int = 90_000) -> None:
        self.guidance().filter(has_text=text).first.wait_for(state="visible", timeout=timeout)

    def click_next(self, button_text: str, next_text: str, *, retries: int = 2,
                   retry_wait: int = 65) -> None:
        """Click a guided next action, waiting out the high-risk decision cooldown."""
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                button = self.guidance().locator("button", has_text=button_text).first
                button.wait_for(state="visible", timeout=60_000)
                button.click()
                self.wait_guidance(next_text, timeout=90_000)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt == retries - 1:
                    break
                print(f"[wait] {button_text} had no effect yet; retrying in {retry_wait}s")
                time.sleep(retry_wait)
        raise StepFailure(f"{button_text} -> {next_text} failed: {last_error}")


class Evidence:
    def __init__(self) -> None:
        self.steps: list[dict] = []
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    def shot(self, page, name: str, detail: str) -> None:
        target = EVIDENCE_DIR / f"{len(self.steps) + 1:02d}-{name}.png"
        page.screenshot(path=str(target), full_page=False)
        self.steps.append(
            {
                "step": name,
                "detail": detail,
                "screenshot": target.name,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        print(f"[ok] {name}: {detail}")

    def write(self, *, ok: bool, note: str = "") -> None:
        payload = {
            "ok": ok,
            "note": note,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "steps": self.steps,
        }
        (EVIDENCE_DIR / "auto-demo-evidence.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
def go_work(session: Session) -> None:
    """Open the work section: the field evidence form and task list live there."""

    session.page.reload(wait_until="domcontentloaded")
    nav = session.page.locator('[data-section="work"]').first
    nav.wait_for(state="visible", timeout=30_000)
    nav.click()
    session.page.wait_for_timeout(500)


def start_task(session: Session, *, task_id: str, attempts: int = 3) -> None:
    """Open the requested task and start it.

    Passing the task id from the command snapshot prevents the demo from grabbing an
    older task left behind by a previous rehearsal. The detail pane only reveals the
    completion form once the task is RUNNING, and that status change needs a re-render,
    so reopen the section and retry instead of failing on a slow refresh.
    """

    if not task_id:
        raise StepFailure("start_task requires the current incident's task id")

    last = ""
    for attempt in range(attempts):
        if attempt:
            # The task detail is a modal dialog; close it before touching the rail again,
            # otherwise the dialog intercepts the navigation click.
            _close_task_dialog(session)
        go_work(session)
        opener = session.page.locator(
            f'button[data-action="open-task"][data-task-id="{task_id}"]'
        ).first
        opener.wait_for(state="visible", timeout=45_000)
        opener.click()
        start = session.page.locator("#task-start-button")
        try:
            start.wait_for(state="visible", timeout=20_000)
        except Exception:  # noqa: BLE001 - already running, or not the open task
            pass
        else:
            start.click()
            try:
                start.wait_for(state="hidden", timeout=20_000)
            except Exception as exc:  # noqa: BLE001
                error = session.page.locator("#task-action-error")
                detail = error.inner_text().strip() if error.count() and error.is_visible() else ""
                last = f"{type(exc).__name__}: {detail}"
                time.sleep(3)
                continue
        form = session.page.locator("#task-complete-form")
        try:
            form.wait_for(state="visible", timeout=45_000)
            return
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}"
            time.sleep(3)
    raise StepFailure(f"task completion form never appeared ({last})")


def approve_incident_decision(session: Session) -> None:
    """Approve the exact decision linked to the current incident.

    The approvals table keeps old requests from earlier rehearsals, so asserting that
    *any* row says approved is not evidence that this run's high-risk action was
    reviewed. Bind the click and the post-condition to the incident's approval id.
    """

    incidents = snapshot(session).get("incidents") or []
    approval_id = str((incidents[0] if incidents else {}).get("decision_approval_id") or "")
    if not approval_id:
        raise StepFailure("current incident has no decision approval")

    session.page.click('.nav-item[data-view="approvals"]')
    approve = session.page.locator(
        f'#approvals-table button[onclick*="{approval_id}"][onclick*="approve"]'
    ).first
    approve.wait_for(state="visible", timeout=60_000)
    approve.click()

    dialog = session.page.locator("#action-dialog")
    dialog.wait_for(state="visible", timeout=30_000)
    session.page.locator("#action-dialog-submit").click()
    dialog.wait_for(state="hidden", timeout=60_000)

    row = session.page.locator("#approvals-table tr").filter(
        has=session.page.locator(f'button[onclick*="{approval_id}"]')
    ).first
    row.filter(has_text="\u5df2\u6279\u51c6").wait_for(timeout=60_000)


def _close_task_dialog(session: Session) -> None:
    dialog = session.page.locator("#task-detail-dialog")
    if not dialog.count() or not dialog.first.is_visible():
        return
    closer = session.page.locator('[data-action="close-task"]')
    if closer.count() and closer.first.is_visible():
        closer.first.click()
        return
    session.page.keyboard.press("Escape")


def _run_text(prep: Session) -> str:
    locator = prep.page.locator("#run")
    return locator.inner_text() if locator.count() else ""


def _simulated_at(prep: Session) -> float | None:
    run = snapshot(prep).get("run") or {}
    value = run.get("simulated_at")
    return float(value) if value is not None else None


def _alert_count(prep: Session) -> int:
    locator = prep.page.locator("#evidence")
    if not locator.count():
        return 0
    try:
        payload = json.loads(locator.inner_text())
    except (ValueError, TypeError):
        return 0
    return len(payload.get("alerts") or [])


_API_TOKENS: dict[tuple[str, str], str] = {}


def _api_token(session: Session) -> str:
    """Mint (and cache) an API token for this session's user."""

    key = (session.base_url, session.user)
    cached = _API_TOKENS.get(key)
    if cached:
        return cached
    payload = json.dumps({"username": session.user, "password": session.secret}).encode("utf-8")
    request = urllib.request.Request(
        session.base_url + "/api/v1/auth/login", data=payload, method="POST"
    )
    request.headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read() or b"{}")
    token = str(body.get("access_token") or "")
    if not token:
        raise StepFailure(f"could not obtain an API token for {session.user}")
    _API_TOKENS[key] = token
    return token


def snapshot(session: Session) -> dict:
    """Read the same snapshot the page renders, using this session's API token."""

    request = urllib.request.Request(
        session.base_url + "/api/v1/scenic/snapshot", method="GET"
    )
    request.headers["Authorization"] = "Bearer " + _api_token(session)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"{}")


def wait_action(session: Session, code: str, *, timeout: int = 120) -> int:
    """Wait until the backend offers `code`, and return its rendered index.

    Driving the demo by action code instead of by button copy keeps it working when the
    product wording changes.
    """

    deadline = time.time() + timeout
    last: list[str] = []
    while time.time() < deadline:
        actions = snapshot(session).get("next_actions") or []
        last = [str(action.get("code")) for action in actions]
        if code in last:
            return last.index(code)
        time.sleep(2)
        session.page.reload(wait_until="domcontentloaded")
    raise StepFailure(f"action {code} never appeared; saw {last}")


def click_action(session: Session, code: str, *, settle: float = 1.5) -> None:
    index = wait_action(session, code)
    button = session.page.locator(f'[data-scenic-next="{index}"]').first
    button.wait_for(state="visible", timeout=30_000)
    button.click()
    time.sleep(settle)


def advance_clock(prep: Session, *, seconds: int, expect_alerts: bool = False) -> None:
    """Advance the clock and confirm the change landed.

    The preparation page posts the command asynchronously and reports failures in a
    transient banner, so a bare click can silently do nothing. Retry once and surface the
    banner instead of letting the demo hang on a stale state.
    """

    before = _simulated_at(prep)
    text = ""
    for attempt in range(2):
        prep.page.click(f'[data-step="{seconds}"]')
        deadline = time.time() + 20
        while time.time() < deadline:
            current = _simulated_at(prep)
            if before is None or current is None or current > before:
                if not expect_alerts or _alert_count(prep):
                    return
            time.sleep(1)
        banner = prep.page.locator("#message")
        text = banner.inner_text().strip() if banner.count() else ""
        print(f"[wait] clock step {seconds}s did not land (attempt {attempt + 1}); banner={text!r}")
        before = _simulated_at(prep)
    raise StepFailure(f"clock did not advance by {seconds}s (banner: {text!r})")


def run(base_url: str, secret: str, channel: str, headless: bool) -> int:
    from playwright.sync_api import sync_playwright

    evidence = Evidence()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel, headless=headless)
        try:
            prep = Session(browser, base_url, "simulation-ops", "/operations/scenic/",
                           "#workspace", secret, "#username", "#password")
            manager = Session(browser, base_url, "wangfang", "/admin/", "#app-screen", secret)
            technician = Session(browser, base_url, "chenyu", "/assistant/", "#app-screen", secret)
            reporter = Session(browser, base_url, "liming", "/assistant/", "#app-screen", secret)

            prep.page.click('[data-command="PREPARE_SCENARIO"]')
            prep.page.locator("#run").filter(has_text="rain_vehicle_east_gate").first.wait_for(timeout=30_000)
            evidence.shot(manager.page, "prepare", "run preparation reset the scenario and clock")

            advance_clock(prep, seconds=2, expect_alerts=True)
            manager.page.reload(wait_until="domcontentloaded")
            wait_action(manager, "CONVERT_ALERT")
            evidence.shot(manager.page, "device_alert", "device alert surfaced in the command center")

            click_action(manager, "CONVERT_ALERT")
            wait_action(manager, "ADD_FIELD_EVIDENCE")
            evidence.shot(manager.page, "convert_alert", "alert converted into a P1 operational incident")

            go_work(reporter)
            reporter.page.wait_for_selector("#scenic-evidence-form", timeout=45_000)
            reporter.page.fill(
                "#scenic-evidence-text",
                "\u540e\u8f6e\u5f02\u54cd\u5e76\u4f34\u968f\u6296\u52a8\uff0c\u5df2\u9760\u8fb9\u505c\u8f66\u5e76\u8bbe\u7f6e\u505c\u8fd0\u6807\u8bc6\u3002",
            )
            reporter.page.set_input_files("#scenic-evidence-file", str(PHOTO))
            reporter.page.click("#scenic-evidence-form button[type=submit]")
            reporter.page.locator("#scenic-evidence-form").wait_for(state="detached", timeout=45_000)
            evidence.shot(reporter.page, "field_evidence", "field staff submitted text and a photo")

            manager.page.reload(wait_until="domcontentloaded")
            wait_action(manager, "RETRIEVE_SOP")
            click_action(manager, "RETRIEVE_SOP", settle=3.0)
            evidence.shot(manager.page, "retrieve_sop", "TEI retrieval grounded the advice request")

            # The trunk generates advice asynchronously. Poll the snapshot rather than
            # the page: reloading in a loop races the render and never observes the card.
            deadline = time.time() + ADVICE_TIMEOUT_SECONDS
            advice = None
            while time.time() < deadline:
                advice = snapshot(manager).get("advice") or None
                if advice and advice.get("status") in {"READY", "FAILED", "SUPERSEDED"}:
                    break
                time.sleep(6)
            if not advice or advice.get("status") != "READY":
                raise StepFailure(
                    "advice never became ready for the duty manager: "
                    + str((advice or {}).get("status"))
                )
            if advice.get("evidence_status") != "GROUNDED":
                raise StepFailure(
                    "advice was not grounded: " + str(advice.get("evidence_status"))
                )

            manager.page.reload(wait_until="domcontentloaded")
            adopt = manager.page.locator('[data-advice-decision="ADOPT"]').first
            adopt.wait_for(state="visible", timeout=60_000)
            evidence.shot(manager.page, "advice_ready", "asynchronous advice arrived with citations")

            # Flow gate: the decision control is the contract, so its presence is the
            # assertion. A dispatch action must not be offered before this point.
            offered = [
                str(action.get("code"))
                for action in (snapshot(manager).get("next_actions") or [])
            ]
            if "CREATE_REPAIR_TASK" in offered:
                raise StepFailure("dispatch was offered before the human advice decision")

            manager.page.locator('[data-advice-decision="ADOPT"]').first.click()
            wait_action(manager, "CREATE_REPAIR_TASK")
            evidence.shot(manager.page, "adopt_advice", "duty manager adopted the advice and unlocked dispatch")

            click_action(manager, "CREATE_REPAIR_TASK", settle=2.5)
            evidence.shot(manager.page, "dispatch", "dispatch draft created and sent to the field")

            incident = (snapshot(manager).get("incidents") or [{}])[0]
            approve_incident_decision(manager)
            evidence.shot(manager.page, "approve", "high-risk decision approved by a human")

            start_task(technician, task_id=str(incident.get("repair_task_id") or ""))
            evidence.shot(technician.page, "accept_task", "technician accepted the repair task")

            for selector, preferred in (("#task-result-primary", "ISOLATED"), ("#task-result-secondary", "READY")):
                options = technician.page.eval_on_selector_all(f"{selector} option", "els => els.map(e => e.value)")
                picked = preferred if preferred in options else (options[1] if len(options) > 1 else options[0])
                technician.page.select_option(selector, picked)
            technician.page.fill(
                "#task-complete-summary",
                "\u786e\u8ba4\u8f6e\u80ce\u65e0\u5f02\u5e38\uff0c12 \u53f7\u8f66\u7ee7\u7eed\u505c\u8fd0\uff0c7 \u53f7\u5907\u7528\u8f66\u590d\u6838\u5408\u683c\u3002",
            )
            technician.page.click("#task-complete-form button[type=submit]")
            technician.page.locator("#task-complete-form").wait_for(state="hidden", timeout=60_000)
            evidence.shot(technician.page, "repair_receipt", "repair task completed with a structured result")

            advance_clock(prep, seconds=28)
            manager.page.reload(wait_until="domcontentloaded")
            manager.page.click('.nav-item[data-view="dashboard"]')
            click_action(manager, "CREATE_DIVERSION_TASK", settle=2.5)
            evidence.shot(manager.page, "diversion_dispatch", "crowd alert produced a diversion task")

            incident = (snapshot(manager).get("incidents") or [{}])[0]
            start_task(reporter, task_id=str(incident.get("diversion_task_id") or ""))
            for selector in ("#task-result-primary", "#task-result-secondary"):
                options = reporter.page.eval_on_selector_all(f"{selector} option", "els => els.map(e => e.value)")
                reporter.page.select_option(selector, options[1] if len(options) > 1 else options[0])
            reporter.page.fill(
                "#task-complete-summary",
                "\u4e1c\u95e8\u5206\u6d41\u5df2\u5b8c\u6210\uff0c\u5ba2\u6d41\u5df2\u6062\u590d\u81f3\u5b89\u5168\u533a\u95f4\u3002",
            )
            reporter.page.click("#task-complete-form button[type=submit]")
            reporter.page.locator("#task-complete-form").wait_for(state="hidden", timeout=60_000)
            evidence.shot(reporter.page, "diversion_receipt", "diversion task completed by field staff")

            advance_clock(prep, seconds=60)
            manager.page.reload(wait_until="domcontentloaded")
            manager.page.click('.nav-item[data-view="dashboard"]')
            click_action(manager, "RESOLVE_INCIDENT", settle=3.0)
            evidence.shot(manager.page, "resolve", "incident resolved after alerts recovered")

            # Closing is a separate gate: evidence, SOP, tasks, approvals and alert
            # recovery must all be present before the command unlocks.
            click_action(manager, "CLOSE_INCIDENT", settle=3.0)
            evidence.shot(manager.page, "close", "closure gate passed and the dossier was sealed")

            evidence.write(ok=True)
            print(f"auto demo finished; evidence in {EVIDENCE_DIR}")
            return 0
        except Exception as exc:  # noqa: BLE001
            evidence.shot(manager.page, "failure", f"{type(exc).__name__}: {exc}")
            evidence.write(ok=False, note=f"{type(exc).__name__}: {exc}")
            print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Drive the scenic story through the UI.")
    parser.add_argument("--base-url", default=os.environ.get("SCENIC_DEMO_BASE_URL", "http://127.0.0.1:8090"))
    parser.add_argument("--browser-channel", default=os.environ.get("SCENIC_DEMO_BROWSER", "msedge"))
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    secret = password()
    if not PHOTO.is_file():
        raise SystemExit(f"field photo fixture is missing: {PHOTO}")
    sys.exit(run(args.base_url, secret, args.browser_channel, args.headless))


if __name__ == "__main__":
    main()
