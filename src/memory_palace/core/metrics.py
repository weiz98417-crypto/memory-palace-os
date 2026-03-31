"""
metrics.py · Prometheus 指标采集模块
================================================================
职责：
  1. 统一封装 Prometheus Python Client，提供标准化指标定义。
  2. 采集业务指标：请求延迟、QPS、Token消耗、队列深度、Agent调用。
  3. 提供指标注册表，供 gateway.py 的 /metrics 端点使用。
  4. 支持 Histogram/Counter/Gauge/Gauge 等多类型指标。
"""

import time
import asyncio
from typing import Optional, Dict, Any, Callable
from functools import wraps
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    Summary,
    Info,
    REGISTRY,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
    ExceptionCounter,
    Timer,
)
from loguru import logger

# ==============================================================================
# 配置
# ==============================================================================

# 指标命名空间前缀
NAMESPACE = "memory_palace"

# 指标维度标签
DEFAULT_LABELS = ["service", "version"]


# ==============================================================================
# 指标类定义
# ==============================================================================

@dataclass
class MetricsConfig:
    """指标配置"""
    # Histogram 分桶边界 (秒)
    request_duration_buckets: tuple = field(
        default_factory=lambda: (
            0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0
        )
    )
    # Token 消耗分桶
    token_buckets: tuple = field(
        default_factory=lambda: (
            100, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000
        )
    )
    # 队列深度分桶
    queue_depth_buckets: tuple = field(
        default_factory=lambda: (
            10, 50, 100, 250, 500, 750, 1000, 2500, 5000, 10000
        )
    )


# ==============================================================================
# 全局指标注册表
# ==============================================================================

