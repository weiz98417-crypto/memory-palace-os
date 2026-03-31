"""
agent_metrics.py - Agent 执行指标收集器
"""
from prometheus_client import Counter, Histogram

DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0, 30.0)

# Agent 请求计数器
agent_requests_total = Counter(
    "memory_palace_agent_requests_total",
    "Total agent requests",
    ["agent_name", "status"]
)

# Agent 请求延迟
agent_request_duration_seconds = Histogram(
    "memory_palace_agent_request_duration_seconds",
    "Agent request duration in seconds",
    ["agent_name"],
    buckets=DURATION_BUCKETS
)

# Agent 交接计数器
agent_handoffs_total = Counter(
    "memory_palace_agent_handoffs_total",
    "Total agent handoffs",
    ["from_agent", "to_agent", "reason"]
)

# 活跃会话数
active_sessions = Gauge(
    "memory_palace_active_sessions",
    "Number of active user sessions",
    ["agent_name"]
)


class AgentMetricsCollector:
    """Agent 指标收集器"""

    @staticmethod
    def record_agent_call(agent_name: str, duration_seconds: float, success: bool = True) -> None:
        """记录一次 Agent 调用"""
        status = "success" if success else "error"
        agent_requests_total.labels(agent_name=agent_name, status=status).inc()
        agent_request_duration_seconds.labels(agent_name=agent_name).observe(duration_seconds)

    @staticmethod
    def record_handoff(from_agent: str, to_agent: str, reason: str = "task_complete") -> None:
        """记录一次 Agent 交接"""
        agent_handoffs_total.labels(from_agent=from_agent, to_agent=to_agent, reason=reason).inc()

    @staticmethod
    def set_active_sessions(agent_name: str, count: int) -> None:
        """设置活跃会话数"""
        active_sessions.labels(agent_name=agent_name).set(count)


__all__ = ["AgentMetricsCollector"]
