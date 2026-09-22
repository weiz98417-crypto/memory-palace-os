from src.memory_palace.core.health_page import accepts_html, render_health_status_page


def test_accepts_html_only_for_browser_accept_headers():
    assert accepts_html("text/html,application/xhtml+xml") is True
    assert accepts_html("application/json") is False
    assert accepts_html("") is False


def test_health_status_page_explains_unbounded_redis_queue():
    html = render_health_status_page(
        {
            "status": "ok",
            "queue_depth": 0,
            "queue_capacity": None,
            "queue_capacity_mode": "unbounded",
            "queue_backend": "redis_streams",
        }
    )

    assert "系统状态" in html
    assert "队列积压" in html
    assert "不限容量" in html
    assert "redis_streams" in html
    assert "/health?format=json" in html