class MetricsRegistry:
    """指标注册表 - 单例模式"""

    _instance: Optional["MetricsRegistry"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._config = MetricsConfig()
        self._custom_metrics: Dict[str, Any] = {}

        # 初始化所有指标
        self._init_core_metrics()
        self._init_business_metrics()

    def _init_core_metrics(self):
        """初始化核心系统指标"""

        # ─────────────────────────────────────────────────────────────
        # 请求指标
        # ─────────────────────────────────────────────────────────────

        # HTTP 请求计数器
        self.http_requests_total = Counter(
            f"{NAMESPACE}_http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status_code"]
        )

        # HTTP 请求延迟分布
        self.http_request_duration_seconds = Histogram(
            f"{NAMESPACE}_http_request_duration_seconds",
            "HTTP request latency in seconds",
            ["method", "endpoint"],
            buckets=self._config.request_duration_buckets
        )

        # HTTP 请求大小
        self.http_request_size_bytes = Histogram(
            f"{NAMESPACE}_http_request_size_bytes",
            "HTTP request size in bytes",
            ["method", "endpoint"],
            buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000)
        )

        # HTTP 响应大小
        self.http_response_size_bytes = Histogram(
            f"{NAMESPACE}_http_response_size_bytes",
            "HTTP response size in bytes",
            ["method", "endpoint"],
            buckets=(100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000)
        )

        # ─────────────────────────────────────────────────────────────
        # 连接池指标
        # ─────────────────────────────────────────────────────────────

        # 数据库连接池
        self.db_connections_active = Gauge(
            f"{NAMESPACE}_db_connections_active",
            "Active database connections",
            ["db_name"]
        )

        self.db_connections_idle = Gauge(
            f"{NAMESPACE}_db_connections_idle",
            "Idle database connections",
            ["db_name"]
        )

        self.db_connections_total = Gauge(
            f"{NAMESPACE}_db_connections_total",
            "Total database connections in pool",
            ["db_name"]
        )

        # Redis 连接池
        self.redis_connections_active = Gauge(
            f"{NAMESPACE}_redis_connections_active",
            "Active Redis connections",
            ["redis_name"]
        )

        # ─────────────────────────────────────────────────────────────
        # 系统资源指标
        # ─────────────────────────────────────────────────────────────

        # CPU 使用率
        self.cpu_usage_percent = Gauge(
            f"{NAMESPACE}_cpu_usage_percent",
            "CPU usage percentage"
        )

        # 内存使用
        self.memory_usage_bytes = Gauge(
            f"{NAMESPACE}_memory_usage_bytes",
            "Memory usage in bytes",
            ["memory_type"]  # rss, vms, used, available
        )

        # 线程数
        self.threads_count = Gauge(
            f"{NAMESPACE}_threads_count",
            "Number of threads",
            ["thread_type"]  # active, daemon
        )

        # ─────────────────────────────────────────────────────────────
        # 队列指标
        # ─────────────────────────────────────────────────────────────

        self.queue_depth = Gauge(
            f"{NAMESPACE}_queue_depth",
            "Current message queue depth",
            ["queue_name"]
        )

        self.queue_max_depth = Gauge(
            f"{NAMESPACE}_queue_max_depth",
            "Maximum message queue depth",
            ["queue_name"]
        )

        self.queue_messages_processed_total = Counter(
            f"{NAMESPACE}_queue_messages_processed_total",
            "Total messages processed from queue",
            ["queue_name", "status"]  # status: success, failed, dropped
        )

        self.queue_processing_duration_seconds = Histogram(
            f"{NAMESPACE}_queue_processing_duration_seconds",
            "Queue message processing duration",
            ["queue_name", "skill"],
            buckets=self._config.request_duration_buckets
        )

    def _init_business_metrics(self):
        """初始化业务指标"""

        # ─────────────────────────────────────────────────────────────
        # LLM 调用指标
        # ─────────────────────────────────────────────────────────────

        self.llm_requests_total = Counter(
            f"{NAMESPACE}_llm_requests_total",
            "Total LLM API requests",
            ["provider", "model", "status"]  # status: success, error, timeout
        )

        self.llm_request_duration_seconds = Histogram(
            f"{NAMESPACE}_llm_request_duration_seconds",
            "LLM request duration in seconds",
            ["provider", "model"],
            buckets=self._config.request_duration_buckets
        )

        self.llm_tokens_total = Counter(
            f"{NAMESPACE}_llm_tokens_total",
            "Total tokens consumed",
            ["provider", "model", "token_type"]  # token_type: input, output
        )

        self.llm_tokens_per_request = Histogram(
            f"{NAMESPACE}_llm_tokens_per_request",
            "Tokens per LLM request",
            ["provider", "model", "token_type"],
            buckets=self._config.token_buckets
        )

        self.llm_cost_total = Counter(
            f"{NAMESPACE}_llm_cost_total",
            "Total LLM API cost in USD",
            ["provider", "model"]
        )

        self.llm_errors_total = Counter(
            f"{NAMESPACE}_llm_errors_total",
            "Total LLM errors",
            ["provider", "model", "error_type"]
        )

        # ─────────────────────────────────────────────────────────────
        # Agent 调用指标
        # ─────────────────────────────────────────────────────────────

        self.agent_requests_total = Counter(
            f"{NAMESPACE}_agent_requests_total",
            "Total agent requests",
            ["agent_name", "status"]
        )

        self.agent_request_duration_seconds = Histogram(
            f"{NAMESPACE}_agent_request_duration_seconds",
            "Agent request duration in seconds",
            ["agent_name"],
            buckets=self._config.request_duration_buckets
        )

        self.agent_handoffs_total = Counter(
            f"{NAMESPACE}_agent_handoffs_total",
            "Total agent handoffs",
            ["from_agent", "to_agent", "reason"]
        )

        self.active_sessions = Gauge(
            f"{NAMESPACE}_active_sessions",
            "Number of active user sessions",
            ["agent_name"]
        )

        # ─────────────────────────────────────────────────────────────
        # 消息处理指标
        # ─────────────────────────────────────────────────────────────

        self.messages_received_total = Counter(
            f"{NAMESPACE}_messages_received_total",
            "Total messages received",
            ["source", "msg_type"]  # source: wechat, api
        )

        self.messages_processed_total = Counter(
            f"{NAMESPACE}_messages_processed_total",
            "Total messages processed",
            ["msg_type", "status"]
        )

        self.messages_response_time_seconds = Histogram(
            f"{NAMESPACE}_messages_response_time_seconds",
            "Message response time",
            ["msg_type"],
            buckets=self._config.request_duration_buckets
        )

        # ─────────────────────────────────────────────────────────────
        # 知识库指标
        # ─────────────────────────────────────────────────────────────

        self.vector_searches_total = Counter(
            f"{NAMESPACE}_vector_searches_total",
            "Total vector searches",
            ["status"]  # success, no_results, error
        )

        self.vector_search_duration_seconds = Histogram(
            f"{NAMESPACE}_vector_search_duration_seconds",
            "Vector search duration",
            buckets=self._config.request_duration_buckets
        )

        self.vector_index_size = Gauge(
            f"{NAMESPACE}_vector_index_size",
            "Size of vector index",
            ["index_name"]
        )

        # ─────────────────────────────────────────────────────────────
        # 告警指标
        # ─────────────────────────────────────────────────────────────

        self.alerts_total = Counter(
            f"{NAMESPACE}_alerts_total",
            "Total alerts triggered",
            ["level", "type"]  # level: P0, P1, P2, P3, P4
        )

    def register_custom_metric(self, name: str, metric: Any):
        """注册自定义指标"""
        self._custom_metrics[name] = metric

    def get_custom_metric(self, name: str) -> Optional[Any]:
        """获取自定义指标"""
        return self._custom_metrics.get(name)

    def get_registry(self) -> CollectorRegistry:
        """获取 Prometheus 注册表"""
        return REGISTRY


