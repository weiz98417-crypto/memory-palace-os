"""
queue_metrics.py - 消息队列指标收集器
"""
from prometheus_client import Counter, Gauge, Histogram

DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0)

# 队列深度
queue_depth = Gauge(
    "memory_palace_queue_depth",
    "Current message queue depth",
    ["queue_name"]
)

# 队列最大深度
queue_max_depth = Gauge(
    "memory_palace_queue_max_depth",
    "Maximum message queue depth",
    ["queue_name"]
)

# 消息处理计数器
queue_messages_processed_total = Counter(
    "memory_palace_queue_messages_processed_total",
    "Total messages processed from queue",
    ["queue_name", "status"]
)

# 消息处理时长
queue_processing_duration_seconds = Histogram(
    "memory_palace_queue_processing_duration_seconds",
    "Queue message processing duration",
    ["queue_name", "skill"],
    buckets=DURATION_BUCKETS
)


class QueueMetricsCollector:
    """队列指标收集器"""

    @staticmethod
    def update_queue_depth(queue_name: str, current_depth: int, max_depth: int = 0) -> None:
        """更新队列深度"""
        queue_depth.labels(queue_name=queue_name).set(current_depth)
        if max_depth > 0:
            queue_max_depth.labels(queue_name=queue_name).set(max_depth)

    @staticmethod
    def record_message_processed(queue_name: str, status: str,
                                 duration: float, skill: str = "unknown") -> None:
        """
        记录消息处理结果
        :param status: success / failed / dropped
        """
        queue_messages_processed_total.labels(queue_name=queue_name, status=status).inc()
        queue_processing_duration_seconds.labels(queue_name=queue_name, skill=skill).observe(duration)


__all__ = ["QueueMetricsCollector"]
