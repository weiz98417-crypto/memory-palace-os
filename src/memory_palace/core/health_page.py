"""Human-readable status page for the lightweight health probe."""

from __future__ import annotations

from html import escape
from typing import Any


def accepts_html(accept_header: str) -> bool:
    return "text/html" in (accept_header or "").lower()


def render_health_status_page(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "unknown")
    queue_depth = escape(str(payload.get("queue_depth", "unknown")))
    capacity = payload.get("queue_capacity")
    capacity_text = "不限容量" if capacity is None else str(capacity)
    capacity_mode = escape(str(payload.get("queue_capacity_mode") or "unknown"))
    backend = escape(str(payload.get("queue_backend") or "unknown"))
    status_class = "ok" if status in {"ok", "healthy"} else "warn" if status == "degraded" else "bad"
    status_label = {"ok": "正常", "healthy": "正常", "degraded": "降级"}.get(status, "异常")

    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="10">
  <title>Memory Palace OS · 系统状态</title>
  <style>
    :root {{ color-scheme: dark; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; padding: clamp(24px, 5vw, 64px); color: #e9f2ff; background: radial-gradient(circle at 18% 8%, #173a5e 0, #091426 38%, #050b16 100%); }}
    main {{ width: min(1080px, 100%); margin: 0 auto; }}
    header {{ display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 28px; }}
    .eyebrow {{ color: #82c7ff; font-size: 12px; letter-spacing: .16em; }}
    h1 {{ margin: 8px 0; font-size: clamp(28px, 4vw, 48px); letter-spacing: -.04em; }}
    p {{ color: #a9bfd8; line-height: 1.7; }}
    .badge {{ display: inline-flex; align-items: center; gap: 8px; padding: 10px 16px; border-radius: 999px; font-weight: 700; white-space: nowrap; }}
    .badge::before {{ width: 9px; height: 9px; border-radius: 50%; background: currentColor; content: ""; }}
    .badge.ok {{ color: #73e6ba; background: rgba(45, 190, 139, .14); border: 1px solid rgba(115, 230, 186, .34); }}
    .badge.warn {{ color: #ffd479; background: rgba(255, 193, 72, .14); border: 1px solid rgba(255, 212, 121, .34); }}
    .badge.bad {{ color: #ff9ba5; background: rgba(255, 92, 115, .14); border: 1px solid rgba(255, 155, 165, .34); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 16px; margin: 28px 0; }}
    .card {{ padding: 22px; border: 1px solid rgba(170, 210, 255, .18); border-radius: 18px; background: rgba(10, 25, 48, .72); box-shadow: 0 22px 60px rgba(0, 4, 14, .28); backdrop-filter: blur(14px); }}
    .label {{ color: #8ca8c6; font-size: 13px; }}
    .value {{ margin-top: 10px; color: #fff; font-size: 28px; font-weight: 720; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 26px; }}
    a {{ display: inline-flex; padding: 11px 15px; border: 1px solid rgba(150, 204, 255, .3); border-radius: 10px; color: #d9edff; background: rgba(23, 61, 99, .55); text-decoration: none; }}
    a:hover {{ border-color: #72c6ff; background: rgba(34, 91, 145, .72); }}
    footer {{ margin-top: 30px; color: #718ba8; font-size: 12px; }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="eyebrow">MEMORY PALACE OS · HEALTH</div>
        <h1>系统状态</h1>
        <p>这是轻量存活状态页，只展示进程和队列积压。完整依赖检查请打开 <code>/ready</code>，运维诊断请进入指挥中心的“运维诊断”。</p>
      </div>
      <span class="badge {status_class}">{status_label}</span>
    </header>
    <section class="grid">
      <article class="card"><div class="label">队列积压</div><div class="value">{queue_depth}</div></article>
      <article class="card"><div class="label">容量模式</div><div class="value">{capacity_mode}</div></article>
      <article class="card"><div class="label">队列容量</div><div class="value">{escape(capacity_text)}</div></article>
      <article class="card"><div class="label">队列后端</div><div class="value">{backend}</div></article>
    </section>
    <div class="actions">
      <a href="/ready">查看 /ready 依赖状态</a>
      <a href="/admin/diagnostics">进入运维诊断</a>
      <a href="/health?format=json">查看原始 JSON</a>
      <a href="http://127.0.0.1:8091/">打开 Hatchet</a>
      <a href="http://127.0.0.1:16686/">打开 Jaeger</a>
    </div>
    <footer>页面每 10 秒自动刷新。Docker/Kubernetes 探针仍使用 JSON 响应。</footer>
  </main>
</body>
</html>'''
