"""
request_metrics.py - HTTP 请求指标收集器
"""
from prometheus_client import Counter, Histogram

# Histogram 分桶边界（秒）
REQUEST_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0)
SIZE_BUCKETS = (100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000)

# HTTP 请求计数器
http_requests_total = Counter(
    "memory_palace_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"]
)

# HTTP 请求延迟分布
http_request_duration_seconds = Histogram(
    "memory_palace_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=REQUEST_DURATION_BUCKETS
)

# HTTP 请求大小
http_request_size_bytes = Histogram(
    "memory_palace_http_request_size_bytes",
    "HTTP request size in bytes",
    ["method", "endpoint"],
    buckets=SIZE_BUCKETS
)

# HTTP 响应大小
http_response_size_bytes = Histogram(
    "memory_palace_http_response_size_bytes",
    "HTTP response size in bytes",
    ["method", "endpoint"],
    buckets=SIZE_BUCKETS
)


class RequestMetricsCollector:
    """HTTP 请求指标收集器"""

    @staticmethod
    def record_request(method: str, endpoint: str, status_code: int,
                      duration: float, request_size: int = 0,
                      response_size: int = 0) -> None:
        """记录一次 HTTP 请求的指标"""
        labels = {"method": method, "endpoint": endpoint, "status_code": str(status_code)}
        http_requests_total.labels(**labels).inc()
        http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)
        if request_size > 0:
            http_request_size_bytes.labels(method=method, endpoint=endpoint).observe(request_size)
        if response_size > 0:
            http_response_size_bytes.labels(method=method, endpoint=endpoint).observe(response_size)


__all__ = ["RequestMetricsCollector"]