# ==============================================================================
# 全局指标实例
# ==============================================================================

_metrics_registry: Optional[MetricsRegistry] = None


def get_metrics_registry() -> MetricsRegistry:
    """获取指标注册表单例"""
    global _metrics_registry
    if _metrics_registry is None:
        _metrics_registry = MetricsRegistry()
    return _metrics_registry


def init_metrics() -> MetricsRegistry:
    """初始化指标收集器"""
    registry = get_metrics_registry()
    logger.info("✅ 指标收集器初始化完成")
    return registry


# ==============================================================================
# 便捷装饰器
# ==============================================================================

def track_request_metrics(endpoint: str):
    """追踪 HTTP 请求指标的装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            registry = get_metrics_registry()
            method = "UNKNOWN"

            start_time = time.perf_counter()
            status_code = 500

            try:
                result = await func(*args, **kwargs)
                status_code = getattr(result, "status_code", 200) if hasattr(result, "status_code") else 200
                return result
            except Exception as e:
                status_code = 500
                raise
            finally:
                duration = time.perf_counter() - start_time
                registry.http_requests_total.labels(
                    method=method,
                    endpoint=endpoint,
                    status_code=str(status_code)
                ).inc()
                registry.http_request_duration_seconds.labels(
                    method=method,
                    endpoint=endpoint
                ).observe(duration)

        return wrapper
    return decorator


def track_llm_metrics(provider: str, model: str):
    """追踪 LLM 调用指标的装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            registry = get_metrics_registry()
            start_time = time.perf_counter()
            status = "success"

            try:
                result = await func(*args, **kwargs)

                # 尝试提取 token 消耗
                if isinstance(result, dict):
                    input_tokens = result.get("usage", {}).get("prompt_tokens", 0)
                    output_tokens = result.get("usage", {}).get("completion_tokens", 0)

                    if input_tokens > 0:
                        registry.llm_tokens_total.labels(
                            provider=provider,
                            model=model,
                            token_type="input"
                        ).inc(input_tokens)
                        registry.llm_tokens_per_request.labels(
                            provider=provider,
                            model=model,
                            token_type="input"
                        ).observe(input_tokens)

                    if output_tokens > 0:
                        registry.llm_tokens_total.labels(
                            provider=provider,
                            model=model,
                            token_type="output"
                        ).inc(output_tokens)
                        registry.llm_tokens_per_request.labels(
                            provider=provider,
                            model=model,
                            token_type="output"
                        ).observe(output_tokens)

                return result
            except Exception as e:
                status = "error"
                registry.llm_errors_total.labels(
                    provider=provider,
                    model=model,
                    error_type=type(e).__name__
                ).inc()
                raise
            finally:
                duration = time.perf_counter() - start_time
                registry.llm_requests_total.labels(
                    provider=provider,
                    model=model,
                    status=status
                ).inc()
                registry.llm_request_duration_seconds.labels(
                    provider=provider,
                    model=model
                ).observe(duration)

        return wrapper
    return decorator


