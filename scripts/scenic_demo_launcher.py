"""Open one logged-in browser window per role for the scenic area demo.

This is a convenience launcher, not a playback script: it opens the demo entry points,
signs each role in through that page's own login form, and then hands the windows to the
operator. Every business action after that is performed by the person, in the real UI.

Usage::

    $env:SCENIC_DEMO_PASSWORD = "<shared demo password>"
    uv run --with playwright python scripts/scenic_demo_launcher.py

Add ``--headless --verify-only`` to smoke-test the login path without opening windows.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCREENSHOT_DIR = PROJECT_ROOT / "artifacts" / "scenic-e2e" / "ui-demo"


@dataclass(frozen=True)
class DemoWindow:
    key: str
    title: str
    username: str
    path: str
    username_selector: str
    password_selector: str
    ready_selector: str


DEMO_WINDOWS: tuple[DemoWindow, ...] = (
    DemoWindow(
        key="prep",
        title="运行准备（模拟输入与时钟）",
        username="simulation-ops",
        path="/operations/scenic/",
        username_selector="#username",
        password_selector="#password",
        ready_selector="#workspace",
    ),
    DemoWindow(
        key="command",
        title="指挥中心（值班经理）",
        username="wangfang",
        path="/admin/",
        username_selector="#login-username",
        password_selector="#login-password",
        ready_selector="#app-screen",
    ),
    DemoWindow(
        key="field-chenyu",
        title="现场端（设备检修）",
        username="chenyu",
        path="/assistant/",
        username_selector="#login-username",
        password_selector="#login-password",
        ready_selector="#app-screen",
    ),
    DemoWindow(
        key="field-liming",
        title="现场端（现场运营）",
        username="liming",
        path="/assistant/",
        username_selector="#login-username",
        password_selector="#login-password",
        ready_selector="#app-screen",
    ),
    DemoWindow(
        key="channel",
        title="内部通知接入环境",
        username="liming",
        path="/simulator/wecom/",
        username_selector="#login-username",
        password_selector="#login-password",
        ready_selector="#simulator-app",
    ),
)


def _layout(index: int, total: int, screen: tuple[int, int]) -> dict[str, int]:
    """Return a tiled window geometry; keeps every window visible on one screen."""
    width, height = screen
    columns = 2 if total > 1 else 1
    rows = (total + columns - 1) // columns
    cell_w = max(640, width // columns)
    cell_h = max(420, (height - 60) // max(1, rows))
    column = index % columns
    row = index // columns
    return {
        "left": column * cell_w,
        "top": 40 + row * cell_h,
        "width": cell_w - 8,
        "height": cell_h - 8,
    }


def _password() -> str:
    for name in ("SCENIC_DEMO_PASSWORD", "SCENIC_ACCOUNT_PASSWORD", "SCENIC_E2E_PASSWORD"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise SystemExit(
        "Set SCENIC_DEMO_PASSWORD (the shared scenic demo password) before launching"
    )


def launch(
    *,
    base_url: str,
    password: str,
    channel: str,
    headless: bool,
    screen: tuple[int, int],
    screenshot_dir: Path | None,
    keep_open_seconds: int | None,
    verify_only: bool,
) -> int:
    from playwright.sync_api import sync_playwright

    failures: list[str] = []
    with sync_playwright() as playwright:
        sessions = []
        try:
            for index, window in enumerate(DEMO_WINDOWS):
                geometry = _layout(index, len(DEMO_WINDOWS), screen)
                browser = playwright.chromium.launch(
                    channel=channel,
                    headless=headless,
                    args=[
                        f"--window-position={geometry['left']},{geometry['top']}",
                        f"--window-size={geometry['width']},{geometry['height']}",
                    ],
                )
                context = browser.new_context(
                    viewport={"width": geometry["width"], "height": geometry["height"] - 90}
                )
                page = context.new_page()
                url = f"{base_url.rstrip('/')}{window.path}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    page.fill(window.username_selector, window.username)
                    page.fill(window.password_selector, password)
                    page.click("button[type=submit]")
                    page.wait_for_selector(window.ready_selector, state="visible", timeout=30_000)
                    print(f"[ok]   {window.title:<24} {window.username:<15} {url}")
                except Exception as exc:  # noqa: BLE001 - report every role, keep the rest open
                    failures.append(f"{window.key}: {type(exc).__name__}: {exc}")
                    print(f"[FAIL] {window.title:<24} {window.username:<15} {exc}")
                if screenshot_dir is not None:
                    screenshot_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        page.screenshot(path=str(screenshot_dir / f"{window.key}.png"))
                    except Exception as exc:  # noqa: BLE001
                        print(f"[warn] screenshot failed for {window.key}: {exc}")
                sessions.append((window, browser, context, page))

            if verify_only or headless:
                return 1 if failures else 0

            print()
            print("窗口已就绪，接下来请人工操作（本脚本不会代替你点击任何业务动作）。")
            print("按 Enter 关闭这些窗口。")
            if keep_open_seconds:
                try:
                    import time

                    time.sleep(keep_open_seconds)
                except KeyboardInterrupt:
                    pass
            else:
                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    pass
        finally:
            for _window, browser, context, _page in sessions:
                try:
                    context.close()
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SCENIC_DEMO_BASE_URL", "http://127.0.0.1:8090"),
        help="demo entry point (Docker stack by default: http://127.0.0.1:8090)",
    )
    parser.add_argument(
        "--browser-channel",
        default=os.environ.get("SCENIC_DEMO_BROWSER", "msedge"),
        help="installed browser channel to drive (msedge or chrome)",
    )
    parser.add_argument("--headless", action="store_true", help="do not open visible windows")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="log every role in, print the result, then close the windows",
    )
    parser.add_argument("--screen", default="1920x1080", help="screen size used to tile windows")
    parser.add_argument(
        "--screenshot-dir",
        type=Path,
        default=DEFAULT_SCREENSHOT_DIR,
        help="where to store one screenshot per role (empty string disables)",
    )
    parser.add_argument("--keep-open", type=int, default=0, help="auto close after N seconds")
    args = parser.parse_args()

    try:
        width, height = (int(part) for part in args.screen.lower().split("x", 1))
    except ValueError:
        raise SystemExit("--screen must look like 1920x1080") from None

    screenshot_dir = args.screenshot_dir if str(args.screenshot_dir) else None
    exit_code = launch(
        base_url=args.base_url,
        password=_password(),
        channel=args.browser_channel,
        headless=args.headless,
        screen=(width, height),
        screenshot_dir=screenshot_dir,
        keep_open_seconds=args.keep_open or None,
        verify_only=args.verify_only,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
