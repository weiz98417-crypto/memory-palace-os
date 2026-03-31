"""
alerting.py - Prometheus alerting rules for Memory Palace OS
"""
from prometheus_client import Alert, AlertManager, generate_latest
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Alert Definitions
# ─────────────────────────────────────────────────────────────────────────────

ALERTS = {
    # P0 - Critical (immediate action required)
    "MemoryPalaceDown": Alert(
        name="MemoryPalaceDown",
        msg="Memory Palace OS gateway is unreachable",
        is_job_urgent=False,
    ),
    "HighErrorRate": Alert(
        name="HighErrorRate",
        msg="Error rate exceeds 10% over 5 minutes",
        is_job_urgent=True,
    ),
    "LLMAPIFailing": Alert(
        name="LLMAPIFailing",
        msg="LLM API circuit breaker is OPEN",
        is_job_urgent=True,
    ),

    # P1 - High priority
    "HighLatency": Alert(
        name="HighLatency",
        msg="API p95 latency exceeds 5 seconds",
        is_job_urgent=False,
    ),
    "QueueBacklog": Alert(
        name="QueueBacklog",
        msg="Message queue depth exceeds 100",
        is_job_urgent=False,
    ),
    "HighTokenUsage": Alert(
        name="HighTokenUsage",
        msg="Token usage rate exceeds 80% of daily budget",
        is_job_urgent=False,
    ),

    # P2 - Medium priority
    "SlowAgentResponse": Alert(
        name="SlowAgentResponse",
        msg="Agent p95 response time exceeds 30 seconds",
        is_job_urgent=False,
    ),
    "SessionCountHigh": Alert(
        name="SessionCountHigh",
        msg="Active sessions exceed 80% of limit",
        is_job_urgent=False,
    ),
    "CircuitBreakerHalfOpen": Alert(
        name="CircuitBreakerHalfOpen",
        msg="LLM circuit breaker is HALF-OPEN - testing recovery",
        is_job_urgent=False,
    ),

    # P3 - Low priority
    "HighCPU": Alert(
        name="HighCPU",
        msg="CPU usage exceeds 80%",
        is_job_urgent=False,
    ),
    "HighMemory": Alert(
        name="HighMemory",
        msg="Memory usage exceeds 80%",
        is_job_urgent=False,
    ),
    "WatcherSLABreach": Alert(
        name="WatcherSLABreach",
        msg="SLA monitoring breach detected",
        is_job_urgent=False,
    ),

    # P4 - Informational
    "NoActivity": Alert(
        name="NoActivity",
        msg="No messages processed in the last 30 minutes",
        is_job_urgent=False,
    ),
    "SkillNotRegistered": Alert(
        name="SkillNotRegistered",
        msg="A skill failed to register during startup",
        is_job_urgent=False,
    ),
    "HotReloadTriggered": Alert(
        name="HotReloadTriggered",
        msg="Hot reload was triggered for skill/prompt update",
        is_job_urgent=False,
    ),
}


class AlertingManager:
    """管理告警规则和通知"""

    def __init__(self):
        self._active_alerts: dict[str, float] = {}  # alert_name -> start_time
        self._handlers: list[callable] = []

    def register_handler(self, handler: callable) -> None:
        """注册告警处理函数"""
        self._handlers.append(handler)

    def trigger_alert(self, name: str, description: str, severity: str = "warning") -> None:
        """触发一个告警"""
        import time
        now = time.time()

        if name not in self._active_alerts:
            self._active_alerts[name] = now
            for handler in self._handlers:
                try:
                    handler(name, description, severity)
                except Exception as e:
                    logger.error(f"Alert handler failed: {e}")

    def resolve_alert(self, name: str) -> None:
        """解决一个告警"""
        if name in self._active_alerts:
            duration = time.time() - self._active_alerts[name]
            del self._active_alerts[name]
            logger.info(f"Alert '{name}' resolved after {duration:.1f}s")

    def get_active_alerts(self) -> list[str]:
        """获取当前活跃的告警列表"""
        return list(self._active_alerts.keys())

    def is_alert_firing(self, name: str) -> bool:
        """检查告警是否正在触发"""
        return name in self._active_alerts


# ─────────────────────────────────────────────────────────────────────────────
# Convenience alert trigger helpers
# ─────────────────────────────────────────────────────────────────────────────

_manager: Optional[AlertingManager] = None


def get_alerting_manager() -> AlertingManager:
    global _manager
    if _manager is None:
        _manager = AlertingManager()
    return _manager


def send_alert(name: str, description: str, severity: str = "warning") -> None:
    """发送告警通知（同时写入 metrics 和触发处理函数）"""
    mgr = get_alerting_manager()
    mgr.trigger_alert(name, description, severity)
    logger.warning(f"[ALERT:{severity.upper()}] {name}: {description}")


def resolve_alert(name: str) -> None:
    """解决告警"""
    get_alerting_manager().resolve_alert(name)