def track_agent_metrics(agent_name: str):
    """追踪 Agent 调用指标的装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            registry = get_metrics_registry()
            start_time = time.perf_counter()
            status = "success"

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start_time
                registry.agent_requests_total.labels(
                    agent_name=agent_name,
                    status=status
                ).inc()
                registry.agent_request_duration_seconds.labels(
                    agent_name=agent_name
                ).observe(duration)

        return wrapper
    return decorator


# ==============================================================================
# 指标更新辅助函数
# ==============================================================================

def update_queue_metrics(queue_name: str, current_depth: int, max_depth: int):
    """更新队列指标"""
    registry = get_metrics_registry()
    registry.queue_depth.labels(queue_name=queue_name).set(current_depth)
    registry.queue_max_depth.labels(queue_name=queue_name).set(max_depth)


def update_system_metrics(cpu_percent: float, memory_rss: int, memory_available: int):
    """更新系统资源指标"""
    registry = get_metrics_registry()
    registry.cpu_usage_percent.set(cpu_percent)
    registry.memory_usage_bytes.labels(memory_type="rss").set(memory_rss)
    registry.memory_usage_bytes.labels(memory_type="available").set(memory_available)


def record_agent_handoff(from_agent: str, to_agent: str, reason: str):
    """记录 Agent 交接"""
    registry = get_metrics_registry()
    registry.agent_handoffs_total.labels(
        from_agent=from_agent,
        to_agent=to_agent,
        reason=reason
    ).inc()


def record_alert(level: str, alert_type: str, message: str):
    """记录告警"""
    registry = get_metrics_registry()
    registry.alerts_total.labels(level=level, type=alert_type).inc()
    logger.warning(f"🚨 [{level}] {alert_type}: {message}")


# ==============================================================================
# 异步指标采集器
# ==============================================================================

class AsyncMetricsCollector:
    """异步指标采集器 - 后台定期更新系统指标"""

    def __init__(self, interval: float = 30.0):
        self.interval = interval
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """启动指标采集"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._collect_loop())
        logger.info(f"🚀 异步指标采集器已启动 (间隔: {self.interval}s)")

    async def stop(self):
        """停止指标采集"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("👋 异步指标采集器已停止")

    async def _collect_loop(self):
        """采集循环"""
        while self._running:
            try:
                await self._collect_system_metrics()
                await self._collect_queue_metrics()
            except Exception as e:
                logger.error(f"指标采集失败: {e}")

            await asyncio.sleep(self.interval)

    async def _collect_system_metrics(self):
        """采集系统指标"""
        try:
            import psutil

            process = psutil.Process()
            memory_info = process.memory_info()

            cpu_percent = psutil.cpu_percent(interval=1)
            memory_rss = memory_info.rss
            memory_available = psutil.virtual_memory().available

            update_system_metrics(cpu_percent, memory_rss, memory_available)

        except ImportError:
            logger.debug("psutil 未安装，跳过系统指标采集")

    async def _collect_queue_metrics(self):
        """采集队列指标"""
        # 此处需要访问应用队列状态，暂留接口
        pass


# ==============================================================================
# 导出
# ==============================================================================

__all__ = [
    # 核心
    "MetricsRegistry",
    "get_metrics_registry",
    "init_metrics",
    "MetricsConfig",

    # 装饰器
    "track_request_metrics",
    "track_llm_metrics",
    "track_agent_metrics",

    # 辅助函数
    "update_queue_metrics",
    "update_system_metrics",
    "record_agent_handoff",
    "record_alert",

    # 异步采集
    "AsyncMetricsCollector",
]

    